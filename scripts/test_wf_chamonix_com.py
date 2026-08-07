"""Unit tests for pure helpers in wf_chamonix_com.py (migration slice 1).

Covers the helpers that strip wf markdown boilerplate and extract the event
fields that fix the old empty-description bug.

Run (web-foundation venv; wf deps not needed for pure helpers):
    /docker/hermes-agent-2bpx/data/web-foundation/.venv/bin/python scripts/test_wf_chamonix_com.py
Also pytest-compatible (functions named test_*).
"""

from __future__ import annotations

from scripts import wf_chamonix_com as wf


SAMPLE_MD = """\
---
title: "UTMB Mont-Blanc"
url: https://www.chamonix.com/agenda/evenements-et-manifestations/utmb-mont-blanc-r
date: "2026-08-01"
---
# UTMB Mont-Blanc

L'UTMB est une    aventure humaine.   Une description   de test.

plus de texte ici.
"""


def test_strip_front_matter_removes_yaml_block():
    out = wf.strip_front_matter(SAMPLE_MD)
    assert not out.startswith("---")
    assert "# UTMB Mont-Blanc" in out


def test_strip_front_matter_no_front_matter():
    assert wf.strip_front_matter("just text") == "just text"
    assert wf.strip_front_matter("") == ""


def test_first_heading():
    assert wf.first_heading(SAMPLE_MD) == "UTMB Mont-Blanc"
    assert wf.first_heading("no heading") == ""
    assert wf.first_heading("") == ""


def test_extract_description_strips_boilerplate_and_collapses():
    desc = wf.extract_description(SAMPLE_MD)
    assert not desc.startswith("---")
    assert "UTMB est" in desc.replace("\n\n", " "), desc
    # runs of whitespace collapsed
    assert "   " not in desc.replace("\n\n", " ")


def test_extract_description_empty():
    assert wf.extract_description("") == ""


def test_detect_commune():
    assert wf.detect_commune("74400 Chamonix-Mont-Blanc") == "Chamonix"
    assert wf.detect_commune("Argentière") == "Argentiere"
    assert wf.detect_commune("Les Houches") == "Les Houches"
    assert wf.detect_commune("Servoz") == "Servoz"
    assert wf.detect_commune("inconnu") == "Chamonix"


def test_extract_address_line():
    assert wf.extract_address_line("Foo\n74400 Chamonix-Mont-Blanc") == "74400 Chamonix-Mont-Blanc"
    assert wf.extract_address_line("rien") == ""


def test_parse_event_time():
    assert wf.parse_event_time("20h30 - 22h") == "20:30"
    assert wf.parse_event_time("9h - 17h") == "09:00"
    assert wf.parse_event_time("de 10h30") == "10:30"
    assert wf.parse_event_time("aucune heure") == ""


def test_parse_french_dates_range_same_month():
    st, en = wf.parse_french_dates("Du mercredi 12 au dimanche 16 août 2026.")
    assert st == "2026-08-12"
    assert en == "2026-08-16"


def test_parse_french_dates_single_day():
    st, en = wf.parse_french_dates("Le samedi 16 août 2026.")
    assert st == "2026-08-16"
    assert en == "2026-08-16"


def test_parse_french_dates_cross_month():
    st, en = wf.parse_french_dates(
        "Du vendredi 30 janvier 2026 au dimanche 1 février 2026")
    assert st == "2026-01-30"
    assert en == "2026-02-01"


def test_parse_french_dates_no_match():
    assert wf.parse_french_dates("pas de date") == ("", "")


def test_classify_category():
    assert wf.classify_category("Concert Dub Inc") == "concert"
    assert wf.classify_category("UTMB trail running") == "sport"
    assert wf.classify_category("Brocante vintage") == "market"
    assert wf.classify_category("Exposition photos") == "exhibition"
    assert wf.classify_category("Truc inconnu") == "other"


if __name__ == "__main__":
    fns = [
        (name, obj) for name, obj in sorted(globals().items())
        if name.startswith("test_") and callable(obj)
    ]
    for name, fn in fns:
        fn()
        print(f"  ok  {name}")
    print(f"\n{len(fns)} tests passed")
