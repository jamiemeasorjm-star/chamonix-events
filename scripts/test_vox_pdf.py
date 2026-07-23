#!/usr/bin/env python3
"""T39 regression tests for vox_pdf.py parser fix.

Bug fixed: multiple films sharing a date+time slot in the Summer film
festival / Little film festival sections of programme.pdf were being
concatenated into a single garbled cinema_events.json entry.

Run: cd /docker/hermes-agent-2bpx/data/chamonix-events && ./venv/bin/python3 scripts/test_vox_pdf.py
"""
from __future__ import annotations
import os
import re
import sys
import unittest

# Allow running directly from the project root
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

from scripts import vox_pdf


PDF_PATH = os.path.join(ROOT, "data", "programme.pdf")


class T39FestivalFilmTests(unittest.TestCase):
    """T39: ensure festival films are parsed as SEPARATE events, not merged."""

    @classmethod
    def setUpClass(cls):
        if not os.path.exists(PDF_PATH):
            raise unittest.SkipTest(f"PDF not found at {PDF_PATH}")
        cls.films, cls.day_dates, cls.sd, cls.ed = vox_pdf.parse_pdf(PDF_PATH)

    def _find_by_title(self, prefix):
        return [f for f in self.films if f["title"].startswith(prefix)]

    def test_no_merged_festival_entry(self):
        """The bug's smoking gun: a single entry containing all three festival
        films. Must not exist after the fix."""
        merged = [
            f for f in self.films
            if "NEW YORK" in f["title"] and "LES FILS" in f["title"]
        ]
        self.assertEqual(
            len(merged), 0,
            f"Festival films still merged into single entry: {[f['title'][:80] for f in merged]}",
        )

    def test_new_york_is_separate_event(self):
        new_york = self._find_by_title("NEW YORK 1997")
        self.assertEqual(
            len(new_york), 1,
            f"Expected exactly one NEW YORK 1997 entry, got {len(new_york)}",
        )
        entry = new_york[0]
        self.assertIn("NEW YORK 1997", entry["title"])
        self.assertNotIn("LES FILS", entry["title"])
        # Must have its own showtime at col 1 (Thursday 9 Jul, 20:30)
        self.assertIn("20:30", entry["showtimes"].get(1, []),
                      f"NEW YORK 1997 missing its 20:30 showtime: {entry['showtimes']}")

    def test_les_fils_is_separate_event(self):
        fils = self._find_by_title("LES FILS")
        self.assertEqual(
            len(fils), 1,
            f"Expected exactly one LES FILS entry, got {len(fils)}",
        )
        entry = fils[0]
        self.assertIn("LES FILS", entry["title"])
        self.assertNotIn("LE MONDE", entry["title"])
        self.assertNotIn("NEW YORK", entry["title"])
        # Must have its own showtime at col 5 (Tuesday 14 Jul, 20:30)
        self.assertIn("20:30", entry["showtimes"].get(5, []),
                      f"LES FILS missing its 20:30 showtime: {entry['showtimes']}")

    def test_le_monde_is_separate_event(self):
        monde = self._find_by_title("LE MONDE")
        self.assertEqual(
            len(monde), 1,
            f"Expected exactly one LE MONDE entry, got {len(monde)}",
        )
        entry = monde[0]
        self.assertIn("LE MONDE", entry["title"])
        self.assertNotIn("LES FILS", entry["title"])
        self.assertNotIn("NEW YORK", entry["title"])
        # LE MONDE A L'ENVERS has dur 0h45 in the PDF — must be preserved
        self.assertEqual(entry["duration"], "0h45",
                         f"LE MONDE missing its 0h45 duration: {entry['duration']!r}")
        # Must have its own showtimes
        all_shows = [t for ts in entry["showtimes"].values() for t in ts]
        self.assertTrue(len(all_shows) >= 2,
                        f"LE MONDE should have ≥2 showtimes, got {entry['showtimes']}")


class T39RegressionTests(unittest.TestCase):
    """T39: ensure the fix doesn't break previously-working cases."""

    @classmethod
    def setUpClass(cls):
        if not os.path.exists(PDF_PATH):
            raise unittest.SkipTest(f"PDF not found at {PDF_PATH}")
        cls.films, cls.day_dates, cls.sd, cls.ed = vox_pdf.parse_pdf(PDF_PATH)

    def _find_by_title(self, prefix):
        return [f for f in self.films if f["title"].startswith(prefix)]

    def test_normal_film_with_inline_showtime(self):
        """VAIANA has 'VAIANA 1H55 15H30 VF' on a single line."""
        v = self._find_by_title("VAIANA")
        self.assertEqual(len(v), 1)
        entry = v[0]
        self.assertEqual(entry["title"], "VAIANA")
        self.assertEqual(entry["duration"], "1h55")
        # VAIANA has many showtimes across multiple columns
        total = sum(len(ts) for ts in entry["showtimes"].values())
        self.assertGreaterEqual(total, 10,
                               f"VAIANA should have many showtimes, got {total}")

    def test_subtitle_pattern_combined_with_duration(self):
        """LA BATAILLE DE GAULLE—Part.2 + J'ÉCRIS TON NOM 2H40 — must be ONE entry
        with combined title and 2h40 duration. (No section marker between.)
        Part.1 + L'AGE DE FER is the same pattern (regression coverage)."""
        part2 = self._find_by_title("LA BATAILLE DE GAULLE—Part.2")
        self.assertEqual(len(part2), 1,
                         f"Expected one LA BATAILLE Part.2 entry, got {len(part2)}")
        self.assertIn("J\u2019\u00c9CRIS TON NOM", part2[0]["title"],
                      f"Sub-title lost from Part.2: {part2[0]['title']!r}")
        self.assertEqual(part2[0]["duration"], "2h40")

        part1 = self._find_by_title("LA BATAILLE DE GAULLE—Part.1")
        self.assertEqual(len(part1), 1,
                         f"Expected one LA BATAILLE Part.1 entry, got {len(part1)}")
        self.assertIn("L\u2019AGE DE FER", part1[0]["title"],
                      f"Sub-title lost from Part.1: {part1[0]['title']!r}")
        self.assertEqual(part1[0]["duration"], "2h39")

    def test_prefix_metadata_combined_with_title(self):
        """'int. —12 ans' standalone (prefix metadata) + DES MINIONS ET DES MONSTRES
        + 1H29 — must be ONE entry with combined title and 1h29 duration.
        (No section marker between.)"""
        d = [f for f in self.films if "DES MINIONS" in f["title"]]
        self.assertEqual(len(d), 1)
        entry = d[0]
        self.assertIn("int. —12 ans", entry["title"],
                      f"Prefix metadata lost: {entry['title']!r}")
        self.assertEqual(entry["duration"], "1h29")

    def test_section_marker_attaches_to_preceding_film(self):
        """'Little film festival' section marker attaches to LE MONDE
        (the preceding festival film), not to SUPERGIRL (the next)."""
        monde = self._find_by_title("LE MONDE")
        self.assertEqual(len(monde), 1)
        self.assertIn("Little film festival", monde[0]["title"])

        supergirl = self._find_by_title("SUPERGIRL")
        self.assertEqual(len(supergirl), 1)
        self.assertNotIn("Little film festival", supergirl[0]["title"],
                         f"Section marker leaked into SUPERGIRL: {supergirl[0]['title']!r}")


if __name__ == "__main__":
    unittest.main(verbosity=2)
