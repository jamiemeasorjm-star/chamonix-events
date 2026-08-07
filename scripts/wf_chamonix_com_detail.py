#!/usr/bin/env python3
"""Staged wf-based drop-in for chamonix_com_detail.main().

Migration slice 2. This is a NON-DESTRUCTIVE staging module: it mirrors the
data flow of `chamonix_com_detail.main()` exactly (so data contracts match the
live scrapers), but replaces the weak plain-httpx detail extraction with the
wf toolkit path (`scripts.wf_chamonix_com.extract_event`) that fixes the old
empty-description bug on JS-heavy chamonix.com pages.

It is deliberately NOT wired into any pipeline. Run it with --dry-run to
inspect; the operator runs it (in write mode) after the parity gate proves
wf >= old coverage.

Flow (mirrors chamonix_com_detail.main()):
  a. load existing chamonix_com events (review_items fallback if empty)
  b. discover event URLs from the chamonix.com sitemap (reuse discovery fns)
  c. extract each via wf extract_event
  d. enrich loaded events via enrich_events_from_details
  e. write back via storage.upsert_events_ungated unless --dry-run

Run (web-foundation venv, wf deps live only there):
    export PYTHONPATH=/docker/hermes-agent-2bpx/data/chamonix-events
    /docker/hermes-agent-2bpx/data/web-foundation/.venv/bin/python -m \\
        scripts.wf_chamonix_com_detail --dry-run --limit 3
"""

from __future__ import annotations

import argparse
import sys

import httpx

from scripts.chamonix_com_detail import (
    USER_AGENT,
    discover_event_urls,
    enrich_events_from_details,
)
from scripts import wf_chamonix_com as wf

SOURCE_ID = "chamonix_com"
MIN_DESCRIPTION_LEN = wf.MIN_DESCRIPTION_LEN


def _coverage_summary(events: list[dict], min_len: int = MIN_DESCRIPTION_LEN) -> tuple[int, int]:
    """Pure helper: (count_with_real_description, total) for a list of events.

    A "real" description is a non-empty string at least `min_len` chars long.
    """
    total = len(events)
    with_desc = sum(
        1 for ev in events if len((ev.get("description") or "").strip()) >= min_len
    )
    return with_desc, total


def _load_existing(storage) -> list[dict]:
    """Load existing chamonix_com events, with the review_items fallback."""
    import json

    existing = storage.get_events(source_id=SOURCE_ID)
    if existing is None:
        existing = []
    print(f"Existing chamonix_com events in events table: {len(existing)}")

    if not existing:
        cur = storage.conn.execute(
            "SELECT event_snapshot FROM review_items WHERE source_id=?",
            (SOURCE_ID,),
        )
        rows = cur.fetchall()
        if rows:
            existing = [json.loads(r[0]) for r in rows]
            for ev in existing:
                ev["status"] = "pending_review"
            print(f"Loaded {len(existing)} chamonix_com events from review queue")
        else:
            print("No chamonix_com events to enrich -- run chamonix_com scraper first")
            return []
    return existing


def _discover_urls(limit: int | None) -> list[str]:
    headers = {"User-Agent": USER_AGENT}
    with httpx.Client(headers=headers, verify=True) as client:
        print("Discovering event URLs from sitemap...")
        event_urls = discover_event_urls(client)
        print(f"Found {len(event_urls)} event URLs")
        if limit:
            event_urls = event_urls[:limit]
            print(f"Applying --limit {limit}: using {len(event_urls)}")
        return event_urls


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="wf-based chamonix.com detail drop-in")
    ap.add_argument("--dry-run", action="store_true",
                    help="print what would change; do NOT write to the DB")
    ap.add_argument("--limit", type=int, default=None,
                    help="only process the first N discovered URLs")
    ap.add_argument("--no-browser", action="store_true",
                    help="disable the JS-render BrowserSession fallback")
    args = ap.parse_args(argv)

    from scripts.storage import get_storage

    # sources.py needs PyYAML, which is not installed in the web-foundation venv.
    # The active-source check is a nicety; degrade gracefully so the staged
    # drop-in still runs under the required venv (write mode stays behind
    # --dry-run).
    source_active = True
    try:
        from scripts.sources import get_source
        source = get_source(SOURCE_ID)
        source_active = bool(source and source.active)
    except Exception:  # noqa: BLE001 - PyYAML missing etc.
        source_active = True

    if not source_active:
        print(f"{SOURCE_ID} source is inactive -- skipping detail enrichment")
        return 0

    storage = get_storage()

    if args.dry_run:
        # Corrupted / foreign events in the events table should not block the
        # operator from a safe preview; fall back gracefully.
        pass

    existing = _load_existing(storage)
    if not existing:
        return 0

    before, total = _coverage_summary(existing)
    print(f"desc-coverage before: {before}/{total} events have a real description")

    event_urls = _discover_urls(args.limit)
    if not event_urls:
        print("No event URLs found -- nothing to do")
        return 0

    use_browser = not args.no_browser
    details: list[dict] = []
    for i, url in enumerate(event_urls, 1):
        slug = url.rstrip("/").split("/")[-1][:50]
        print(f"  [{i}/{len(event_urls)}] {slug}...", end=" ", flush=True)
        try:
            ev = wf.extract_event(url, use_browser_fallback=use_browser)
        except Exception as e:  # noqa: BLE001 - one URL shouldn't kill the run
            print(f"error: {e}")
            continue
        desc_len = len(ev.get("description", ""))
        details.append(ev)
        flag = "OK " if desc_len >= MIN_DESCRIPTION_LEN else "FAIL"
        browser = " [browser]" if ev.get("used_browser_fallback") else ""
        print(f"{flag} title={ev.get('title','?')[:40]} desc={desc_len}c{browser}")

    print(f"Extracted {len(details)}/{len(event_urls)} detail pages via wf")

    if args.dry_run:
        for d in details[:5]:
            print(f"  {d.get('title','?')}")
            print(f"    desc: {d.get('description','')[:100]}")
            print(f"    image: {'Y' if d.get('image_url') else 'N'}")
            print(f"    dates: {d.get('start_date','?')} -> {d.get('end_date','?')}")
            print(f"    commune: {d.get('commune','?')}")
        after, _ = _coverage_summary(existing + [x for x in details if x])
        print(f"\n[dry-run] desc-coverage after preview: {after}/{total} would have a real description")
        print(f"[dry-run] {len(details)} detail(s) extracted; NO DB write performed.")
        return 0

    enriched, count = enrich_events_from_details(details, existing)
    print(f"Enriched: {count} events updated")

    if count > 0:
        storage.upsert_events_ungated(SOURCE_ID, enriched)
        print(f"Written {len(enriched)} events to SQLite")
    else:
        print("No events to update")

    after, _ = _coverage_summary(enriched)
    print(f"desc-coverage after: {after}/{len(enriched)} events have a real description")
    return 0


if __name__ == "__main__":
    sys.exit(main())
