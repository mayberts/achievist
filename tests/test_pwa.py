"""
The install metadata for the phone app.

A broken manifest does not fail a build or throw in the console — the browser
just quietly stops offering "Install app", and nobody notices for weeks. So
the pieces that have to line up are asserted here: the manifest parses, every
icon it names exists, the HTML points at both the manifest and the iOS icon,
and the service worker keeps its hands off the API.
"""

import json
import mimetypes
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
PUBLIC = REPO / "frontend" / "public"
MANIFEST = PUBLIC / "manifest.webmanifest"
INDEX_HTML = REPO / "frontend" / "index.html"
SW = PUBLIC / "sw.js"


@pytest.fixture(scope="module")
def manifest() -> dict:
    return json.loads(MANIFEST.read_text())


def test_manifest_has_what_a_browser_requires_to_offer_install(manifest):
    assert manifest["name"]
    assert manifest["short_name"]
    assert manifest["start_url"] == "/"
    # Anything but standalone/fullscreen and Chrome treats it as a bookmark,
    # not an app: you get browser chrome and no home-screen entry.
    assert manifest["display"] in {"standalone", "fullscreen", "minimal-ui"}


def test_every_icon_the_manifest_names_actually_exists(manifest):
    for icon in manifest["icons"]:
        path = PUBLIC / icon["src"].lstrip("/")
        assert path.is_file(), f"{icon['src']} is in the manifest but not in frontend/public"


def test_icons_cover_both_the_plain_and_maskable_purposes(manifest):
    """Without a maskable icon, Android launchers that crop to a circle put
    the whole rounded-square tile inside another circle."""
    sizes = {(i["sizes"], i.get("purpose", "any")) for i in manifest["icons"]}
    assert ("192x192", "any") in sizes
    assert ("512x512", "any") in sizes
    assert ("512x512", "maskable") in sizes


def test_webmanifest_is_served_as_a_manifest_not_octet_stream():
    # Importing main registers the type; without it FileResponse guesses
    # octet-stream and the browser ignores the manifest.
    import app.main  # noqa: F401

    assert mimetypes.guess_type("manifest.webmanifest")[0] == "application/manifest+json"


def test_html_links_the_manifest_and_the_ios_icon():
    html = INDEX_HTML.read_text()
    assert 'rel="manifest"' in html
    # iOS ignores the manifest's icons entirely and uses this tag instead.
    assert 'rel="apple-touch-icon"' in html
    assert 'name="theme-color"' in html
    # Needed for the safe-area insets in index.css to have anything to inset.
    assert "viewport-fit=cover" in html


def test_service_worker_never_caches_the_api():
    """The API is one family member's private library behind a session
    cookie. A cached response could be served to whoever signs in next."""
    sw = SW.read_text()
    assert '"/api/"' in sw or "'/api/'" in sw
    assert "startsWith" in sw
