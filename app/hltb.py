"""
HowLongToBeat name cleanup.

Store listings (Xbox in particular) often carry trademark symbols, a
platform tag, and an edition suffix that HowLongToBeat's own catalog doesn't
use — e.g. "Call of Duty®: Vanguard - Standard Edition" or "Call of Duty®:
Modern Warfare® - Digital Standard Edition (Windows)". Left as-is, the
library's fuzzy search either finds nothing or a low-confidence match.
Stripping the noise (but not edition words like "Remastered"/"GOTY"/"Deluxe"
that can denote a genuinely distinct release HLTB tracks separately) gives
the search a much closer shot at the real title.
"""

import re

_TRADEMARK_RE = re.compile(r"[®™©]")

_PLATFORM_TAG_RE = re.compile(
    r"\s*\((?:Windows|PC|Xbox(?: One| Series X\|S| 360)?|PS[345]?|PlayStation(?: \d)?)\)\s*$",
    re.IGNORECASE,
)

_STANDARD_EDITION_RE = re.compile(
    r"\s*-\s*(?:Digital )?Standard Edition\s*$",
    re.IGNORECASE,
)


def clean_name(name: str) -> str:
    name = _TRADEMARK_RE.sub("", name)
    name = _PLATFORM_TAG_RE.sub("", name)
    name = _STANDARD_EDITION_RE.sub("", name)
    return name.strip()
