#!/usr/bin/env python3
"""Remove events whose end_date (or start_date) is before today."""
import json
import sys
from datetime import date

path = sys.argv[1] if len(sys.argv) > 1 else 'data/events.json'
today = date.today().isoformat()

with open(path) as f:
    events = json.load(f)

before = len(events)
events = [e for e in events if (e.get('end_date') or e.get('start_date') or '')[:10] >= today]

with open(path, 'w') as f:
    json.dump(events, f, indent=2, ensure_ascii=False)

removed = before - len(events)
if removed:
    print(f'Purged {removed} past events, {len(events)} remaining')
else:
    print(f'No past events to remove ({len(events)} events)')
