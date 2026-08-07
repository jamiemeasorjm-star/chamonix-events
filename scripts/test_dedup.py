"""Unit tests for cross-source dedup (CROSS_SOURCE_DEDUP_SPEC).

Covers the concrete duplicate pairs observed in the live DB (2026-08-07):

1. Unidivers appends "<VENUE> <LOCALITY>" to the event title.
2. HTML entities not decoded (unidivers "d&rsquo;orgue" vs "d'orgue").
3. Minor word/order variants ("Visite guidée" vs "Visite guidées").
4. No over-merging (e.g. two distinct "Sortie nature X/Y").

Run with:
    ./venv/bin/python3.11 -m pytest scripts/test_dedup.py -q
or directly:
    ./venv/bin/python3.11 scripts/test_dedup.py
"""
from __future__ import annotations

from scripts.dedup import normalize_title
from scripts.dedup import dedupe_events


def _ev(title, date, source="chamonix_fr", confidence=1.0, venue=None):
    e = {
        "title": title,
        "start_date": date,
        "source_id": source,
        "confidence": confidence,
    }
    if venue is not None:
        e["venue_name"] = venue
    return e


def test_normalize_html_entities():
    assert normalize_title("Festival d&rsquo;orgue") == normalize_title("Festival d'orgue")
    assert normalize_title("A &amp; B") == normalize_title("A & B")


def test_prefix_merge_journees():
    a = _ev("58e Journées Minéralogiques", "2026-08-08")
    b = _ev("58e Journées Minéralogiques Le Majestic Centre des Cong...",
            "2026-08-08", source="unidivers", confidence=0.9)
    out = dedupe_events([a, b])
    assert len(out) == 1
    assert out[0]["source_id"] == "chamonix_fr"  # official preferred


def test_prefix_merge_fete_des_guides():
    a = _ev("Fête des Guides aux Gaillands", "2026-08-10")
    b = _ev("Fête des Guides aux Gaillands Site des Gaillands Chamonix-...",
            "2026-08-10", source="unidivers", confidence=0.9)
    assert len(dedupe_events([a, b])) == 1


def test_prefix_merge_hockey():
    a = _ev("Match de Hockey sur Glace Chamonix Vs Grenoble", "2026-08-12")
    b = _ev("Match de Hockey sur Glace Chamonix Vs Grenoble Patinoire...",
            "2026-08-12", source="unidivers", confidence=0.9)
    assert len(dedupe_events([a, b])) == 1


def test_prefix_merge_soiree_indienne():
    a = _ev("Soirée Indienne", "2026-08-14")
    b = _ev("Soirée Indienne Temple Protestant Chamonix-Mont-Blanc",
            "2026-08-14", source="unidivers", confidence=0.9)
    assert len(dedupe_events([a, b])) == 1


def test_html_entity_festival_orgue():
    a = _ev("Festival d'orgue de la vallée de Chamonix", "2026-08-09")
    b = _ev("Festival d&rsquo;orgue de la vallée de Chamonix",
            "2026-08-09", source="unidivers", confidence=0.9)
    assert len(dedupe_events([a, b])) == 1


def test_minor_singular_plural_variant():
    a = _ev("Visite guidée de la mer de Glace", "2026-08-15")
    b = _ev("Visite guidées de la mer de Glace", "2026-08-15", source="unidivers")
    assert len(dedupe_events([a, b])) == 1


def test_no_overmerge_sortie_nature():
    a = _ev("Sortie nature observation des chamois", "2026-08-20")
    b = _ev("Sortie nature découverte des marmottes", "2026-08-20", source="unidivers")
    assert len(dedupe_events([a, b])) == 2


def test_identical_title_still_merges():
    a = _ev("Arc'teryx Alpine Academy", "2026-07-02")
    b = _ev("Arc'teryx Alpine Academy", "2026-07-02", source="unidivers")
    assert len(dedupe_events([a, b])) == 1


def test_same_name_different_date_stays():
    a = _ev("Marché paysan", "2026-08-02")
    b = _ev("Marché paysan", "2026-08-30", source="unidivers")
    assert len(dedupe_events([a, b])) == 2


if __name__ == "__main__":
    fns = [
        (name, obj) for name, obj in sorted(globals().items())
        if name.startswith("test_") and callable(obj)
    ]
    for name, fn in fns:
        fn()
        print(f"  ok  {name}")
    print(f"\n{len(fns)} tests passed")
