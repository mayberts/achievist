"""
Generate the PWA icon set.

Committed as PNGs so neither the build nor CI needs an image library; this
script exists so the icons can be regenerated identically if the palette
changes rather than being mystery binaries nobody can reproduce.

    pip install pillow && python scripts/make_icons.py

The trophy is drawn to match the lucide "trophy" glyph already used as the
favicon and in the header, so the installed app's icon matches the app.
"""

from pathlib import Path

from PIL import Image, ImageDraw

OUT = Path(__file__).resolve().parent.parent / "frontend" / "public"

BG = (10, 13, 20, 255)        # ink-950
ACCENT = (91, 140, 255, 255)  # accent.DEFAULT

# Drawn oversampled and downscaled, because Pillow has no anti-aliasing of
# its own — a 512px trophy drawn directly has visibly ragged edges.
SUPERSAMPLE = 4


def draw_trophy(size: int, *, maskable: bool) -> Image.Image:
    s = size * SUPERSAMPLE
    img = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)

    # A maskable icon may be cropped to a circle by the launcher, so its art
    # must sit inside the middle 80%. The plain icon can use more of the tile.
    d.rounded_rectangle([0, 0, s - 1, s - 1], radius=int(s * 0.18), fill=BG)

    # A maskable icon may be cropped to a circle by the launcher, so its art
    # must sit inside the middle 80%. The plain icon can use more of the tile.
    w = s * (0.46 if maskable else 0.56)
    cx, cy = s / 2, s / 2 + (w * 0.02)

    # A solid silhouette rather than an outline: a thin stroke turns to mush
    # once the launcher scales this down to ~48px on a home screen.
    cup_top = cy - w * 0.62
    shoulder = cy - w * 0.04           # where the straight sides give way
    bowl_r = w / 2
    left, right = cx - w / 2, cx + w / 2

    # handles first, so the cup overlaps their inner ends
    hw = max(2, int(w * 0.10))          # handle thickness
    hr = w * 0.30
    hy = cup_top + w * 0.30
    d.arc([left - hr, hy - hr, left + hr * 0.55, hy + hr], 90, 265, fill=ACCENT, width=hw)
    d.arc([right - hr * 0.55, hy - hr, right + hr, hy + hr], 275, 90, fill=ACCENT, width=hw)

    # cup: straight sides into a rounded bowl
    d.rectangle([left, cup_top, right, shoulder], fill=ACCENT)
    d.pieslice([left, shoulder - bowl_r, right, shoulder + bowl_r], 0, 180, fill=ACCENT)

    # stem
    stem_w = w * 0.14
    stem_top = shoulder + bowl_r - w * 0.02
    base_y = cy + w * 0.60
    d.rectangle([cx - stem_w / 2, stem_top, cx + stem_w / 2, base_y], fill=ACCENT)

    # base: a foot and a plinth, which is what reads as "trophy" at small sizes
    foot_h = w * 0.09
    d.rounded_rectangle(
        [cx - w * 0.24, base_y - foot_h, cx + w * 0.24, base_y],
        radius=foot_h / 2, fill=ACCENT,
    )
    d.rounded_rectangle(
        [cx - w * 0.40, base_y + w * 0.06, cx + w * 0.40, base_y + w * 0.06 + foot_h * 1.5],
        radius=foot_h * 0.6, fill=ACCENT,
    )

    return img.resize((size, size), Image.LANCZOS)


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    for size in (192, 512):
        draw_trophy(size, maskable=False).save(OUT / f"icon-{size}.png")
        draw_trophy(size, maskable=True).save(OUT / f"icon-{size}-maskable.png")
    # iOS ignores the manifest icons and uses this one.
    draw_trophy(180, maskable=False).save(OUT / "apple-touch-icon.png")
    print(f"wrote icons to {OUT}")


if __name__ == "__main__":
    main()
