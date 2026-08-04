#!/usr/bin/env python3
"""T55: Render a concise report of events auto-filtered by publish_rules.

Reads data/drop_report.jsonl (written by storage.upsert_events when it drops an
event). Each distinct template (source_id + normalized title) is surfaced ONCE;
once reported it's marked as "seen" and suppressed thereafter, so the feed only
shows genuinely NEW held-back patterns (which you then codify into rules). The
daily jsonl is cleared each run; the "seen" set persists in drop_report_seen.json.

Silent (no output) when there is nothing new — so clean days send nothing.

Usage:
    python -m scripts.drop_report
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

DATA = Path(__file__).resolve().parent.parent / "data"
DROP_LOG = DATA / "drop_report.jsonl"
SEEN_FILE = DATA / "drop_report_seen.json"


def _load_seen():
    if not SEEN_FILE.exists():
        return set()
    try:
        return set(json.loads(SEEN_FILE.read_text(encoding="utf-8")))
    except (json.JSONDecodeError, OSError):
        return set()


def _save_seen(seen):
    try:
        SEEN_FILE.write_text(json.dumps(sorted(seen), ensure_ascii=False, indent=0),
                             encoding="utf-8")
    except OSError:
        pass


def main():
    drops = []
    if DROP_LOG.exists():
        for line in DROP_LOG.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                drops.append(json.loads(line))
            except json.JSONDecodeError:
                pass

    # Clear the daily log regardless (it's a per-day buffer).
    try:
        DROP_LOG.write_text("", encoding="utf-8")
    except OSError:
        pass

    if not drops:
        return 0  # silent — nothing was held back

    seen = _load_seen()

    def key(d):
        return f"{d.get('source_id','')}|{(d.get('title') or '').strip().lower()}"

    # Only surface templates not already reported.
    new_drops = [d for d in drops if key(d) not in seen]
    if not new_drops:
        return 0  # everything held back is already known — stay quiet

    # Mark them as seen.
    seen.update(key(d) for d in new_drops)
    _save_seen(seen)

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
    for d in new_drops:
        by_cat.setdefault(cat(d.get("reason", "")), []).append(d)

    lines = [f"🕓 Chamonix auto-filter — {len(new_drops)} new held-back entries"]
    for c in ["excluded pattern", "low confidence", "duplicate", "other"]:
        items = by_cat.get(c)
        if not items:
            continue
        lines.append(f"\n*{c.title()}: {len(items)}*")
        for d in items[:12]:
            title = d.get("title", "?")
            venue = f" @ {d['venue']}" if d.get("venue") else ""
            when = f" · {d['date']}" if d.get("date") else ""
            lines.append(f"• {title}{when}{venue}")
        if len(items) > 12:
            lines.append(f"  …and {len(items) - 12} more")

    print("\n".join(lines))
    return 0


if __name__ == "__main__":
    sys.exit(main())
