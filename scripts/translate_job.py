#!/usr/bin/env python3
"""T25: Batch translation of FR → EN content fields via OpenRouter.

Uses the DeepSeek v4 Flash model (cheapest available on OpenRouter) to
translate canonical FR event/venue content to EN. Writes results back to
SQLite as title_en, description_en, venue_name_en, name_en.

Idempotent: only translates fields that are currently empty. Can be re-run
safely as new events trickle in.

Usage:
    python -m scripts.translate_job              # translate all FR→EN
    python -m scripts.translate_job --dry-run    # show what would be done
"""

import json, os, re, sys, time, uuid
from datetime import datetime, timezone
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
OPENROUTER_MODEL = "openai/gpt-4o-mini"
OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
API_KEY = os.environ.get("OPENROUTER_API_KEY") or ""
if not API_KEY:
    env_paths = [
        "/docker/hermes-agent-2bpx/data/.env",
        os.path.join(os.path.dirname(os.path.dirname(__file__)), ".env"),
    ]
    for ep in env_paths:
        if os.path.exists(ep):
            for line in open(ep):
                if line.startswith("OPENROUTER_API_KEY="):
                    API_KEY = line.strip().split("=", 1)[1]
                    break
            if API_KEY:
                break

RATE_LIMIT_DELAY = 0.3
MAX_RETRIES = 3
RETRY_DELAY = 2.0
BATCH_SIZE = 10  # T39: items per batch — 10× fewer API calls

SYSTEM_PROMPT = (
    "You are a professional French-to-English translator for a Chamonix events website. "
    "Translate the given French text to natural, idiomatic English. "
    "Keep place names (Chamonix, Mont-Blanc, Les Houches, Argentiere, etc.) unchanged. "
    "Keep event names and proper nouns unchanged. "
    "Return ONLY the translated text, nothing else."
)


def translate_fr_to_en(text: str) -> str:
    """Translate a single French text to English via OpenRouter."""
    if not text or not text.strip():
        return text or ""
    if len(text) > 2000:
        text = text[:2000]
    for attempt in range(MAX_RETRIES):
        try:
            body = json.dumps({
                "model": OPENROUTER_MODEL,
                "messages": [
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": f"Translate this French text to English:\n\n{text}"},
                ],
                "max_tokens": max(100, min(400, len(text) * 2)),
                "temperature": 0.1,
            }).encode()
            req = Request(OPENROUTER_URL, data=body, headers={
                "Authorization": f"Bearer {API_KEY}",
                "Content-Type": "application/json",
                "HTTP-Referer": "https://chamonix-events.local",
            })
            resp = urlopen(req, timeout=30)
            data = json.loads(resp.read())
            msg = data.get("choices", [{}])[0].get("message", {})
            content = msg.get("content") if isinstance(msg, dict) else None
            if not content or not content.strip():
                return text
            result = content.strip()
            result = result.strip('"').strip("'")
            return result
        except (HTTPError, URLError, json.JSONDecodeError, KeyError, IndexError, TypeError, AttributeError) as e:
            if attempt < MAX_RETRIES - 1:
                time.sleep(RETRY_DELAY * (attempt + 1))
            else:
                print(f"  [warn] translation failed: {e}", file=sys.stderr)
                return text
    return text


def batch_translate(texts: list[str], label: str = "") -> list[str]:
    """Translate a list of texts via batched API calls (BATCH_SIZE items per call).

    Returns list of translated texts in the same order as input.
    For short texts (titles, venue names) this is ~10× faster than one-per-call.
    """
    results: list[str] = []
    total = len(texts)
    if total == 0:
        return results
    batch_size = BATCH_SIZE

    # Build batches: list of (batch_idx, seq_in_batch, text)
    batches: list[list[tuple[int, int, str]]] = []
    for i, text in enumerate(texts):
        if not text or not text.strip():
            continue
        batch_idx = i // batch_size
        seq = i % batch_size
        while len(batches) <= batch_idx:
            batches.append([])
        batches[batch_idx].append((i, seq, text))

    # Placeholder for results
    placeholder = {i: text for i, text in enumerate(texts)}

    for batch in batches:
        # Build batch prompt: numbered items
        batch_lines = "\n".join(f"[{seq}] {text}" for _, seq, text in batch)
        prompt = (
            f"Translate the following {len(batch)} French texts to English.\n"
            f"Return ONLY a JSON object with keys like \"0\", \"1\", etc. mapping to the translations.\n"
            f"Keep place names (Chamonix, Mont-Blanc, Les Houches, etc.) and proper nouns unchanged.\n\n"
            f"{batch_lines}"
        )

        print(f"  [{batch[0][0]+1}-{batch[-1][0]+1}/{total}] {label} ({len(batch)} items)...",
              end=" ", flush=True)

        translated = _call_llm_batch(prompt, len(batch))
        if translated and len(translated) == len(batch):
            for (orig_idx, _, _), trans in zip(batch, translated):
                if trans:
                    placeholder[orig_idx] = trans
                    print(f"ok", end=" ", flush=True)
                else:
                    print(f"unchanged", end=" ", flush=True)
            print()
        else:
            # Fallback: translate each item individually within this batch
            print(f"batch failed ({len(translated) if translated else 0}/{len(batch)}), falling back individually")
            for orig_idx, _, text in batch:
                t = _call_llm_single(text)
                print(f"  [{orig_idx+1}/{total}] {label} ({len(text)}c)...",
                      "ok" if t != text else "unchanged")
                if t:
                    placeholder[orig_idx] = t
                time.sleep(RATE_LIMIT_DELAY)

    return [placeholder[i] for i in range(len(texts))]


def _call_llm_batch(prompt: str, expected_count: int) -> list[str] | None:
    """Send a batched translation prompt and parse the JSON response."""
    for attempt in range(MAX_RETRIES):
        try:
            body = json.dumps({
                "model": OPENROUTER_MODEL,
                "messages": [
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": prompt},
                ],
                "max_tokens": 400 * expected_count,
                "temperature": 0.1,
                "response_format": {"type": "json_object"},
            }).encode()
            req = Request(OPENROUTER_URL, data=body, headers={
                "Authorization": f"Bearer {API_KEY}",
                "Content-Type": "application/json",
                "HTTP-Referer": "https://chamonix-events.local",
            })
            resp = urlopen(req, timeout=60)
            data = json.loads(resp.read())
            msg = data.get("choices", [{}])[0].get("message", {})
            content = msg.get("content") if isinstance(msg, dict) else None
            if not content:
                continue
            # Parse the JSON response
            parsed = json.loads(content)
            # Map keys 0..N-1 to values
            results = []
            for i in range(expected_count):
                val = parsed.get(str(i)) or parsed.get(i)
                if val and isinstance(val, str):
                    results.append(val.strip().strip("\"'"))
                else:
                    results.append("")
            return results
        except (HTTPError, URLError, json.JSONDecodeError, KeyError, IndexError, TypeError, AttributeError) as e:
            if attempt < MAX_RETRIES - 1:
                time.sleep(RETRY_DELAY * (attempt + 1))
            else:
                print(f"  [warn] batch translation failed: {e}", file=sys.stderr)
                return None
    return None


def _call_llm_single(text: str) -> str:
    """Translate a single text (fallback path)."""
    if not text or not text.strip():
        return text or ""
    if len(text) > 2000:
        text = text[:2000]
    for attempt in range(MAX_RETRIES):
        try:
            body = json.dumps({
                "model": OPENROUTER_MODEL,
                "messages": [
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": f"Translate this French text to English:\n\n{text}"},
                ],
                "max_tokens": max(100, min(400, len(text) * 2)),
                "temperature": 0.1,
            }).encode()
            req = Request(OPENROUTER_URL, data=body, headers={
                "Authorization": f"Bearer {API_KEY}",
                "Content-Type": "application/json",
                "HTTP-Referer": "https://chamonix-events.local",
            })
            resp = urlopen(req, timeout=30)
            data = json.loads(resp.read())
            msg = data.get("choices", [{}])[0].get("message", {})
            content = msg.get("content") if isinstance(msg, dict) else None
            if not content or not content.strip():
                return text
            result = content.strip()
            result = result.strip('"').strip("'")
            return result
        except (HTTPError, URLError, json.JSONDecodeError, KeyError, IndexError, TypeError, AttributeError) as e:
            if attempt < MAX_RETRIES - 1:
                time.sleep(RETRY_DELAY * (attempt + 1))
            else:
                print(f"  [warn] single translation failed: {e}", file=sys.stderr)
                return text
    return text


def _translate_descriptions_per_item(items, dry_run=False):
    """Translate long descriptions ONE AT A TIME (T55).

    Descriptions were previously batch-translated 10-at-a-time inside a single
    JSON response. The model sometimes returned valid JSON with misaligned /
    cross-contaminated values, which the code trusted by key order and wrote to
    the WRONG event (e.g. a falconry card got an ice-hockey description).
    Translating long text per-item makes that class of error impossible.
    Titles/venue names (short) stay batched for speed.
    """
    results: list[str] = []
    total = len(items)
    for idx, (e, _t, desc_fr, _v) in enumerate(items):
        if not desc_fr or not desc_fr.strip():
            results.append(desc_fr or "")
            continue
        t = _call_llm_single(desc_fr)
        print(f"  [{idx+1}/{total}] description ({len(desc_fr)}c)...",
              "ok" if t and t != desc_fr else "unchanged", flush=True)
        results.append(t if t else desc_fr)
        time.sleep(RATE_LIMIT_DELAY)
    return results


def main():
    dry_run = "--dry-run" in sys.argv
    if not API_KEY:
        print("ERROR: OPENROUTER_API_KEY not found")
        return 1

    print(f"Using model: {OPENROUTER_MODEL}")
    if dry_run:
        print("DRY RUN — no changes will be written")

    from scripts.storage import get_storage
    storage = get_storage()
    now = datetime.now(timezone.utc).isoformat()
    stats = {"events": 0, "venues": 0, "cinema": 0}

    # ---- Events ----
    events = storage.get_events()
    to_translate = []
    for e in events:
        if e.get("title_en") and e.get("description_en"):
            continue
        title_fr = e.get("title") or ""
        desc_fr = e.get("description") or ""
        venue_fr = e.get("venue_name") or ""
        if not title_fr and not desc_fr and not venue_fr:
            continue
        to_translate.append((e, title_fr, desc_fr, venue_fr))

    if to_translate:
        print(f"\nTranslating {len(to_translate)} events...")
        en_titles = batch_translate([t[1] for t in to_translate], "title")

        # Save titles immediately (progressive save)
        if not dry_run and en_titles:
            with storage.conn:
                for (e, _, _, _), title_en in zip(to_translate, en_titles):
                    if title_en and title_en != e.get("title", ""):
                        eid = e["id"]
                        storage.conn.execute(
                            "UPDATE events SET title_en = ?, updated_at = ? WHERE id = ?",
                            [title_en, now, eid],
                        )
            print(f"  Saved {sum(1 for t in en_titles if t)} title translations")

        en_descs = _translate_descriptions_per_item(to_translate, dry_run)

        # Save descriptions immediately
        if not dry_run and en_descs:
            with storage.conn:
                for (e, _, _, _), desc_en in zip(to_translate, en_descs):
                    if desc_en and desc_en != e.get("description", ""):
                        eid = e["id"]
                        storage.conn.execute(
                            "UPDATE events SET description_en = ?, updated_at = ? WHERE id = ?",
                            [desc_en, now, eid],
                        )
            print(f"  Saved {sum(1 for d in en_descs if d)} description translations")

        en_venues = batch_translate([t[3] for t in to_translate], "venue_name")

        # Save venue names immediately
        if not dry_run and en_venues:
            with storage.conn:
                for (e, _, _, _), venue_en in zip(to_translate, en_venues):
                    if venue_en and venue_en != e.get("venue_name", ""):
                        eid = e["id"]
                        storage.conn.execute(
                            "UPDATE events SET venue_name_en = ?, updated_at = ? WHERE id = ?",
                            [venue_en, now, eid],
                        )
            print(f"  Saved {sum(1 for v in en_venues if v)} venue name translations")

        stats["events"] = len(to_translate)
    else:
        print("\nNo events need translation")

    # ---- Venues ----
    venues = storage.get_venues()
    to_translate_v = [(v, v.get("name") or "") for v in venues if not v.get("name_en") and v.get("name")]
    if to_translate_v:
        print(f"\nTranslating {len(to_translate_v)} venues...")
        en_names = batch_translate([t[1] for t in to_translate_v], "venue_name")
        if not dry_run:
            with storage.conn:
                for (v, _), name_en in zip(to_translate_v, en_names):
                    if name_en:
                        storage.conn.execute(
                            "UPDATE venues SET name_en = ? WHERE id = ?",
                            [name_en, v["id"]],
                        )
            stats["venues"] = len(to_translate_v)
            print(f"  Written {len(to_translate_v)} venues to SQLite")
    else:
        print("\nNo venues need translation")

    # ---- Cinema ----
    cinema = storage.get_cinema()
    to_translate_c = [(c, c.get("title") or "") for c in cinema if not c.get("title_en") and c.get("title")]
    if to_translate_c:
        print(f"\nTranslating {len(to_translate_c)} cinema events...")
        en_titles = batch_translate([t[1] for t in to_translate_c], "cinema_title")
        if not dry_run:
            with storage.conn:
                for (c, _), title_en in zip(to_translate_c, en_titles):
                    if title_en:
                        storage.conn.execute(
                            "UPDATE cinema_events SET title_en = ? WHERE id = ?",
                            [title_en, c["id"]],
                        )
            stats["cinema"] = len(to_translate_c)
            print(f"  Written {len(to_translate_c)} cinema events to SQLite")
    else:
        print("\nNo cinema events need translation")

    if dry_run:
        print(f"\nDRY RUN: {len(to_translate)} events, {len(to_translate_v)} venues, {len(to_translate_c)} cinema to translate")
    else:
        print(f"\nDone: {stats['events']} events, {stats['venues']} venues, {stats['cinema']} cinema updated")
    return 0


if __name__ == "__main__":
    sys.exit(main())