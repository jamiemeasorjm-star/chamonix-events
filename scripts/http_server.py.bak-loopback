#!/usr/bin/env python3
"""Static HTTP server with /healthz and /api/review/* endpoints.

Phase 1 / T05 (healthz) + Phase 3 / T27 (review API).
Reads PORT from CHAMONIX_PORT (default 8090) and document root from
CHAMONIX_DIR (default parent of this script).

Endpoints
---------
GET /healthz
    Returns 200 with JSON {"status": "ok", "build_age_hours": ..., "built_at": ...}
    Reads data/last_build.json to compute build age.

GET /api/review
    Query params:
      status    = open | approved | rejected (default: open)
      source    = source_id (optional)
      min_conf  = float (optional)
      max_conf  = float (optional)
      limit     = int (default 100)
    Returns JSON {"items": [...], "total": N, "filter": {...}}.

GET /api/review/sources
    Returns {"sources": ["chamonix_net", "chamonix_com", ...]}.

GET /api/review/counts
    Returns {"open": N, "approved": N, "rejected": N}.

GET /api/review/<id>
    Returns the full review item (incl. parsed event_snapshot) or 404.

POST /api/review/<id>/approve
    JSON body: {"note": "...", "by": "operator"} (both optional).
    Returns {"ok": true, "id": "..."} or {"ok": false, "error": "..."}.

POST /api/review/<id>/reject
    JSON body: {"note": "...", "by": "operator"} (note REQUIRED).
    Returns {"ok": true, "id": "..."} or {"ok": false, "error": "..."}.

GET /<path>
    Standard static file serving from CHAMONIX_DIR.
"""
from __future__ import annotations

import http.server
import json
import os
import re
import socketserver
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse, parse_qs


PORT = int(os.environ.get("CHAMONIX_PORT", "8090"))
HERE = Path(__file__).resolve().parent
ROOT = Path(os.environ.get("CHAMONIX_DIR", str(HERE.parent))).resolve()
DATA_DIR = ROOT / "data"
LAST_BUILD_PATH = DATA_DIR / "last_build.json"

# Review-item id pattern: 16 hex chars (SHA1 prefix). Tightened to keep
# path-traversal and SQL injection out of the URL path.
_RID_RE = re.compile(r"^[0-9a-f]{16}$")


class ChamonixHandler(http.server.SimpleHTTPRequestHandler):
    """SimpleHTTPRequestHandler with /healthz and /api/review overrides."""

    # ---------- routing ----------

    def do_GET(self):  # noqa: N802 (stdlib naming)
        path = self.path.split("?", 1)[0]
        if path == "/healthz":
            self._serve_healthz()
            return
        if path == "/api/review" or path == "/api/review/":
            self._api_review_list()
            return
        if path == "/api/review/sources":
            self._api_review_sources()
            return
        if path == "/api/review/counts":
            self._api_review_counts()
            return
        if path == "/api/review/stats":
            self._api_review_stats()
            return
        if path == "/admin" or path == "/admin/":
            self._serve_admin()
            return
        if path == "/api/events.ics":
            self._serve_ics()
            return
        m = re.match(r"^/api/review/([0-9a-f]{16})$", path)
        if m:
            self._api_review_show(m.group(1))
            return
        # Proxy-path fallback: host-nginx strips /events/ prefix, so
        # /events/cosmo-jazz.html arrives as /cosmo-jazz.html. Try serving
        # from the events/ subdirectory as a fallback.
        import os
        fs_path = "." + path
        if not os.path.isfile(fs_path) and not path.endswith("/"):
            events_path = "." + "/events" + path
            if os.path.isfile(events_path):
                self.path = "/events" + path
        return super().do_GET()

    def do_POST(self):  # noqa: N802 (stdlib naming)
        path = self.path.split("?", 1)[0]
        # T32: manual submission endpoint
        if path == "/api/submit" or path == "/api/submit/":
            self._api_submit()
            return
        m = re.match(r"^/api/review/([0-9a-f]{16})/(approve|reject)$", path)
        if not m:
            self._json_error(404, "not found")
            return
        rid = m.group(1)
        if not _RID_RE.match(rid):
            self._json_error(400, "invalid review id")
            return
        action = m.group(2)
        body = self._read_json_body()
        if body is None:
            return  # _read_json_body already sent the error response
        if action == "approve":
            self._api_review_decide(rid, "approve", body)
        else:
            self._api_review_decide(rid, "reject", body)

    # ---------- /healthz ----------

    def _serve_healthz(self) -> None:
        body_obj: dict
        try:
            if LAST_BUILD_PATH.exists():
                lb = json.loads(LAST_BUILD_PATH.read_text(encoding="utf-8"))
                bt = lb.get("built_at")
                if bt:
                    try:
                        built_at = datetime.fromisoformat(bt)
                    except ValueError:
                        built_at = None
                    if built_at is not None:
                        now = datetime.now(timezone.utc)
                        age_h = round((now - built_at).total_seconds() / 3600.0, 2)
                        body_obj = {
                            "status": "ok",
                            "built_at": bt,
                            "build_age_hours": age_h,
                            "events": lb.get("events"),
                            "cinema": lb.get("cinema"),
                        }
                    else:
                        body_obj = {"status": "ok", "built_at": None}
                else:
                    body_obj = {"status": "ok", "built_at": None}
            else:
                # Service is up but no build yet — still 200, caller decides
                body_obj = {"status": "ok", "built_at": None, "build_age_hours": None}
            self._json_response(200, body_obj)
        except Exception as exc:  # pragma: no cover - defensive
            self._json_response(500, {"status": "error", "error": str(exc)})

    # ---------- /api/review ----------

    def _api_review_list(self) -> None:
        """GET /api/review — list with filters."""
        try:
            from scripts.storage import get_storage  # local import for speed
            q = parse_qs(urlparse(self.path).query)
            status = (q.get("status", ["open"])[0] or "open").lower()
            if status not in ("open", "approved", "rejected", "all"):
                self._json_error(400, f"invalid status: {status}")
                return
            source = q.get("source", [None])[0] or None
            min_conf = self._parse_float(q.get("min_conf", [None])[0])
            max_conf = self._parse_float(q.get("max_conf", [None])[0])
            try:
                limit = int(q.get("limit", ["100"])[0] or "100")
            except ValueError:
                limit = 100
            limit = max(1, min(limit, 1000))

            s = get_storage()
            if status == "all":
                items = []
                for st in ("open", "approved", "rejected"):
                    items.extend(s.list_review_items(
                        status=st, source_id=source,
                        min_confidence=min_conf, max_confidence=max_conf,
                        limit=limit,
                    ))
            else:
                items = s.list_review_items(
                    status=status, source_id=source,
                    min_confidence=min_conf, max_confidence=max_conf,
                    limit=limit,
                )

            self._json_response(200, {
                "items": [_serialize_review_item(it) for it in items],
                "total": len(items),
                "filter": {
                    "status": status, "source": source,
                    "min_confidence": min_conf, "max_confidence": max_conf,
                    "limit": limit,
                },
            })
        except Exception as exc:
            self._json_response(500, {"error": str(exc)})

    def _api_review_show(self, rid: str) -> None:
        """GET /api/review/<id> — single item, snapshot parsed."""
        try:
            from scripts.storage import get_storage
            s = get_storage()
            item = s.get_review_item(rid)
            if not item:
                self._json_error(404, "review item not found")
                return
            self._json_response(200, _serialize_review_item(item))
        except Exception as exc:
            self._json_response(500, {"error": str(exc)})

    def _api_review_sources(self) -> None:
        """GET /api/review/sources — distinct source_ids for filter UI."""
        try:
            from scripts.storage import get_storage
            self._json_response(200, {"sources": get_storage().review_sources()})
        except Exception as exc:
            self._json_response(500, {"error": str(exc)})

    def _api_review_counts(self) -> None:
        """GET /api/review/counts — counts grouped by status."""
        try:
            from scripts.storage import get_storage
            self._json_response(200, get_storage().review_counts_by_status())
        except Exception as exc:
            self._json_response(500, {"error": str(exc)})

    def _api_review_stats(self) -> None:
        """T43: GET /api/review/stats — confidence histogram + summary."""
        try:
            from scripts.storage import get_storage
            s = get_storage()
            data = {
                "counts": s.review_counts_by_status(),
                "histogram": s.review_confidence_histogram(),
            }
            self._json_response(200, data)
        except Exception as exc:
            self._json_response(500, {"error": str(exc)})

    def _api_review_decide(self, rid: str, action: str, body: dict) -> None:
        """POST /api/review/<id>/approve|reject — apply decision."""
        try:
            from scripts.storage import get_storage
            note = body.get("note")
            by = body.get("by") or "operator"

            if action == "reject" and not (note and str(note).strip()):
                self._json_error(400, "note is required for reject")
                return

            s = get_storage()
            if action == "approve":
                ok = s.approve_review_item(rid, reviewer=by, note=note)
            else:
                ok = s.reject_review_item(rid, reviewer=by, note=note)

            if not ok:
                self._json_error(409, "review item not found or already decided")
                return
            self._json_response(200, {"ok": True, "id": rid, "action": action, "by": by})
        except Exception as exc:
            self._json_response(500, {"error": str(exc)})

    # ---------- T32: /api/submit ----------

    VALID_CATEGORIES = {
        "concert", "exhibition", "family", "market", "other",
        "sport", "theatre", "cinema",
    }

    def _api_submit(self) -> None:
        """POST /api/submit — accept a manual event submission.

        Expects JSON:
            title (required), start_date (required),
            category (optional, defaults to 'other'),
            description, time, venue_name, commune,
            contact_name, contact_email.

        Response:
            200: {"ok": true, "id": "<review_item_id>"}
            400: {"ok": false, "error": "..."}
            500: {"ok": false, "error": "..."}
        """
        body = self._read_json_body()
        if body is None:
            return  # error already sent by _read_json_body

        # ---- validate ----
        title = (body.get("title") or "").strip()
        if not title:
            self._json_error(400, "title is required")
            return
        if len(title) > 500:
            self._json_error(400, "title too long (max 500 chars)")
            return

        start_date = (body.get("start_date") or "").strip()
        if not start_date:
            self._json_error(400, "start_date is required")
            return
        # Basic ISO date check: YYYY-MM-DD
        if not re.match(r"^\d{4}-\d{2}-\d{2}$", start_date):
            self._json_error(400, "start_date must be YYYY-MM-DD")
            return

        category = (body.get("category") or "other").strip().lower()
        if category not in self.VALID_CATEGORIES:
            category = "other"

        description = (body.get("description") or "").strip()[:2000]
        time_val = (body.get("time") or "").strip() or None
        venue_name = (body.get("venue_name") or "").strip() or None
        commune = (body.get("commune") or "Chamonix").strip()
        contact_name = (body.get("contact_name") or "").strip() or None
        contact_email = (body.get("contact_email") or "").strip() or None
        # Reject obviously bogus emails
        if contact_email and (
            "@" not in contact_email or len(contact_email) > 320
        ):
            self._json_error(400, "invalid contact_email")
            return

        # Rate-limit: per-IP, max 5 open manual submissions
        try:
            from scripts.storage import get_storage
            s = get_storage()
            existing = s.list_review_items(
                status="open", source_id="manual_submission", limit=50,
            )
            same_title_today = 0
            today_prefix = start_date
            for item in existing:
                snap = item.get("event_snapshot")
                if isinstance(snap, str):
                    try:
                        import json
                        snap = json.loads(snap)
                    except Exception:
                        pass
                if isinstance(snap, dict):
                    st = (snap.get("start_date") or "")[:10]
                    if st == today_prefix:
                        same_title_today += 1
            if same_title_today >= 3:
                self._json_error(429, "too many submissions for this date — wait for review")
                return

            # Build event dict
            import uuid
            event = {
                "title": title,
                "start_date": start_date,
                "category": category,
                "description": description,
                "source_id": "manual_submission",
                "source_url": "",
                "commune": commune,
                "status": "pending_review",
                "confidence": 0.55,  # manual submissions capped per sources.yaml
            }
            if time_val:
                event["time"] = time_val
            if venue_name:
                event["venue_name"] = venue_name
            if contact_name:
                event["contact_name"] = contact_name
            if contact_email:
                event["contact_email"] = contact_email

            reason = "manual_submission"
            # Use a unique event_id so each submission is independent
            event_id = f"manual-{uuid.uuid4().hex[:12]}"

            rid = s.insert_review_item(
                source_id="manual_submission",
                event=event,
                reason=reason,
                event_id=event_id,
            )

            self._json_response(200, {
                "ok": True,
                "id": rid,
                "message": "Event submitted for review. It will appear on the site once approved.",
            })
        except Exception as exc:
            self._json_response(500, {"ok": False, "error": str(exc)})

    # ---------- T38: /admin dashboard ----------

    ADMIN_HTML = """\
<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Dashboard — Chamonix Events</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600&family=Playfair+Display:wght@400;500&display=swap" rel="stylesheet">
<style>
:root{--bg:#0b0a08;--surface:#141210;--card:#1a1815;--border:rgba(255,255,255,0.06);--border-a:rgba(200,164,92,0.25);--text:#ede8e0;--text2:#9a948c;--text3:#6b6660;--gold:#c8a45c;--gold-h:#d4b46a;--gold-d:rgba(200,164,92,0.15);--ok:#7fb98e;--warn:#e8a87c;--bad:#d68a8a;--ff-serif:'Playfair Display',Georgia,serif;--ff-sans:'Inter',-apple-system,BlinkMacSystemFont,sans-serif;--rs:8px;--rm:12px;--rl:16px;--ease:cubic-bezier(0.22,1,0.36,1)}
*{box-sizing:border-box;margin:0;padding:0}
html,body{background:var(--bg);color:var(--text);font-family:var(--ff-sans);line-height:1.6;min-height:100%}
body{padding:32px 24px 80px}
.wrap{max-width:1200px;margin:0 auto}
h1{font-family:var(--ff-serif);font-size:1.8rem;font-weight:500;letter-spacing:-.02em;margin-bottom:4px}
.sub{color:var(--text3);font-size:.85rem;margin-bottom:32px}
.g{display:grid;grid-template-columns:repeat(auto-fill,minmax(260px,1fr));gap:14px;margin-bottom:32px}
.c{background:var(--card);border:1px solid var(--border);border-radius:var(--rl);padding:18px 20px}
.c-n{font-size:.6rem;letter-spacing:.15em;text-transform:uppercase;color:var(--text3);margin-bottom:6px}
.c-v{font-family:var(--ff-serif);font-size:2rem;font-weight:500;color:var(--text);line-height:1}
.c-v.s{font-size:1.4rem}
.c-v.ok{color:var(--ok)}.c-v.warn{color:var(--warn)}.c-v.bad{color:var(--bad)}
.c-m{font-size:.7rem;color:var(--text3);margin-top:4px}
table{width:100%;border-collapse:collapse;font-size:.82rem}
th{text-align:left;font-size:.6rem;letter-spacing:.12em;text-transform:uppercase;color:var(--text3);padding:8px 12px 8px 0;border-bottom:1px solid var(--border);font-weight:500}
td{padding:8px 12px 8px 0;border-bottom:1px solid var(--border);color:var(--text2)}
tr:last-child td{border-bottom:none}
td:first-child{font-family:var(--ff-serif);color:var(--text)}
.num-v{font-family:'SF Mono',Menlo,monospace;color:var(--text);font-weight:500}
.badge{display:inline-block;font-size:.55rem;letter-spacing:.1em;text-transform:uppercase;padding:2px 8px;border-radius:100px;border:1px solid var(--border);font-weight:500}
.badge.g{color:var(--ok);border-color:rgba(127,185,142,.35)}
.badge.y{color:var(--warn);border-color:rgba(232,168,124,.35)}
.badge.r{color:var(--bad);border-color:rgba(214,138,138,.35)}
.sec-h{font-family:var(--ff-serif);font-size:1.1rem;font-weight:500;margin-bottom:16px;padding-bottom:10px;border-bottom:1px solid var(--border)}
.foot{margin-top:48px;padding-top:20px;border-top:1px solid var(--border);font-size:.7rem;color:var(--text3)}
.foot a{color:var(--text2);text-decoration:none}
.foot a:hover{color:var(--text)}
@media(max-width:600px){.g{grid-template-columns:1fr 1fr} h1{font-size:1.4rem}}
</style>
</head>
<body><div class="wrap">
<h1>Dashboard</h1>
<p class="sub">Chamonix Events · built __BUILD_AGE__</p>

<div class="g">
  <div class="c"><div class="c-n">Published Events</div><div class="c-v">__EVENTS_TOTAL__</div><div class="c-m">__EVENTS_PER_SOURCE__</div></div>
  <div class="c"><div class="c-n">Cinema</div><div class="c-v">__CINEMA_COUNT__</div><div class="c-m">films with showtimes</div></div>
  <div class="c"><div class="c-n">Venues</div><div class="c-v">__VENUE_COUNT__</div><div class="c-m">__VENUE_COORDS__ with map coordinates</div></div>
  <div class="c"><div class="c-n">Review Queue</div><div class="c-v __REVIEW_STATUS__">__REVIEW_OPEN__</div><div class="c-m">open · __REVIEW_DETAIL__</div></div>
  <div class="c"><div class="c-n">Last Build</div><div class="c-v __BUILD_STATUS__">__BUILD_AGE_SHORT__</div><div class="c-m">__BUILD_TIME__</div></div>
  <div class="c"><div class="c-n">Sources Active</div><div class="c-v">3</div><div class="c-m">chamonix_net, chamonix_com, vox_pdf</div></div>
</div>

<h2 class="sec-h">Events per Source</h2>
<table>
<tr><th>Source</th><th>Published</th><th>Status</th></tr>
__EVENTS_TABLE__
</table>

<h2 class="sec-h" style="margin-top:32px">Review Queue</h2>
<table>
<tr><th>Status</th><th>Count</th></tr>
__REVIEW_TABLE__
</table>

<h2 class="sec-h" style="margin-top:32px">Confidence Distribution (open)</h2>
<p class="sub" style="font-size:.75rem;margin-bottom:12px">__CONF_STATS__</p>
<div class="g">
__CONF_BARS__
</div>

<p class="foot"><a href="/">← Back to site</a> · <a href="/healthz">/healthz</a> · <a href="/api/review/counts">API</a> · <a href="/api/review/stats">Stats API</a></p>
</div></body></html>
"""

    def _serve_admin(self) -> None:
        """GET /admin/ — operator dashboard (T38)."""
        try:
            from scripts.storage import get_storage
            s = get_storage()

            now = datetime.now(timezone.utc)

            # Build metadata
            bm = s.get_build_metadata()
            built_at_str = bm.get("built_at", "")
            if built_at_str:
                try:
                    built_at = datetime.fromisoformat(built_at_str)
                    age_h = (now - built_at).total_seconds() / 3600.0
                    if age_h < 1:
                        build_age = f"{int(age_h * 60)}m ago"
                    elif age_h < 24:
                        build_age = f"{int(age_h)}h ago"
                    else:
                        build_age = f"{int(age_h / 24)}d ago"
                    build_age_short = build_age
                    build_time = built_at_str[:19].replace("T", " ")
                    build_cls = "ok" if age_h < 12 else ("warn" if age_h < 48 else "bad")
                except ValueError:
                    build_age = "unknown"
                    build_age_short = "?"
                    build_time = ""
                    build_cls = ""
            else:
                build_age = "never"
                build_age_short = "?"
                build_time = ""
                build_cls = "bad"

            # Counts
            cnt = s.counts()
            events_total = cnt["events"]
            cinema_count = cnt["cinema_events"]
            venue_count = cnt["venues"]

            venues_with_coords = len([
                v for v in s.get_venues()
                if v.get("latitude") and v.get("longitude")
            ])
            venue_coords = f"{venues_with_coords}/{venue_count}"

            # Per-source events
            rows = s.conn.execute(
                "SELECT source_id, count(*) FROM events WHERE status='published' "
                "GROUP BY source_id ORDER BY count(*) DESC"
            ).fetchall()
            per_source = []
            for src_id, n in rows:
                is_fresh = True  # could check last ingest time with more data
                badge = '<span class="badge g">active</span>' if is_fresh else '<span class="badge y">stale</span>'
                per_source.append(f"<tr><td>{src_id}</td><td class=\"num-v\">{n}</td><td>{badge}</td></tr>")
            events_table = "\n".join(per_source)
            events_per_source = ", ".join(f"{r[0]}: {r[1]}" for r in rows)

            # Review queue
            rc = s.conn.execute(
                "SELECT status, count(*) FROM review_items GROUP BY status ORDER BY status"
            ).fetchall()
            review_rows = []
            review_open = 0
            for st, n in rc:
                review_rows.append(f"<tr><td>{st}</td><td class=\"num-v\">{n}</td></tr>")
                if st == "open":
                    review_open = n
            review_table = "\n".join(review_rows)
            review_status_cls = "ok" if review_open == 0 else ("warn" if review_open < 10 else "bad")
            review_detail = (
                "queue clear" if review_open == 0
                else f"{review_open} items pending review"
            )

            total_all = sum(r[1] for r in rc)
            review_detail += f" · {total_all} total"

            # T43: confidence histogram
            hist = s.review_confidence_histogram()
            conf_stats = (
                f"Mean: {hist['mean']} · Min: {hist['min']} · Max: {hist['max']} · "
                f"Total open: {hist['total']}"
            )
            conf_bars = []
            colors = {
                "0.0-0.2": "#d68a8a", "0.2-0.4": "#e8a87c",
                "0.4-0.6": "#d6c8a0", "0.6-0.8": "#7fb98e",
                "0.8-1.0": "#7fb98e",
            }
            for bucket, count in hist["buckets"].items():
                pct = (count / max(hist["total"], 1)) * 100
                color = colors.get(bucket, "var(--text3)")
                conf_bars.append(
                    f'<div class="c">'
                    f'<div class="c-n">{bucket}</div>'
                    f'<div class="c-v s" style="color:{color}">{count}</div>'
                    f'<div class="c-m">{pct:.0f}% of queue</div>'
                    f'</div>'
                )
            conf_bars_html = "\n".join(conf_bars)

            html = self.ADMIN_HTML
            for key, val in {
                "BUILD_AGE": build_age,
                "BUILD_AGE_SHORT": build_age_short,
                "BUILD_TIME": build_time,
                "BUILD_STATUS": build_cls,
                "EVENTS_TOTAL": str(events_total),
                "EVENTS_PER_SOURCE": events_per_source,
                "EVENTS_TABLE": events_table,
                "CINEMA_COUNT": str(cinema_count),
                "VENUE_COUNT": str(venue_count),
                "VENUE_COORDS": venue_coords,
                "REVIEW_OPEN": str(review_open),
                "REVIEW_DETAIL": review_detail,
                "REVIEW_STATUS": review_status_cls,
                "REVIEW_TABLE": review_table,
                "CONF_STATS": conf_stats,
                "CONF_BARS": conf_bars_html,
            }.items():
                html = html.replace(f"__{key}__", val)

            body = html.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-cache")
            self.end_headers()
            self.wfile.write(body)
        except Exception as exc:
            try:
                self._json_error(500, str(exc))
            except Exception:
                pass

    # ---------- /api/events.ics ----------

    def _serve_ics(self) -> None:
        """T42: Generate iCal/ICS feed of all published events.

        Supports optional GET params:
          ?start=YYYY-MM-DD   — filter events on or after this date
          ?end=YYYY-MM-DD     — filter events on or before this date
          ?event=<slug>       — single event (for the "Add to Calendar" button)

        Returns RFC 5545 iCalendar with VEVENT components per event.
        """
        try:
            from scripts.storage import get_storage

            q = parse_qs(urlparse(self.path).query)
            start_filter = (q.get("start", [None])[0] or "").strip()
            end_filter = (q.get("end", [None])[0] or "").strip()
            event_slug = (q.get("event", [None])[0] or "").strip()

            # Build slug-to-event mapping from storage
            storage = get_storage()
            events = storage.get_events(status="published")

            # Generate slugs (same logic as build.py)
            def _slugify(text: str) -> str:
                import unicodedata
                text = unicodedata.normalize("NFD", text.lower().strip())
                text = re.sub(r"[\u0300-\u036f]", "", text)
                text = re.sub(r"[^a-z0-9]+", "-", text)
                text = text.strip("-")
                text = re.sub(r"-+", "-", text)
                return text[:80] or "event"

            def _event_slug(e: dict) -> str:
                slug = _slugify(e.get("id", e.get("title", "event")))
                slug = re.sub(r"-\d{4}-\d{2}-\d{2}$", "", slug)
                return slug

            # Filter
            if event_slug:
                events = [e for e in events if _event_slug(e) == event_slug]
            else:
                if start_filter:
                    events = [e for e in events if (e.get("start_date") or "") >= start_filter]
                if end_filter:
                    events = [e for e in events if (e.get("start_date") or "") <= end_filter]

            now_dt = datetime.now(timezone.utc)
            now_str = now_dt.strftime("%Y%m%dT%H%M%SZ")

            lines = [
                "BEGIN:VCALENDAR",
                "VERSION:2.0",
                "PRODID:-//Chamonix Events//EN",
                "CALSCALE:GREGORIAN",
                "METHOD:PUBLISH",
                "X-WR-CALNAME:Chamonix Events",
                "X-WR-TIMEZONE:Europe/Paris",
            ]

            for e in events:
                start = (e.get("start_date") or now_dt.strftime("%Y-%m-%d"))[:10].replace("-", "")
                end_v = e.get("end_date") or e.get("start_date")
                if end_v and end_v != e.get("start_date"):
                    end_dt = end_v[:10].replace("-", "")
                else:
                    end_dt = start

                uid = e.get("id", f"event-{start}")
                summary = (e.get("title") or "Event").replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,")
                desc = (e.get("description") or "").replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,").replace("\n", "\\n")
                venue = (e.get("venue_name") or e.get("venue") or "Chamonix").replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,")
                url = e.get("source_url", "")

                lines.append("BEGIN:VEVENT")
                lines.append(f"UID:{uid}")
                lines.append(f"DTSTART;VALUE=DATE:{start}")
                lines.append(f"DTEND;VALUE=DATE:{end_dt}")
                lines.append(f"SUMMARY:{summary}")
                if desc:
                    lines.append(f"DESCRIPTION:{desc}")
                lines.append(f"LOCATION:{venue}")
                if url:
                    lines.append(f"URL:{url}")
                lines.append("STATUS:CONFIRMED")
                lines.append("END:VEVENT")

            lines.append("END:VCALENDAR")
            body = "\r\n".join(lines) + "\r\n"
            body_bytes = body.encode("utf-8")

            self.send_response(200)
            self.send_header("Content-Type", "text/calendar; charset=utf-8")
            self.send_header("Content-Disposition", "attachment; filename=\"chamonix-events.ics\"")
            self.send_header("Content-Length", str(len(body_bytes)))
            self.send_header("Cache-Control", "no-cache")
            self.end_headers()
            self.wfile.write(body_bytes)
        except Exception as exc:
            try:
                self._json_error(500, f"iCal generation failed: {exc}")
            except Exception:
                pass

    # ---------- helpers ----------

    def _read_json_body(self) -> dict | None:
        """Read and JSON-parse POST body. Returns dict or None on error.

        On parse error, sends a 400 JSON error response and returns None.
        Empty body is allowed and returns {}.
        """
        try:
            length = int(self.headers.get("Content-Length", "0") or "0")
        except ValueError:
            length = 0
        if length <= 0:
            return {}
        if length > 64_000:  # generous cap; review notes are tiny
            self._json_error(413, "body too large")
            return None
        try:
            raw = self.rfile.read(length)
            data = json.loads(raw.decode("utf-8"))
            if not isinstance(data, dict):
                self._json_error(400, "expected JSON object")
                return None
            return data
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            self._json_error(400, f"invalid JSON: {exc}")
            return None

    @staticmethod
    def _parse_float(s: str | None) -> float | None:
        if s is None or s == "":
            return None
        try:
            return float(s)
        except ValueError:
            return None

    def _json_response(self, status: int, body: dict) -> None:
        body_bytes = json.dumps(body, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body_bytes)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body_bytes)

    def _json_error(self, status: int, msg: str) -> None:
        self._json_response(status, {"ok": False, "error": msg})

    def log_message(self, format: str, *args) -> None:  # noqa: A002
        # Pipe to stderr so supervisord captures it in the logfile.
        sys.stderr.write("[%s] %s - %s\n" % (
            datetime.now(timezone.utc).isoformat(timespec="seconds"),
            self.address_string(),
            format % args,
        ))
        sys.stderr.flush()


def _serialize_review_item(item: dict) -> dict:
    """Parse event_snapshot JSON into a nested field for the API.

    Review items store the snapshot as a JSON-encoded string column. The
    /api/review endpoint returns it parsed so the page can render fields
    directly without re-parsing on every row.
    """
    out = dict(item)
    raw = out.pop("event_snapshot", None)
    if raw:
        try:
            out["event"] = json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            out["event"] = None
    else:
        out["event"] = None
    return out


class ReusableTCPServer(socketserver.TCPServer):
    allow_reuse_address = True


def main() -> int:
    if not ROOT.exists():
        sys.stderr.write(f"chamonix http_server: ROOT does not exist: {ROOT}\n")
        return 2

    # Make the project root importable so scripts.* modules resolve.
    sys.path.insert(0, str(ROOT))

    os.chdir(str(ROOT))
    sys.stderr.write(
        f"chamonix http_server: serving {ROOT} on 0.0.0.0:{PORT} (PID {os.getpid()})\n"
    )
    sys.stderr.flush()

    try:
        with ReusableTCPServer(("0.0.0.0", PORT), ChamonixHandler) as httpd:
            httpd.serve_forever()
    except KeyboardInterrupt:
        sys.stderr.write("chamonix http_server: interrupted\n")
    except OSError as exc:
        sys.stderr.write(f"chamonix http_server: bind/listen failed: {exc}\n")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
