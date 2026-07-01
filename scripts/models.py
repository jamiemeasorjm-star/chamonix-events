from __future__ import annotations

import json
import os
import re
import uuid
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def slugify(text: str) -> str:
    s = text.lower().strip()
    s = re.sub(r"[^\w\s-]", "", s)
    s = re.sub(r"[-\s]+", "-", s)
    return s.strip("-")


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def write_atomic_json(path: str | os.PathLike, data: Any, *, indent: int = 2, ensure_ascii: bool = False) -> None:
    """Atomically write JSON to ``path``.

    Writes to a unique temp file in the same directory, fsyncs, then renames
    over the target. A crash mid-write leaves the existing file untouched.

    Added for ticket T03 (Phase 1 stabilisation).
    """
    path = Path(path)
    parent = path.parent
    parent.mkdir(parents=True, exist_ok=True)

    payload = json.dumps(data, indent=indent, ensure_ascii=ensure_ascii)
    tmp_name = f".{path.name}.tmp.{os.getpid()}.{uuid.uuid4().hex[:8]}"
    tmp_path = parent / tmp_name

    try:
        with open(tmp_path, "w", encoding="utf-8") as f:
            f.write(payload)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_path, path)
    except Exception:
        # Best-effort cleanup of the temp file on failure
        try:
            if tmp_path.exists():
                tmp_path.unlink()
        except OSError:
            pass
        raise


def write_atomic_text(path: str | os.PathLike, text: str) -> None:
    """Atomically write a UTF-8 text file. Same crash-safety as write_atomic_json.

    Added for ticket T03 (Phase 1 stabilisation).
    """
    path = Path(path)
    parent = path.parent
    parent.mkdir(parents=True, exist_ok=True)

    tmp_name = f".{path.name}.tmp.{os.getpid()}.{uuid.uuid4().hex[:8]}"
    tmp_path = parent / tmp_name

    try:
        with open(tmp_path, "w", encoding="utf-8") as f:
            f.write(text)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_path, path)
    except Exception:
        try:
            if tmp_path.exists():
                tmp_path.unlink()
        except OSError:
            pass
        raise


@dataclass
class Venue:
    id: str
    name: str
    commune: str = "Chamonix"
    address: str = ""
    latitude: float | None = None
    longitude: float | None = None
    url: str | None = None
    phone: str | None = None
    source_id: str = ""

    def to_dict(self) -> dict:
        return {k: v for k, v in asdict(self).items() if v is not None or k == "address"}


@dataclass
class Event:
    id: str = ""
    title: str = ""
    description: str = ""
    start_date: str = ""
    end_date: str | None = None
    time: str | None = None
    venue_id: str | None = None
    category: str = "other"
    commune: str = "Chamonix"
    source_id: str = "chamonix_com"
    source_url: str = ""
    image_url: str | None = None
    price: str | None = None
    venue_name: str | None = None
    address: str | None = None
    contact_phone: str | None = None
    website: str | None = None
    status: str = "published"
    confidence: float = 1.0
    created_at: str = ""
    updated_at: str = ""

    def __post_init__(self):
        if not self.id and self.title and self.start_date:
            base = slugify(self.title)
            date_part = self.start_date[:10]
            self.id = f"{base}-{date_part}"
        if not self.created_at:
            self.created_at = now_iso()
        if not self.updated_at:
            self.updated_at = now_iso()

    def to_dict(self) -> dict:
        return {k: v for k, v in asdict(self).items() if v is not None}


# T13: Source dataclass (per docs/schema.md)
# Trust-level -> confidence baseline (per plan §8.2):
#   high   -> 1.0
#   medium -> 0.8
#   low    -> 0.55
TRUST_BASELINE = {"high": 1.0, "medium": 0.8, "low": 0.55}


@dataclass
class Source:
    id: str
    name: str
    type: str = "scraper"           # official | aggregator | venue | scraper | community
    base_url: str | None = None
    trust_level: str = "medium"     # high | medium | low
    ingestion_cadence_hours: int | None = None
    active: bool = True
    notes: str = ""
    # T26: per-source publish threshold override (None = use global default).
    # When set, events from this source below this confidence go to
    # review_items instead of the events table.
    min_publish_confidence: float | None = None

    def confidence_baseline(self) -> float:
        return TRUST_BASELINE.get(self.trust_level, 0.5)

    def to_dict(self) -> dict:
        return {k: v for k, v in asdict(self).items() if v is not None or k == "notes"}
