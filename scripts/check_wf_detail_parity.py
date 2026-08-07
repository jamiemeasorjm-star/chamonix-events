#!/usr/bin/env python3
"""Read-only parity gate: OLD httpx detail extraction vs NEW wf extraction.

Migration slice 2. Compares, per sampled chamonix.com event-detail URL:
    - OLD path: `chamonix_com_detail.extract_detail` (plain httpx) -> desc_len_old
    - NEW path: `wf_chamonix_com.extract_event` (fast-path + browser fallback)
                -> desc_len_wf
and reports coverage for each, then gates on REGRESSION: if any URL where the
OLD path had a real description comes back with a notably SHORTER wf
description (wf_len < old_len * --regress-ratio), the gate FAILS (exit 1).

This is the operator's signal that the swap is safe: it must PASS before the
drop-in is run in write mode.

Read-only: only fetches the web + prints. No DB/storage writes.

Run (web-foundation venv):
    export PYTHONPATH=/docker/hermes-agent-2bpx/data/chamonix-events
    /docker/hermes-agent-2bpx/data/web-foundation/.venv/bin/python -m \\
        scripts.check_wf_detail_parity [--regress-ratio 0.5]
"""

from __future__ import annotations

import argparse
import sys

import httpx

from scripts import wf_chamonix_com as wf
from scripts.chamonix_com_detail import USER_AGENT, extract_detail
from scripts.chamonix_com_detail import get_event_urls_from_sitemap, get_sitemap_pages

BASE = "https://www.chamonix.com/agenda/evenements-et-manifestations/"

SAMPLE_SLUGS = [
    "fete-des-guides-2026",
    "festival-d-orgue-de-la-vallee-de-chamonix-31eme-edition",
    "festival-la-nuit-des-ours-2026",
    "utmb-mont-blanc-r",
    "chamonix-photo-festival",
    "marche-de-chamonix",
    "concert-avec-dub-inc",
    "marche-des-houches",
]

SAMPLE_URLS = [BASE + s for s in SAMPLE_SLUGS]


def discover_extra_urls(max_add: int = 4) -> list[str]:
    """Best-effort: pull a few more event-detail URLs from the sitemap.

    Never raises; returns [] if the sitemap is unreachable. Dedupes against
    the known sample slugs and returns full URLs.
    """
    known = set(SAMPLE_URLS)
    extra: list[str] = []
    try:
        headers = {"User-Agent": USER_AGENT}
        with httpx.Client(headers=headers, verify=True) as client:
            pages = get_sitemap_pages(client)
            for sp in pages:
                for u in get_event_urls_from_sitemap(client, sp):
                    if u not in known and u not in extra:
                        extra.append(u)
                    if len(extra) >= max_add:
                        return extra
    except Exception as e:  # noqa: BLE001
        print(f"  [warn] could not extend sample from sitemap: {e}")
    return extra


def run_pair(url: str, use_browser: bool = True) -> dict:
    """Run both OLD (httpx) and NEW (wf) extraction on one URL; return metrics."""
    row: dict = {"url": url, "desc_len_old": 0, "desc_len_wf": 0,
                 "old_title": "", "wf_title": "", "status": "ok"}
    try:
        headers = {"User-Agent": USER_AGENT}
        with httpx.Client(headers=headers, verify=True) as client:
            old = extract_detail(client, url)
        row["desc_len_old"] = len(old.get("description", "") or "")
        row["old_title"] = old.get("title", "")
    except Exception as e:  # noqa: BLE001
        row["status"] = f"old-error: {e}"
    try:
        ev = wf.extract_event(url, use_browser_fallback=use_browser)
        row["desc_len_wf"] = len(ev.get("description", "") or "")
        row["wf_title"] = ev.get("title", "")
    except Exception as e:  # noqa: BLE001
        row["status"] = f"{row['status']}; wf-error: {e}"
    row["slug"] = url.rstrip("/").split("/")[-1]
    return row


def is_regression(row: dict, ratio: float) -> bool:
    """True when the OLD path had a real description the wf path notably lost."""
    old = row["desc_len_old"]
    wf_len = row["desc_len_wf"]
    if old <= 0:
        # No old description to regress against: wf merely gaining coverage is good.
        return False
    return wf_len < old * ratio


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="OLD-vs-wf chamonix.com detail parity gate")
    ap.add_argument("--regress-ratio", type=float, default=0.5,
                    help="wf desc shorter than this fraction of old desc counts as regression")
    ap.add_argument("--no-browser", action="store_true",
                    help="disable wf JS-render fallback (makes wf weaker)")
    ap.add_argument("--urls", nargs="*", default=None,
                    help="override sample URLs")
    args = ap.parse_args(argv)

    urls = list(args.urls) if args.urls else SAMPLE_URLS
    if not args.urls:
        urls.extend(discover_extra_urls())

    use_browser = not args.no_browser
    rows = [run_pair(u, use_browser=use_browser) for u in urls]

    slug_w = min(max((len(r["slug"]) for r in rows), default=20), 50)
    print(f"{'slug':{slug_w}} {'old_len':>8} {'wf_len':>8} {'regress':>8}  title(wf)")
    print("-" * (slug_w + 48))
    for r in rows:
        flag = "YES" if is_regression(r, args.regress_ratio) else "no"
        title = r["wf_title"][:40] or r["old_title"][:40]
        print(f"{r['slug']:{slug_w}} {r['desc_len_old']:>8} {r['desc_len_wf']:>8} "
              f"{flag:>8}  {title}")

    regressions = [r for r in rows if is_regression(r, args.regress_ratio)]
    ok_parity = len(rows) - len(regressions)

    print()
    print(f"Summary: {ok_parity}/{len(rows)} URLs have wf desc >= old desc "
          f"(within {args.regress_ratio:.0%} of old coverage).")
    for r in regressions:
        print(f"  REGRESSION: {r['slug']} old={r['desc_len_old']}c "
              f"wf={r['desc_len_wf']}c ({r['status']})")

    if regressions:
        print("PARITY: FAIL")
        return 1
    print("PARITY: PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
