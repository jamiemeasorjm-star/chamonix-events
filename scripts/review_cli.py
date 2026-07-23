"""Operator CLI for the review queue (T15).

Lets an operator triage low-confidence or unusual events without touching
SQL or the JSON build artefacts.

Usage
-----
  python -m scripts.review_cli list [--status=open] [--source=<id>] [--limit=20]
  python -m scripts.review_cli show <id>
  python -m scripts.review_cli approve <id> [--note="..."] [--by=<reviewer>]
  python -m scripts.review_cli reject <id> --note="..." [--by=<reviewer>]
  python -m scripts.review_cli count

Status values: open | approved | rejected.

Review-item ids are 16-char hex SHA1 prefixes, stable across re-scrapes.
They are derived from (source_id, event_id, title, start_date, reason) so
the same event on the next scrape maps to the same row, and a re-scrape
does not stomp an operator's prior decision.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys_path = str(Path(__file__).resolve().parent.parent)
if sys_path not in sys.path:
    sys.path.insert(0, sys_path)

from scripts.storage import get_storage  # noqa: E402


def _short(s: str | None, n: int = 80) -> str:
    if not s:
        return "(none)"
    s = str(s)
    return s if len(s) <= n else s[: n - 1] + "…"


def cmd_list(args: argparse.Namespace) -> int:
    s = get_storage()
    items = s.list_review_items(
        status=args.status, source_id=args.source, limit=args.limit
    )
    if not items:
        print(f"No review items with status={args.status!r}")
        return 0
    print(f"{len(items)} review item(s) — status={args.status}:")
    print()
    for it in items:
        snap = {}
        raw = it.get("event_snapshot")
        if raw:
            try:
                snap = json.loads(raw)
            except json.JSONDecodeError:
                snap = {}
        rid = it["id"]
        src = it.get("source_id") or "?"
        reason = it.get("reason") or "?"
        print(f"  [{rid}]  source={src:20s}  reason={reason}")
        print(f"      title   : {_short(snap.get('title'))}")
        print(f"      date    : {snap.get('start_date') or '?'}")
        print(f"      venue   : {_short(snap.get('venue_name'))}")
        print(f"      conf    : {snap.get('confidence', '?')}")
        print(f"      created : {it.get('created_at') or '?'}")
        if it.get("reviewed_by"):
            print(
                f"      decided : {it['status']:9s} by {it['reviewed_by']} "
                f"at {it.get('reviewed_at') or '?'}"
            )
        if it.get("notes"):
            print(f"      note    : {_short(it['notes'], 200)}")
        print()
    return 0


def cmd_show(args: argparse.Namespace) -> int:
    s = get_storage()
    item = s.get_review_item(args.id)
    if not item:
        print(f"No review item with id={args.id!r}", file=sys.stderr)
        return 1
    # Pretty-print with the event_snapshot re-parsed for readability.
    snap_raw = item.get("event_snapshot")
    if snap_raw:
        try:
            item["event_snapshot_pretty"] = json.loads(snap_raw)
        except json.JSONDecodeError:
            pass
        item.pop("event_snapshot", None)
    print(json.dumps(item, indent=2, ensure_ascii=False, sort_keys=True))
    return 0


def cmd_approve(args: argparse.Namespace) -> int:
    s = get_storage()
    if s.approve_review_item(args.id, reviewer=args.by, note=args.note):
        print(f"Approved {args.id} (by={args.by})")
        return 0
    print(
        f"Could not approve {args.id} — not found or already decided.",
        file=sys.stderr,
    )
    return 1


def cmd_reject(args: argparse.Namespace) -> int:
    s = get_storage()
    if not args.note:
        print("--note is required for reject (so we have a record).", file=sys.stderr)
        return 2
    if s.reject_review_item(args.id, reviewer=args.by, note=args.note):
        print(f"Rejected {args.id} (by={args.by}): {args.note}")
        return 0
    print(
        f"Could not reject {args.id} — not found or already decided.",
        file=sys.stderr,
    )
    return 1


def cmd_count(args: argparse.Namespace) -> int:
    s = get_storage()
    # Show breakdown by status, not just total.
    counts = s.counts()
    print(f"Total review_items: {counts['review_items']}")
    for status in ("open", "approved", "rejected"):
        n = len(s.list_review_items(status=status, limit=10_000))
        print(f"  {status:9s}: {n}")
    return 0


def cmd_batch_approve(args: argparse.Namespace) -> int:
    """T43: batch-approve review items matching criteria."""
    s = get_storage()
    items = s.list_review_items(
        status="open",
        source_id=args.source,
        limit=args.limit,
        min_confidence=args.min_confidence,
        max_confidence=args.max_confidence,
    )
    if not items:
        print("No matching open items to approve.")
        return 0
    count = 0
    for it in items:
        if s.approve_review_item(it["id"], reviewer=args.by, note=args.note or "auto-approved"):
            count += 1
    print(f"Batch-approved {count} item(s) (matched {len(items)})")
    return 0


def cmd_batch_reject(args: argparse.Namespace) -> int:
    """T43: batch-reject review items matching criteria."""
    s = get_storage()
    items = s.list_review_items(
        status="open",
        source_id=args.source,
        limit=args.limit,
        min_confidence=args.min_confidence,
        max_confidence=args.max_confidence,
    )
    if not items:
        print("No matching open items to reject.")
        return 0
    note = args.note or "batch-rejected"
    count = 0
    for it in items:
        if s.reject_review_item(it["id"], reviewer=args.by, note=note):
            count += 1
    print(f"Batch-rejected {count} item(s) (matched {len(items)})")
    return 0


def cmd_auto_triage(args: argparse.Namespace) -> int:
    """T43: run auto-triage — approve high-confidence, reject stale low-confidence."""
    s = get_storage()
    result = s.auto_triage()
    print(f"Auto-triage complete:")
    print(f"  Approved: {result['approved']}")
    print(f"  Rejected: {result['rejected']}")
    if result['errors']:
        print(f"  Errors:   {result['errors']} (check stderr)")
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="review_cli",
        description="Chamonix events review queue CLI (T15).",
    )
    sub = p.add_subparsers(dest="cmd", required=True)

    p_list = sub.add_parser("list", help="List review items")
    p_list.add_argument(
        "--status", default="open", help="open | approved | rejected (default: open)"
    )
    p_list.add_argument("--source", default=None, help="filter by source_id")
    p_list.add_argument("--limit", type=int, default=20)
    p_list.set_defaults(func=cmd_list)

    p_show = sub.add_parser("show", help="Show a single review item")
    p_show.add_argument("id")
    p_show.set_defaults(func=cmd_show)

    p_appr = sub.add_parser("approve", help="Approve a review item")
    p_appr.add_argument("id")
    p_appr.add_argument("--note", default=None)
    p_appr.add_argument("--by", default="operator")
    p_appr.set_defaults(func=cmd_approve)

    p_rej = sub.add_parser(
        "reject", help="Reject a review item (note required)"
    )
    p_rej.add_argument("id")
    p_rej.add_argument("--note", required=True)
    p_rej.add_argument("--by", default="operator")
    p_rej.set_defaults(func=cmd_reject)

    p_count = sub.add_parser(
        "count", help="Show review_items counts by status"
    )
    p_count.set_defaults(func=cmd_count)

    # T43: batch operations
    p_bappr = sub.add_parser(
        "batch-approve", help="Batch-approve items matching criteria"
    )
    p_bappr.add_argument("--source", default=None, help="filter by source_id")
    p_bappr.add_argument("--limit", type=int, default=1000)
    p_bappr.add_argument("--min-confidence", type=float, default=None)
    p_bappr.add_argument("--max-confidence", type=float, default=None)
    p_bappr.add_argument("--note", default=None)
    p_bappr.add_argument("--by", default="operator")
    p_bappr.set_defaults(func=cmd_batch_approve)

    p_brej = sub.add_parser(
        "batch-reject", help="Batch-reject items matching criteria"
    )
    p_brej.add_argument("--source", default=None, help="filter by source_id")
    p_brej.add_argument("--limit", type=int, default=1000)
    p_brej.add_argument("--min-confidence", type=float, default=None)
    p_brej.add_argument("--max-confidence", type=float, default=None)
    p_brej.add_argument("--note", default=None)
    p_brej.add_argument("--by", default="operator")
    p_brej.set_defaults(func=cmd_batch_reject)

    p_auto = sub.add_parser(
        "auto-triage", help="Auto-approve high-confidence + auto-reject stale low-confidence"
    )
    p_auto.set_defaults(func=cmd_auto_triage)

    return p


def main() -> int:
    args = build_parser().parse_args()
    return int(args.func(args) or 0)


if __name__ == "__main__":
    sys.exit(main())
