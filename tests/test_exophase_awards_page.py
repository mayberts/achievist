"""
Tests for app.platforms.exophase._AwardsPageParser / fetch_game_page_awards,
using a real HTML fragment captured from a live EA achievements page (via
the temporary /api/exophase-page-debug endpoint) — EA's tooltip attribute
contains unescaped inner HTML, which broke a naive regex-based scraper.
"""

import httpx
import pytest

from app.platforms import exophase as exophase_module

# Real fragment from https://www.exophase.com/game/battlefield-1-origin/achievements/
_REAL_FRAGMENT = """
<ul class="awards-list">
<li class="col-12 t1 award visible" data-type="" data-award-id="1" data-master="2097279" id="2097279" data-earned="1483045666" data-average="50.95" data-points="10">
	<div class="row align-items-center">
		<div class="col-auto award-left">
			<div class="box image hidden-toggle">
									<img data-tippy-content="<strong>Operations</strong> <p>Win 1 round of Operations in multiplayer</p>" class="award-image trophy-image visible" src="https://m.exophase.com/origin/awards/s/7ded638.png?1512fe2f5620d9c668081c8183195733" width="64" height="64" />
							</div>
		</div>

		<div class="col col-lg-4 col-xl-6 award-details snippet">
			<div class="text-medium award-title hidden-toggle fw-bolder">
								<a href="https://www.exophase.com/achievement/battlefield-1-origin/108-operations">Operations</a>
			</div>

			<div class="award-description hidden-toggle"><p>Win 1 round of Operations in multiplayer</p></div>
		</div>

				<div class="col-12 col-lg mt-3 mt-lg-0 award-points text-center">
							<span>10</span>
				<i class="me-0 mt-2 d-block exo-icon icon-collection-trophies exo-icon-origin-points"></i>
					</div>

		<div class="col-12 col-lg mt-3 mt-lg-0 award-average text-center">
			<span class="tippy" data-tippy-content="Uncommon (50.00 EXP)" style="display:inline">50.95% (50.00)</span>
		</div>

		<div class="col-12 col-lg award-earned text-center text-lg-end mt-3 mt-lg-0">
		</div>
	</div>

</li>
											<li class="col-12 locked t1 award visible" data-type="" data-award-id="2" data-master="2097260" id="2097260" data-earned="0" data-average="26.31" data-points="40">
	<div class="row align-items-center">
		<div class="col-auto award-left">
			<div class="box image hidden-toggle">
									<img data-tippy-content="<strong>Decorated</strong> <p>Reach Rank 1 with all 4 Infantry classes in multiplayer</p>" class="award-image trophy-image visible" src="https://m.exophase.com/origin/awards/s/7ded618.png?1512fe2f5620d9c668081c8183195733" width="64" height="64" />
							</div>
		</div>

		<div class="col col-lg-4 col-xl-6 award-details snippet">
			<div class="text-medium award-title hidden-toggle fw-bolder">
								<a href="https://www.exophase.com/achievement/battlefield-1-origin/95-decorated">Decorated</a>
			</div>

			<div class="award-description hidden-toggle"><p>Reach Rank 1 with all 4 Infantry classes in multiplayer</p></div>
		</div>
	</div>
</li>
</ul>
"""


def test_parser_handles_unescaped_html_in_tooltip():
    parser = exophase_module._AwardsPageParser()
    parser.feed(_REAL_FRAGMENT)
    assert len(parser.awards) == 2

    unlocked, locked = parser.awards
    assert unlocked["slug"] == "108-operations"
    assert unlocked["name"] == "Operations"
    assert unlocked["description"] == "Win 1 round of Operations in multiplayer"
    assert unlocked["icon"].endswith("7ded638.png?1512fe2f5620d9c668081c8183195733")
    assert unlocked["points"] == "10"
    assert unlocked["rarity_pct"] == "50.95"
    assert unlocked["locked"] is False

    assert locked["slug"] == "95-decorated"
    assert locked["name"] == "Decorated"
    assert locked["description"] == "Reach Rank 1 with all 4 Infantry classes in multiplayer"
    assert locked["locked"] is True


async def test_fetch_game_page_awards_end_to_end(monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text=_REAL_FRAGMENT)

    real_async_client = httpx.AsyncClient
    monkeypatch.setattr(
        httpx, "AsyncClient", lambda **kw: real_async_client(transport=httpx.MockTransport(handler), **kw)
    )
    awards = await exophase_module.fetch_game_page_awards("battlefield-1-origin")
    assert {a["slug"] for a in awards} == {"108-operations", "95-decorated"}


async def test_fetch_earned_does_not_collide_on_shared_slug(monkeypatch):
    """
    Real bug: EA has several distinct secret achievements all literally
    named/slugged "hidden-achievement" — keying the earned dict by "slug"
    silently overwrote all but one. Must key by the unique id-prefixed
    "endpoint" segment instead.
    """
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={
            "success": True,
            "master_gameid": "1",
            "list": [
                {"masterAwardId": 1, "slug": "hidden-achievement", "timestamp": 100,
                 "endpoint": "/achievement/some-game-origin/2840-hidden-achievement",
                 "icons": {"m": "/a.png"}},
                {"masterAwardId": 2, "slug": "hidden-achievement", "timestamp": 90,
                 "endpoint": "/achievement/some-game-origin/2844-hidden-achievement",
                 "icons": {"m": "/b.png"}},
            ],
        })

    real_async_client = httpx.AsyncClient
    monkeypatch.setattr(
        httpx, "AsyncClient", lambda **kw: real_async_client(transport=httpx.MockTransport(handler), **kw)
    )
    earned = await exophase_module.fetch_earned(999, 1)
    assert set(earned) == {"2840-hidden-achievement", "2844-hidden-achievement"}


def test_dedupe_awards_collapses_identical_name_and_description():
    """
    Real bug: EA sometimes lists the same achievement twice under different
    numeric ids (e.g. a per-platform copy) — same name/description, distinct
    slug — which showed as literal duplicate rows in the UI.
    """
    awards = [
        {"slug": "108-backseat-mechanic", "name": "Backseat Mechanic",
         "description": "You helped fix the bike.", "icon": "https://cdn/a.png",
         "points": "10", "rarity_pct": "83.42", "locked": False},
        {"slug": "230-backseat-mechanic", "name": "Backseat Mechanic",
         "description": "You helped fix the bike.", "icon": None,
         "points": "10", "rarity_pct": "83.42", "locked": True},
        {"slug": "109-in-sync", "name": "In Sync",
         "description": "Music was played in harmony.", "icon": "https://cdn/b.png",
         "points": "20", "rarity_pct": "28.21", "locked": False},
    ]
    deduped = exophase_module._dedupe_awards(awards)
    assert len(deduped) == 2

    bm = next(a for a in deduped if a["name"] == "Backseat Mechanic")
    assert bm["slug"] == "108-backseat-mechanic"  # first occurrence wins as canonical
    assert set(bm["alt_slugs"]) == {"108-backseat-mechanic", "230-backseat-mechanic"}
    assert bm["icon"] == "https://cdn/a.png"  # kept from whichever copy actually had one


@pytest.mark.parametrize("val,expected", [("10", 10), ("10.0", 10), (None, None), ("garbage", None)])
def test_to_int(val, expected):
    assert exophase_module._to_int(val) == expected


@pytest.mark.parametrize("val,expected", [("50.95", 50.95), (None, None), ("garbage", None)])
def test_to_float(val, expected):
    assert exophase_module._to_float(val) == expected
