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
        m = re.match(r"^/api/review/([0-9a-f]{16})$", path)
        if m:
            self._api_review_show(m.group(1))
            return
        return super().do_GET()

    def do_POST(self):  # noqa: N802 (stdlib naming)
        path = self.path.split("?", 1)[0]
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
