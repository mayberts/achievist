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
    assert unlocked["slug"] == "operations"
    assert unlocked["name"] == "Operations"
    assert unlocked["description"] == "Win 1 round of Operations in multiplayer"
    assert unlocked["icon"].endswith("7ded638.png?1512fe2f5620d9c668081c8183195733")
    assert unlocked["points"] == "10"
    assert unlocked["rarity_pct"] == "50.95"
    assert unlocked["locked"] is False

    assert locked["slug"] == "decorated"
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
    assert {a["slug"] for a in awards} == {"operations", "decorated"}


@pytest.mark.parametrize("val,expected", [("10", 10), ("10.0", 10), (None, None), ("garbage", None)])
def test_to_int(val, expected):
    assert exophase_module._to_int(val) == expected


@pytest.mark.parametrize("val,expected", [("50.95", 50.95), (None, None), ("garbage", None)])
def test_to_float(val, expected):
    assert exophase_module._to_float(val) == expected
