"""Shared category-classification helper for all Chamonix scrapers.

TIERED classification (2026-08-07):
  1. TITLE keywords win (precise, per-scraper maps).
  2. If the title yields 'other', fall back to LOW-NOISE DESCRIPTION phrases only —
     specific, low-collision phrases that clearly indicate an event's nature
     (e.g. "visite guidée", "randonnée", "sortie nature"). We deliberately do NOT
     match generic words from the description ("marche", "famille", "jeu", "sport")
     which appear incidentally and cause misclassification (e.g. a blood drive
     tagged "family" because its blurb mentions "famille").
  3. Still ambiguous -> stays 'other'.

Usage:
    from scripts.category_utils import LOW_NOISE_DESC_PHRASES, desc_fallback_category
    cat = classify_category(title)          # per-scraper, title-first
    if cat == "other":
        cat = desc_fallback_category(description)
"""

from __future__ import annotations

import re
from typing import Iterable

# Curated, low-collision description phrases -> category. Only fire when the
# TITLE gave no signal. Avoid generic nouns that occur incidentally.
LOW_NOISE_DESC_PHRASES: list[tuple[Iterable[str], str]] = [
    (["visite guidée", "visite guidee", "visite commentée", "visite commentee",
      "exposition", "expo temporaire", "musée", "musee", "galerie",
      "parcours d'art", "parcours d’art"], "exhibition"),
    (["randonnée", "randonnee", "sortie nature", "course à pied", "course a pied",
      "trail", "escalade", "tour de montagne", "trek"], "sport"),
    (["concert de", "live", "scène", "scene", "groupe de musique", "orchestre",
      "chorale", "chœur", "choeur", "concert"], "concert"),
    (["vide-grenier", "vide grenier", "braderie", "foire", "marché aux",
      "marche aux", "bourse aux"], "market"),
    (["spectacle pour enfants", "atelier enfant", "atelier enfants",
      "jeu de piste", "chasse au trésor", "chasse au tresor", "goûter", "gouter"], "family"),
    (["pièce de théâtre", "piece de theatre", "spectacle de théâtre",
      "spectacle de theatre", "one man show", "danse"], "theatre"),
]


def desc_fallback_category(description: str) -> str:
    """Categorize from a DESCRIPTION using only curated low-noise phrases.

    Returns a category, or 'other' if nothing low-noise matches. Case-insensitive.
    """
    if not description:
        return "other"
    t = re.sub(r"\s+", " ", description.lower())
    for phrases, cat in LOW_NOISE_DESC_PHRASES:
        for phrase in phrases:
            if phrase in t:
                return cat
    return "other"
