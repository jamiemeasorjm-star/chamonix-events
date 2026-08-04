#!/usr/bin/env python3
"""T55: Render a concise human-readable report of events auto-filtered by
publish_rules (the 'review feed'). Reads data/drop_report.jsonl (written by
storage.upsert_events), dedupes, groups by reason, and prints a Telegram-ready
message. By default it CLEARS the log so each run only reports NEW drops.

Usage:
    python -m scripts.drop_report             # print report + clear log
    python -m scripts.drop_report --keep     # print report, keep the log
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def main():
    keep = "--keep" in sys.argv
    path = Path(__file__).resolve().parent.parent / "data" / "drop_report.jsonl"

    drops = []
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                drops.append(json.loads(line))
            except json.JSONDecodeError:
                pass

    if not drops:
        return 0  # silent on clean runs — only deliver when something was held back

    # Dedup by (title, date, venue) keeping first.
    seen = set()
    uniq = []
    for d in drops:
        key = (d.get("title", ""), d.get("date", ""), d.get("venue", ""))
        if key in seen:
            continue
        seen.add(key)
        uniq.append(d)

    # Group by reason category.
    def cat(r):
        if r == "duplicate":
            return "duplicate"
        if r == "low_confidence":
            return "low confidence"
        if r and r.startswith("excluded_pattern:"):
            return "excluded pattern"
        return "other"

    by_cat = {}
    for d in uniq:
        by_cat.setdefault(cat(d.get("reason", "")), []).append(d)

    lines = [f"🕓 Chamonix auto-filter — {len(uniq)} held back (of {len(drops)} raw)"]
    order = ["excluded pattern", "low confidence", "duplicate", "other"]
    for c in order:
        items = by_cat.get(c)
        if not items:
            continue
        lines.append(f"\n*{c.title()}: {len(items)}*")
        for d in items[:12]:  # cap for readability
            title = d.get("title", "?")
            venue = f" @ {d['venue']}" if d.get("venue") else ""
            when = f" · {d['date']}" if d.get("date") else ""
            lines.append(f"• {title}{when}{venue}")
        if len(items) > 12:
            lines.append(f"  …and {len(items) - 12} more")

    print("\n".join(lines))

    if not keep:
        try:
            path.write_text("", encoding="utf-8")
        except OSError:
            pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
