#!/usr/bin/env python3
"""wf-path parity verifier (migration slice 1).

PROVES the wf extraction path fixes the old chamonix_com empty-description bug:
the legacy httpx-only chamonix_com_detail.py returned empty descriptions for
chamonix.com event pages (JS-heavy / Next.js). This verifier runs the wf
toolkit path against a sample of known event-detail URLs and reports, per URL,
whether a real description came back.

Read-only: fetches the web + prints a summary. No DB/storage writes.

Run (must use the web-foundation venv):
    export PYTHONPATH=/docker/hermes-agent-2bpx/data/chamonix-events
    /docker/hermes-agent-2bpx/data/web-foundation/.venv/bin/python -m \\
        scripts.check_wf_parity [--min-len 120] [--browser]
"""

from __future__ import annotations

import argparse
import sys

from scripts import wf_chamonix_com as wf  # avoid clashing module name

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


def check(urls: list[str], min_len: int, use_browser: bool) -> list[dict]:
    results = []
    for url in urls:
        try:
            ev = wf.extract_event(url, use_browser_fallback=use_browser)
            desc = ev.get("description", "")
            results.append({
                "url": url,
                "title": ev.get("title", ""),
                "desc_len": len(desc),
                "ok": len(desc) >= min_len,
                "browser": bool(ev.get("used_browser_fallback")),
                "status": "ok",
            })
        except Exception as e:  # noqa: BLE001 - one bad URL shouldn't kill the run
            results.append({
                "url": url,
                "title": "",
                "desc_len": 0,
                "ok": False,
                "browser": False,
                "status": f"error: {e}",
            })
    return results


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="wf chamonix.com description parity verifier")
    ap.add_argument("--min-len", type=int, default=wf.MIN_DESCRIPTION_LEN,
                    help="minimum description length to count as success")
    ap.add_argument("--browser", action="store_true",
                    help="also try the JS-render BrowserSession fallback")
    ap.add_argument("--urls", nargs="*", default=SAMPLE_URLS,
                    help="override sample URLs")
    args = ap.parse_args(argv)

    results = check(args.urls, args.min_len, args.browser)

    slug_w = max((len(u.rsplit("/", 1)[-1]) for u in args.urls), default=20)
    slug_w = min(slug_w, 55)
    print(f"{'slug':{slug_w}} {'desc_len':>8} {'ok':>4}  title")
    print("-" * (slug_w + 40))
    for r in results:
        slug = r["url"].rsplit("/", 1)[-1][:slug_w]
        flag = "YES" if r["ok"] else "NO "
        browser = " [browser]" if r["browser"] else ""
        print(f"{slug:{slug_w}} {r['desc_len']:>8} {flag:>4}  {r['title'][:45]}{browser}")

    good = sum(1 for r in results if r["ok"])
    total = len(results)
    lens = [r["desc_len"] for r in results if r["status"] == "ok"]
    avg = sum(lens) / len(lens) if lens else 0
    fails = [r["url"] for r in results if not r["ok"]]

    print()
    print(f"Summary: {good}/{total} URLs yield a real description "
          f"(>= {args.min_len} chars) via the wf path.")
    print(f"Average description length: {avg:.0f} chars "
          f"(old httpx path returned ~0 for most chamonix.com pages).")
    if fails:
        print("Still failing:")
        for u in fails:
            print(f"  - {u}")
    overall = "PASS" if good == total else "FAIL"
    print(f"Overall: {overall}")
    return 0 if good == total else 1


if __name__ == "__main__":
    sys.exit(main())
