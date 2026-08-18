"""
Layout smoke tests in a real browser.

Deliberately narrow. These do not re-check anything the Vitest component
tests already cover — they check what jsdom physically cannot know, because
it has no layout engine: whether text wrapped, and whether things fit. The
"Sync all" button silently wrapping onto two lines when a nav tab was added
is the case that motivated all of this.

Each test costs a browser launch, so the viewport sweeps loop inside one
test rather than being parametrized into many.
"""

# The widths that matter: the narrowest desktop layout, the width where the
# wrapping regression showed up, and a roomy one.
VIEWPORTS = [(1024, 900), (1280, 900), (1600, 900)]

# Counts the lines an element's text is laid out across. A Range over a text
# node returns one client rect per line box, so a wrapped label reports more
# than one — precisely the signal jsdom cannot give us.
LINE_COUNT_JS = """
(el) => {
  const walker = document.createTreeWalker(el, NodeFilter.SHOW_TEXT);
  let lines = 0;
  while (walker.nextNode()) {
    const node = walker.currentNode;
    if (!node.textContent.trim()) continue;
    const range = document.createRange();
    range.selectNodeContents(node);
    lines = Math.max(lines, range.getClientRects().length);
  }
  return lines;
}
"""


async def _lines(locator) -> int:
    return await locator.evaluate(LINE_COUNT_JS)


async def _settle(page, width: int, height: int) -> None:
    await page.set_viewport_size({"width": width, "height": height})
    await page.wait_for_timeout(250)


async def test_app_loads_and_lands_on_home(page):
    active = await page.locator("nav button.border-accent\\/40").first.inner_text()
    assert active.strip() == "Home"
    # the page rendered real content, not a spinner or a blank div
    assert await page.locator("text=Quick wins").count() > 0
    assert await page.locator("text=Chase list").count() > 0


async def test_page_never_scrolls_sideways(page):
    """A page wider than its own viewport is the most visible layout failure
    there is, and the one jsdom is least able to notice."""
    for width, height in VIEWPORTS:
        await _settle(page, width, height)
        overflow = await page.evaluate(
            "() => document.documentElement.scrollWidth - document.documentElement.clientWidth"
        )
        # a pixel of slack for sub-pixel rounding
        assert overflow <= 1, f"page overflows its viewport by {overflow}px at {width}px wide"


async def test_header_labels_stay_on_one_line(page):
    """The regression this file exists for: adding a nav tab squeezed the
    header until 'Sync all' wrapped in half."""
    for width, height in VIEWPORTS:
        await _settle(page, width, height)

        button = page.get_by_role("button", name="Sync all")
        assert await _lines(button) == 1, f"'Sync all' wrapped at {width}px wide"

        tabs = page.locator("nav button")
        count = await tabs.count()
        assert count >= 7, f"expected the full tab bar, found {count} tabs at {width}px"
        for i in range(count):
            tab = tabs.nth(i)
            label = (await tab.inner_text()).strip()
            assert await _lines(tab) == 1, f"nav tab '{label}' wrapped at {width}px wide"


async def test_search_palette_opens_on_ctrl_k_and_finds_a_real_game(page):
    """The unit tests drive a mocked api. This is the one check that the
    shortcut, the live endpoints and the rendering line up in a browser."""
    await page.keyboard.press("Control+k")
    dialog = page.locator("[role=dialog]")
    await dialog.wait_for(state="visible", timeout=5000)

    # No command glyph anywhere: this is a Windows household.
    assert "⌘" not in await dialog.inner_text()

    await page.locator("[role=dialog] input").fill("Finished")
    await page.locator("[role=option]").first.wait_for(timeout=5000)
    assert "A Finished Game" in await dialog.inner_text()

    await page.keyboard.press("Enter")
    await page.wait_for_url("**/games/**", timeout=5000)


async def test_home_panels_render_with_real_size(page):
    """A collapsed or zero-height card looks fine to jsdom and broken in a
    browser, so assert each panel actually occupies space."""
    for name in ["Quick wins", "Chase list", "Achievement milestones"]:
        panel = page.locator(f"text={name}").first
        assert await panel.is_visible(), f"{name} is not visible"
        box = await panel.bounding_box()
        assert box and box["height"] > 0 and box["width"] > 0, f"{name} has no rendered size"

    # the milestone cards pack a number, a unit, a tier badge and sometimes a
    # "New" pill onto one row; that row overflowing is invisible to jsdom
    card = page.locator("text=ACHIEVEMENT MILESTONES").locator(
        "xpath=ancestor::div[contains(@class,'rounded-card')][1]"
    )
    overflow = await card.evaluate("(el) => el.scrollWidth - el.clientWidth")
    assert overflow <= 1, f"milestone card content overflows its card by {overflow}px"
