"""Unit tests for the pure token/parsing helpers in the platform auth modules.

These deliberately avoid the database and network — they cover the small
parsing functions that have caused real bugs before (e.g. the Ubisoft
session-id extraction, Epic's date parsing) so a future refactor can't
silently break them.
"""

import base64
import json

from app.psn_auth import _extract_query_param
from app.ubisoft_auth import _sid_from_ticket
from app.platforms.epic import _cover, _parse_date


def test_extract_query_param_finds_code():
    url = "com.scee.psxandroid.scecompcall://redirect?code=abc123&state=xyz"
    assert _extract_query_param(url, "code") == "abc123"


def test_extract_query_param_missing_key_returns_none():
    url = "https://example.com/redirect?foo=bar"
    assert _extract_query_param(url, "code") is None


def test_sid_from_ticket_decodes_jwe_header():
    header = {"typ": "JWE", "sid": "bf0a483f-abd2-4f68-a2ac-c7ce9f2b3471"}
    header_b64 = base64.urlsafe_b64encode(json.dumps(header).encode()).decode().rstrip("=")
    ticket = f"{header_b64}.payload.signature"
    assert _sid_from_ticket(ticket) == "bf0a483f-abd2-4f68-a2ac-c7ce9f2b3471"


def test_sid_from_ticket_garbage_input_returns_empty_string():
    assert _sid_from_ticket("not-a-real-ticket") == ""
    assert _sid_from_ticket("") == ""


def test_epic_cover_prefers_wide_then_tall_then_thumbnail():
    images = [
        {"type": "Thumbnail", "url": "thumb.jpg"},
        {"type": "OfferImageTall", "url": "tall.jpg"},
        {"type": "OfferImageWide", "url": "wide.jpg"},
    ]
    assert _cover(images) == "wide.jpg"
    assert _cover([{"type": "OfferImageTall", "url": "tall.jpg"}]) == "tall.jpg"
    assert _cover([{"type": "Thumbnail", "url": "thumb.jpg"}]) == "thumb.jpg"


def test_epic_cover_handles_missing_or_malformed_images():
    assert _cover([]) is None
    assert _cover(None) is None  # type: ignore[arg-type]


def test_epic_parse_date_handles_valid_and_sentinel_values():
    dt = _parse_date("2026-07-31T20:19:12.504376Z")
    assert dt is not None
    assert dt.year == 2026 and dt.month == 7 and dt.day == 31

    assert _parse_date("N/A") is None
    assert _parse_date(None) is None
    assert _parse_date("") is None
    assert _parse_date("not-a-date") is None
