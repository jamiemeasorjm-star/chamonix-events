#!/usr/bin/env python3
"""Le Vox PDF Scraper — weekly cinema schedule from cinemavox-chamonix.com"""
import json, os, re, sys
import pymupdf, ssl
from datetime import date, timedelta, datetime
from urllib.request import Request, urlopen

# Allow importing from scripts.models when invoked as a flat script
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from scripts.storage import get_storage
from scripts.sources import get_source  # T13
from scripts.scoring import compute_confidence  # T14
# T22: TMDB enrichment as a fallback after AlloCine search. The module is
# imported lazily inside _enrich_with_tmdb() so vox_pdf keeps working when
# the key isn't configured (or the module isn't present for any reason).
try:
    from scripts import tmdb as _tmdb  # type: ignore
except ImportError:  # pragma: no cover - module ships with the project
    _tmdb = None

PDF_URL = "https://cinemavox-chamonix.com/fichier/programme.pdf"
DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "data")
OUTPUT = os.path.join(DATA_DIR, "cinema_events.json")

# T13: confidence baseline derived from sources.yaml trust_level
_vox_source = get_source("vox_pdf")
VOX_CONFIDENCE = _vox_source.confidence_baseline() if _vox_source else 1.0

MONTHS = {"janvier":1,"fevrier":2,"mars":3,"avril":4,"mai":5,"juin":6,"juillet":7,
           "aout":8,"septembre":9,"octobre":10,"novembre":11,"decembre":12}

COL_RANGES = [(0, 170, 250), (1, 250, 290), (2, 290, 340), (3, 340, 380),
              (4, 380, 440), (5, 440, 490), (6, 490, 600)]

# Poster cache for films not found on AlloCine
# List updated weekly — add entries as needed for PDF-only films
POSTER_CACHE = {
    # Weekly update: add poster URLs for films not found via AlloCine search
    "SCARY MOVIE": "https://fr.web.img4.acsta.net/img/bd/e1/bde1b6a103ec4de9e8d82759bc58dd82.jpg",
    "LE VIRTUOSE": "https://fr.web.img5.acsta.net/img/a0/72/a072f3d4406da64a5e8aedbb26054ac6.jpg",
    "L'OBJET DU DELIT": "https://fr.web.img6.acsta.net/img/f1/13/f113b78c6126c1a49a0168d53497267c.jpg",
}
DESC_CACHE = {}
POSTER_SEARCH_API = "https://www.allocine.fr/recherche/?q="

def lookup(key):
    """Find poster URL for a film title. Checks cache first, then
    local data/posters/ directory, then AlloCine search."""
    norm_key = key.strip().upper()
    # Check memory cache
    if norm_key in POSTER_CACHE:
        return POSTER_CACHE[norm_key], DESC_CACHE.get(norm_key, "")
    # T36: check local posters directory first
    import hashlib
    here = os.path.dirname(os.path.abspath(__file__))
    poster_dir = os.path.join(here, "..", "data", "posters")
    slug = hashlib.sha256(key.encode("utf-8")).hexdigest()[:16]
    for ext in (".jpg", ".jpeg", ".png", ".webp"):
        local_path = os.path.join(poster_dir, f"{slug}{ext}")
        if os.path.exists(local_path):
            src = f"/data/posters/{slug}{ext}"
            POSTER_CACHE[norm_key] = src
            print(f"  POSTER LOCAL: {local_path}")
            return src, ""
    # Also try a human-readable slug
    from scripts.storage import _slug
    readable = _slug(key)
    for ext in (".jpg", ".jpeg", ".png", ".webp"):
        local_path = os.path.join(poster_dir, f"{readable}{ext}")
        if os.path.exists(local_path):
            src = f"/data/posters/{readable}{ext}"
            POSTER_CACHE[norm_key] = src
            print(f"  POSTER LOCAL: {local_path}")
            return src, ""
    # Try to find via AlloCine search
    import httpx
    from bs4 import BeautifulSoup
    try:
        query = re.sub(r"^int[.°]?\s*—\s*\d+\s+ans\s+", "", re.sub(r"—.*—", "", key)).strip()
        search_url = POSTER_SEARCH_API + query.replace(" ", "+")
        r = httpx.get(search_url, timeout=8, follow_redirects=True,
                      headers={"User-Agent": "Mozilla/5.0"})
        soup = BeautifulSoup(r.text, "html.parser")
        img = soup.find("img", {"class": "thumbnail"}) or soup.find("img", src=lambda s: s and "acsta" in (s or ""))
        if img:
            src = img.get("data-src") or img.get("src") or ""
            if src:
                POSTER_CACHE[norm_key] = src
                print(f"  POSTER FOUND: {src[:60]}...")
                return src, ""
    except Exception as e:
        print(f"  Poster lookup failed: {e}")
    return "", ""

def col_for_x(xc):
    for col_id, lo, hi in COL_RANGES:
        if lo <= xc < hi: return col_id
    return None

def slugify(title):
    s = title.lower().replace("'", "-").replace("\u2019", "-")
    s = re.sub(r'[^a-z0-9-]+', '-', s).strip('-')
    return re.sub(r'-+', '-', s)

def download_pdf():
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    req = Request(PDF_URL, headers={'User-Agent': 'Mozilla/5.0'})
    resp = urlopen(req, context=ctx)
    data = resp.read()
    pdf_path = os.path.join(DATA_DIR, "programme.pdf")
    with open(pdf_path, 'wb') as f: f.write(data)
    return pdf_path

def parse_pdf(pdf_path):
    doc = pymupdf.open(pdf_path)
    page = doc[0]
    blocks = page.get_text('dict')['blocks']
    raw_items = []
    for b in blocks:
        if 'lines' in b:
            for line in b['lines']:
                text = ''.join([s['text'] for s in line['spans']]).strip()
                if not text: continue
                x0, y0, x1, y1 = line['bbox']
                raw_items.append((y0, (x0+x1)/2, text))
    raw_items.sort(key=lambda t: t[0])

    # Parse date range
    year = month_num = day_start = day_end = None
    now = datetime.now()
    for _, _, text in raw_items:
        m = re.search(r'Du\s+(\d+)\s+au\s+(\d+)\s+([a-z]+)', text, re.IGNORECASE)
        if m:
            day_start, day_end = int(m.group(1)), int(m.group(2))
            mn = m.group(3).lower().strip()
            month_num = MONTHS.get(mn, now.month)
            year = now.year
            try: date(year, month_num, day_start)
            except ValueError: year += 1
            break
    if year is None:
        print("ERROR: Could not parse date range", file=sys.stderr)
        return [], {}, "", ""

    # Handle month boundary: "Du 27 au 2 juin" = May 27 to June 2
    if day_start > day_end:
        sm = month_num - 1
        sy = year
        if sm < 1: sm, sy = 12, year - 1
    else:
        sm, sy = month_num, year
    start_d = date(sy, sm, day_start)
    day_dates = {i: (start_d + timedelta(days=i)).isoformat() for i in range(7)}
    print(f"Date range: {day_dates[0]} to {day_dates[6]}")

    # Collect items for content area (between FILMS header and footer)
    content_items = []
    in_content = False
    for y, xc, text in raw_items:
        if text in ("FILMS", "FILMS "):
            in_content = True
            continue
        if not in_content:
            continue
        if "VF :" in text or "TARIF NORMAL" in text or "Version originale" in text:
            break
        
        if text == "L'abandon, de Vincent Garenq":
            continue
        # Skip day headers
        if re.match(r'^(Mer|Jeu|Ven|Sam|Dim|Lun|Mar)$', text):
            continue
        # Skip date numbers
        if re.match(r'^\d{1,2}$', text):
            continue
        # Skip FERMETURE
        if "FERMETURE" in text:
            continue
        content_items.append((y, xc, text))

    # T39: detect pure-metadata lines so they don't get concatenated into the wrong film
    _SECTION_MARKER_RE = re.compile(
        r'^\s*(?:(?:Summer|Little)?\s*film\s+festival)\s*$',
        re.IGNORECASE,
    )
    _PREFIX_METADATA_RE = re.compile(
        r'^\s*int\.?\s*[—\-]?\s*\d+\s*ans\s*$',
        re.IGNORECASE,
    )

    # Group items by film block
    # A film block starts with a title line (xc < 170) that has a duration
    # Showtimes are on lines with xc >= 170
    films = []
    current_film = None
    title_lines = []
    title_lines_has_marker = False   # T39: any title_lines entry has a section marker suffix
    current_block_showtimes = []

    def _flush_title_as_new_film():
        """T39: flush title_lines + pending showtimes as a new film (no duration)."""
        nonlocal title_lines, title_lines_has_marker, current_block_showtimes
        if not title_lines:
            return
        new_film = {
            "title": re.sub(r'\s+', ' ', ' '.join(title_lines)).strip(),
            "duration": "",
            "showtimes": {i: [] for i in range(7)},
        }
        films.append(new_film)
        if current_block_showtimes:
            for s_col, s_times in current_block_showtimes:
                if s_col in new_film["showtimes"]:
                    for t in s_times:
                        if t not in new_film["showtimes"][s_col]:
                            new_film["showtimes"][s_col].append(t)
            current_block_showtimes = []
        title_lines = []
        title_lines_has_marker = False

    for y, xc, text in content_items:
        is_title = xc < 170

        if is_title:
            has_dur = bool(re.search(r'\d+[Hh]\d+', text))

            if has_dur:
                # T39: a section marker in title_lines means a separate festival film —
                # flush it before creating this duration-based film.
                if title_lines and title_lines_has_marker:
                    _flush_title_as_new_film()

                # Parse this title line
                dur_m = re.search(r'(\d+)[Hh](\d+)', text)
                dur = f"{dur_m.group(1)}h{dur_m.group(2)}" if dur_m else ""
                title_part = re.sub(r'\s*\d+[Hh]\d+.*$', '', text).strip()
                full_title = re.sub(r'\s+', ' ', ' '.join(title_lines + [title_part])).strip()
                title_lines = []
                title_lines_has_marker = False

                current_film = {
                    "title": full_title,
                    "duration": dur,
                    "showtimes": {i: [] for i in range(7)},
                }
                films.append(current_film)

                # Assign any pending showtimes (from multi-line title buffer) to this new film
                if current_block_showtimes:
                    for s_col, s_times in current_block_showtimes:
                        if s_col in current_film["showtimes"]:
                            for t in s_times:
                                if t not in current_film["showtimes"][s_col]:
                                    current_film["showtimes"][s_col].append(t)
                    current_block_showtimes = []

                # Extract inline showtimes on title line — some films have compact layout
                # where showtime text is on the same line as the title (e.g., "VIVALDI ET MOI 1H50 18H00 VO")
                after_dur = re.sub(r'.*?\d+[Hh]\d+\s*', '', text, count=1).strip()
                if after_dur:
                    tn = after_dur.replace('h', 'H')
                    for h, m in re.findall(r'(\d+)H(\d+)', tn):
                        ts = f"{h}:{m}"
                        if ts not in current_film["showtimes"][0]:
                            current_film["showtimes"][0].append(ts)
            else:
                # TITLE line without duration
                if _SECTION_MARKER_RE.match(text):
                    # T39: section marker like "Summer film festival" / "Little film festival"
                    # is suffix metadata — append to the immediately preceding film/title.
                    if current_film is not None:
                        current_film['title'] = re.sub(
                            r'\s+', ' ',
                            (current_film['title'] + ' ' + text).strip(),
                        )
                    elif title_lines:
                        title_lines[-1] = title_lines[-1] + ' ' + text.strip()
                        title_lines_has_marker = True
                    # else: orphan section marker — discard
                elif _PREFIX_METADATA_RE.match(text):
                    # T39: standalone "int. —12 ans" is prefix metadata — keep with the
                    # next real title so it becomes part of that film's title.
                    title_lines.append(text.strip())
                    current_film = None
                else:
                    # Multi-line title continuation or a new film title without duration.
                    # T39: if a section marker is present in the buffered title_lines, the
                    # buffered title is a complete festival film — flush it before starting a new one.
                    if title_lines and title_lines_has_marker:
                        _flush_title_as_new_film()
                    if current_film:
                        # Flush any pending showtimes to current_film first
                        if current_block_showtimes:
                            for s_col, s_times in current_block_showtimes:
                                if s_col in current_film['showtimes']:
                                    for t in s_times:
                                        if t not in current_film['showtimes'][s_col]:
                                            current_film['showtimes'][s_col].append(t)
                            current_block_showtimes = []
                        # Now set current_film to None so future showtimes buffer
                        current_film = None
                    title_lines.append(text.strip())
        else:
            # Showtime text
            ci = col_for_x(xc)
            if ci is None:
                continue
            tn = text.replace('h', 'H')
            times_found = re.findall(r'(\d+)H(\d+)', tn)
            if not times_found:
                continue

            ts_list = [f"{h}:{m}" for h, m in times_found]

            if current_film:
                # Assign directly to current film
                for ts in ts_list:
                    if ts not in current_film["showtimes"][ci]:
                        current_film["showtimes"][ci].append(ts)
            else:
                # Pending showtimes for a film that hasn't been created yet
                # (multi-line title situation — title_lines accumulated, but no has_dur line yet)
                current_block_showtimes.append((ci, ts_list))

    # T39: end-of-content flush — any pending title_lines becomes a new film (no duration)
    if title_lines:
        _flush_title_as_new_film()

    # Flush last film's pending showtimes
    if current_film and current_block_showtimes:
        for s_col, s_times in current_block_showtimes:
            if s_col in current_film["showtimes"]:
                for t in s_times:
                    if t not in current_film["showtimes"][s_col]:
                        current_film["showtimes"][s_col].append(t)

    print(f"Films found: {len(films)}")
    for f in films:
        total = sum(len(v) for v in f["showtimes"].values())
        print(f"  {f['title']} ({f['duration']}) - {total} showtimes")
    return films, day_dates, start_d.isoformat(), (start_d + timedelta(days=6)).isoformat()

def build_events(films, day_dates, start_date, end_date):
    events = []
    for film in films:
        title = re.sub(r'\s+', ' ', film["title"]).strip()
        poster, desc = lookup(title)
        # T22: if AlloCine lookup didn't find a poster, try TMDB.
        if not poster:
            poster = _enrich_with_tmdb(title)
        showtimes = {}
        for ci, times in film["showtimes"].items():
            if ci < 7 and times:
                ds = day_dates.get(ci)
                if ds:
                    showtimes[ds] = sorted(set(t.strip() for t in times))
        if not showtimes:
            print(f"  WARNING: {title} has no showtimes, skipping")
            continue
        ad = sorted(showtimes.keys())
        events.append({
            "id": f"vox-{slugify(title)}",
            "title": title,
            "description": desc,
            "category": "Cinema",
            "commune": "Chamonix",
            "source_id": "vox_pdf",
            "source_url": "https://www.allocine.fr/seance/salle_gen_csalle=P1406.html",
            "image_url": poster,
            "venue": "Le Vox",
            "address": "22 Cour du Bartavel, 74400 Chamonix-Mont-Blanc",
            "language": "Francais",
            "duration": film["duration"],
            "start_date": ad[0],
            "end_date": ad[-1],
            "showtimes": showtimes,
            "status": "published",
            "confidence": VOX_CONFIDENCE,  # T14: placeholder, recomputed below
        })
    # T14: full confidence score for each cinema event
    for ev in events:
        ev["confidence"] = compute_confidence("vox_pdf", ev)
    return events


def _enrich_with_tmdb(title: str) -> str:
    """T22: TMDB poster lookup as a fallback after AlloCine.

    Returns the poster URL or empty string on miss / no-key / error.
    Cached via scripts.tmdb.lookup_poster so repeated runs are instant.
    """
    if not _tmdb:
        return ""
    try:
        year = _tmdb.lookup_title_year(title)
        url = _tmdb.lookup_poster(title, year=year)
        if url:
            print(f"  [tmdb] poster for {title!r}: {url}")
            return url
    except Exception as exc:  # never break the scraper on TMDB issues
        print(f"  [tmdb] error for {title!r}: {exc}", file=sys.stderr)
    return ""

def main():
    os.makedirs(DATA_DIR, exist_ok=True)
    print("Downloading PDF...")
    pdf_path = download_pdf()
    print(f"PDF saved to {pdf_path}")
    print("Parsing PDF...")
    films, day_dates, sd, ed = parse_pdf(pdf_path)
    if not films:
        print("No films found.", file=sys.stderr)
        return
    print("Building events...")
    events = build_events(films, day_dates, sd, ed)
    print(f"Writing {len(events)} cinema events to SQLite...")
    # T10: SQLite canonical. JSON is build artefact only.
    get_storage().upsert_cinema(events)
    print("Done!")
    for ev in events:
        total = sum(len(v) for v in ev.get("showtimes", {}).values())
        hp = "OK" if ev.get("image_url") else "XX"
        print(f"  {hp} {ev['title']} - {total} showtimes")

if __name__ == "__main__":
    main()
