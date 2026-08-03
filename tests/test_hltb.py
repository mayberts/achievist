"""
Tests for app/hltb.py's name cleanup — strips noise that store listings
(Xbox in particular) add but HowLongToBeat's own catalog doesn't use, without
touching edition words that can denote a genuinely distinct HLTB entry.
"""

import pytest

from app.hltb import clean_name


@pytest.mark.parametrize("raw,expected", [
    ("Call of Duty®: Modern Warfare® III", "Call of Duty: Modern Warfare III"),
    (
        "Call of Duty®: Modern Warfare® - Digital Standard Edition (Windows)",
        "Call of Duty: Modern Warfare",
    ),
    ("Call of Duty®: Vanguard - Standard Edition", "Call of Duty: Vanguard"),
    ("Halo 5: Guardians", "Halo 5: Guardians"),
    ("Halo: The Master Chief Collection", "Halo: The Master Chief Collection"),
    ("Some Game (Xbox One)", "Some Game"),
    ("Some Game (PC)", "Some Game"),
])
def test_clean_name(raw, expected):
    assert clean_name(raw) == expected


@pytest.mark.parametrize("raw", [
    "Borderlands GOTY Enhanced",
    "BioShock Remastered",
    "Some Game Deluxe Edition",
])
def test_clean_name_leaves_edition_words_that_may_denote_a_distinct_release(raw):
    # These aren't store-listing noise — HLTB may track them as their own
    # entries, so stripping them could match the wrong game entirely.
    assert clean_name(raw) == raw
