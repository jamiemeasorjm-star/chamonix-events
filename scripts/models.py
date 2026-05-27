from __future__ import annotations

import re
import uuid
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone


def slugify(text: str) -> str:
    s = text.lower().strip()
    s = re.sub(r"[^\w\s-]", "", s)
    s = re.sub(r"[-\s]+", "-", s)
    return s.strip("-")


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


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
