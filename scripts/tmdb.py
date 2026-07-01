"""TMDB (The Movie Database) API client — cinema poster lookup.

Phase 3 / T22. Wraps the TMDB v3 API to look up poster images for cinema
events by title. Uses stdlib only (urllib + json) — no new dependencies.

Attribution
-----------
TMDB requires visible attribution wherever their data/images are shown.
Required text (per https://www.themoviedb.org/documentation/api/terminology):

    This product uses the TMDB API but is not endorsed or certified by TMDB.

This text is rendered in the cinema section footer of index.html (see
ATTRIBUTION_HTML constant below).

API key
-------
Read from $TMDB_API_KEY or the project .env (TMDB_API_KEY=...). v3 keys
are designed for client-side use, so we keep the key on disk.

Caching
-------
All lookups are cached in data/poster_cache.json, keyed by normalized
title. Cache hits avoid the network entirely. The cache is append-only
(we never invalidate) — TMDB poster paths are stable.
"""
from __future__ import annotations

import json
import os
import re
import sys
import time
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Optional


# ---- Configuration ---------------------------------------------------------

API_BASE = "https://api.themoviedb.org/3"
IMAGE_BASE = "https://image.tmdb.org/t/p"
DEFAULT_SIZE = "w342"  # cinema cards — good balance for retina + load time

# TMDB attribution strings. The HTML is embedded in the cinema section
# footer of index.html. The plain text is what TMDB's API ToS require.
ATTRIBUTION_TEXT = (
    "This product uses the TMDB API but is not endorsed or certified by TMDB."
)
ATTRIBUTION_LOGO_URL = (
    "https://www.themoviedb.org/assets/2/v4/logos/v2/"
    "blue_short-8e7b30f73a4020692ccca9c88bafe5dcb6f8a62a4c6bc55cd9ba82bb"
    "2cd95f6c.svg"
)

# Inline HTML for the cinema footer. Single concatenated string with no
# embedded `</` so the file parses cleanly. Embeds the logo + the
# required attribution text in the title attribute for compliance even
# when logos are blocked by ad-blockers / CSP.
_ATTRIBUTION_DIV_OPEN = '<div class="tmdb-attr" title="' + ATTRIBUTION_TEXT + '">'
_ATTRIBUTION_LOGO_LINK = (
    '<a href="https://www.themoviedb.org/" target="_blank" rel="noopener">'
    '<img src="' + ATTRIBUTION_LOGO_URL + '" alt="TMDB" class="tmdb-logo">'
 '</a></div>'
)
ATTRIBUTION_HTML = (
    _ATTRIBUTION_DIV_OPEN
    + '<span>Posters & metadata</span>'
    + _ATTRIBUTION_LOGO_LINK
)

# Project-relative cache file. Resolved relative to the repo root so it
# works whether the script is run from host venv or inside the container.
def _resolve_cache_path() -> Path:
    """Locate data/poster_cache.json — host path or in-container path."""
    here = Path(__file__).resolve().parent
    for d in (
        here.parent / "data",                    # host layout
        Path("/opt/data/chamonix-events/data"),  # container layout
    ):
        if d.exists():
            return d / "poster_cache.json"
    return here.parent / "data" / "poster_cache.json"


CACHE_PATH = _resolve_cache_path()


# ---- Key loading -----------------------------------------------------------

def get_api_key() -> Optional[str]:
    """Return the TMDB v3 API key from env or project .env.

    Returns None if no key is configured (caller should skip enrichment).
    """
    key = os.environ.get("TMDB_API_KEY")
    if key:
        return key
    for env_path in (
        Path("/docker/hermes-agent-2bpx/data/.env"),
        Path("/opt/data/.env"),
    ):
        if env_path.exists():
            try:
                for line in env_path.read_text(encoding="utf-8").splitlines():
                    m = re.match(r'^TMDB_API_KEY\s*=\s*(.+?)\s*$', line)
                    if m:
                        return m.group(1).strip().strip('"').strip("'")
            except OSError:
                continue
    return None


# ---- Cache -----------------------------------------------------------------

def _load_cache() -> dict[str, dict]:
    """Read cache from disk. Returns {} if missing or unreadable."""
    try:
        return json.loads(CACHE_PATH.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return {}


def _save_cache(cache: dict[str, dict]) -> None:
    """Persist cache atomically. Best-effort — never raises."""
    try:
        CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
        tmp = CACHE_PATH.with_suffix(".tmp")
        tmp.write_text(
            json.dumps(cache, ensure_ascii=False, indent=2, sort_keys=True),
            encoding="utf-8",
        )
        os.replace(tmp, CACHE_PATH)
    except OSError:
        pass  # cache is optional


def _normalize_title(title: str) -> str:
    """Cache key — strip diacritics, lowercase, collapse whitespace.

    Same convention as scripts/dedup.py so a title in events table
    produces the same key as one in the cache.
    """
    s = (title or "").strip()
    s = unicodedata.normalize("NFKD", s)
    s = "".join(c for c in s if not unicodedata.combining(c))
    s = re.sub(r"\s+", " ", s).lower().strip()
    return s


# ---- HTTP ------------------------------------------------------------------

def _http_get(url: str, timeout: float = 8.0) -> Optional[dict]:
    """GET a JSON URL. Returns parsed JSON or None on error.

    Never raises — TMDB failures shouldn't break the scraper.
    """
    req = urllib.request.Request(url, headers={
        "Accept": "application/json",
        "User-Agent": "chamonix-events/1.0 (T22 TMDB enrichment)",
    })
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except (urllib.error.URLError, urllib.error.HTTPError,
            json.JSONDecodeError, TimeoutError, OSError) as exc:
        print(f"  [tmdb] http error: {exc}", file=sys.stderr)
        return None


# ---- Core lookups ----------------------------------------------------------

def search_movie(
    title: str,
    year: Optional[int] = None,
    language: str = "fr-FR",
    api_key: Optional[str] = None,
) -> Optional[dict]:
    """Look up a movie by title. Returns the best match dict or None.

    Best match = highest-popularity result (TMDB's default sort). If
    `year` is given, results are filtered to that release year via
    `primary_release_year`.

    Returns a dict with at least: id, title, poster_path, release_date.
    Returns None if no key, no match, or any error.
    """
    key = api_key or get_api_key()
    if not key:
        return None
    if not title or not title.strip():
        return None

    params = {
        "api_key": key,
        "query": title,
        "language": language,
        "include_adult": "false",
    }
    if year:
        params["primary_release_year"] = str(year)

    url = API_BASE + "/search/movie?" + urllib.parse.urlencode(params)
    data = _http_get(url)
    if not data:
        return None
    results = data.get("results") or []
    if not results:
        return None
    # First result is highest popularity. Prefer one with a poster.
    best = None
    for r in results[:5]:
        if r.get("poster_path"):
            best = r
            break
    if not best:
        best = results[0]
    if not best.get("poster_path"):
        return None
    return best


def get_poster_url(poster_path: str, size: str = DEFAULT_SIZE) -> str:
    """Build a full TMDB image URL from a poster_path like '/abc.jpg'."""
    if not poster_path:
        return ""
    if not poster_path.startswith("/"):
        poster_path = "/" + poster_path
    return IMAGE_BASE + "/" + size + poster_path


# ---- Cached lookup ---------------------------------------------------------

def lookup_poster(
    title: str,
    year: Optional[int] = None,
    language: str = "fr-FR",
    use_cache: bool = True,
    api_key: Optional[str] = None,
) -> Optional[str]:
    """Cached TMDB poster lookup. Returns full image URL or None.

    Caches both hits AND misses (None) so dead titles don't get re-queried.
    """
    norm = _normalize_title(title)
    if not norm:
        return None
    cache = _load_cache() if use_cache else {}

    if use_cache and norm in cache:
        cached = cache[norm]
        if year is None or cached.get("year") == year:
            path = cached.get("poster_path")
            return get_poster_url(path) if path else None

    movie = search_movie(title, year=year, language=language, api_key=api_key)
    if use_cache:
        cache[norm] = {
            "title": title,
            "year": year,
            "poster_path": movie.get("poster_path") if movie else None,
            "tmdb_id": movie.get("id") if movie else None,
            "fetched_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        }
        _save_cache(cache)

    if not movie or not movie.get("poster_path"):
        return None
    return get_poster_url(movie["poster_path"])


def lookup_title_year(title: str) -> Optional[int]:
    """Extract a 4-digit year from a movie title (e.g., 'Dune (2021)' → 2021)."""
    m = re.search(r"\b(?:19|20)\d{2}\b", title or "")
    return int(m.group(0)) if m else None


def enrich_cinema_event(
    event: dict,
    api_key: Optional[str] = None,
    overwrite: bool = False,
) -> bool:
    """Fill event['image_url'] from TMDB if not already set.

    Returns True if image_url was set/modified, False otherwise.
    Never raises.
    """
    if not event.get("title"):
        return False
    if event.get("image_url") and not overwrite:
        return False  # already have one
    year = lookup_title_year(event["title"])
    try:
        url = lookup_poster(event["title"], year=year, api_key=api_key)
    except Exception as exc:  # defensive — should never happen
        print(f"  [tmdb] enrich error: {exc}", file=sys.stderr)
        return False
    if not url:
        return False
    event["image_url"] = url
    return True


# ---- CLI -------------------------------------------------------------------

def _cli() -> int:
    """Simple CLI for testing and one-shot backfill.

    Usage:
        python -m scripts.tmdb search "<title>" [year]
        python -m scripts.tmdb poster <poster_path>
        python -m scripts.tmdb key
        python -m scripts.tmdb enrich "<title>"
    """
    args = sys.argv[1:]
    if not args or args[0] in ("-h", "--help"):
        print(__doc__)
        return 0
    cmd = args[0]
    if cmd == "key":
        key = get_api_key()
        if key:
            masked = key[:4] + "..." + key[-4:] if len(key) > 8 else "***"
            print("TMDB_API_KEY: " + masked)
            return 0
        print("TMDB_API_KEY not set")
        return 1
    if cmd == "poster":
        if len(args) < 2:
            print("usage: poster <path>")
            return 1
        print(get_poster_url(args[1]))
        return 0
    if cmd == "search":
        if len(args) < 2:
            print("usage: search <title> [year]")
            return 1
        title = args[1]
        year = int(args[2]) if len(args) > 2 and args[2].isdigit() else None
        result = search_movie(title, year=year)
        if not result:
            print("No match for " + repr(title))
            return 1
        print(json.dumps({
            "id": result.get("id"),
            "title": result.get("title"),
            "release_date": result.get("release_date"),
            "poster_path": result.get("poster_path"),
            "poster_url": get_poster_url(result.get("poster_path", "")),
            "popularity": result.get("popularity"),
        }, indent=2, ensure_ascii=False))
        return 0
    if cmd == "enrich":
        if len(args) < 2:
            print("usage: enrich <title>")
            return 1
        title = args[1]
        year = lookup_title_year(title)
        url = lookup_poster(title, year=year)
        print("title=" + repr(title) + " year=" + str(year) +
              " -> image_url=" + (url or "(none)"))
        return 0
    print("unknown command: " + cmd)
    return 1


if __name__ == "__main__":
    sys.exit(_cli())
