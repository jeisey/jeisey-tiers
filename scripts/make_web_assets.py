"""Derive the served fonts and logo from their committed sources (ADR-098).

The site's shell was 145 kB of script, 72 kB of fonts and a 75 kB logo on every cold visit.
Two of the three were larger than anything a reader's screen can show:

* **Fonts.** The vendored Google subsets carry a weight axis of 100-900 (Exo 2) and 400-800
  (JetBrains Mono) and about 230 code points each. The stylesheet declares ``font-weight:
  400 700`` for both, so a browser never renders outside 400-700, and the page prints the
  ASCII range plus sixteen typographic characters. Each family is therefore served as a
  **core** file (those characters, the axis clamped to the declared range) and a **rest**
  file (every other character the original latin file held, same clamp), each behind its
  own ``unicode-range``: a page that prints only core characters never downloads the rest,
  and a page that prints one gets the same family's own glyph, never a fallback. The
  latin-ext files are served unchanged, as before.
* **Logo.** The artwork is 434x145 and is drawn 48 CSS pixels tall (42 on a phone). It is
  served as a 2x (96 px) and a 3x (145 px) palette PNG through ``srcset``; the browser takes
  the one its screen needs.

Nothing here changes a glyph's outline inside the declared range, a character's font, or the
artwork: it removes what the page cannot show. The sources stay committed beside the outputs,
so the derivation can be re-run and diffed.

Usage (the tools are not project dependencies; ``uv`` provides them for the one run)::

    uv run --no-project --with pillow==11.3.0 --with fonttools==4.59.0 --with brotli==1.1.0 \\
        python scripts/make_web_assets.py
"""

from __future__ import annotations

import io
from pathlib import Path

from fontTools import subset
from fontTools.ttLib import TTFont
from fontTools.varLib import instancer
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
FONTS = ROOT / "web" / "src" / "assets" / "fonts"
ASSETS = ROOT / "web" / "src" / "assets"

#: Every character the interface prints: ASCII, the no-break space and BOM, and the sixteen
#: typographic characters the components use (``·`` ``×`` ``±`` ``–`` ``—`` ``‘’“”`` ``…``
#: ``‹›`` ``↑↓`` ``−``). Player names on the 2026 board are ASCII; a name that is not simply
#: loads the rest file.
CORE = sorted(
    {
        *range(0x20, 0x7F),
        0xA0,
        0xB1,
        0xB7,
        0xD7,
        0x2013,
        0x2014,
        0x2018,
        0x2019,
        0x201C,
        0x201D,
        0x2026,
        0x2039,
        0x203A,
        0x2191,
        0x2193,
        0x2212,
        0xFEFF,
    },
)

#: The weight range the stylesheet declares for both families.
WEIGHTS = (400, 700)

FAMILIES = {"exo2": "exo2-latin.woff2", "jetbrains-mono": "jetbrains-mono-latin.woff2"}


def _subset(source: Path, unicodes: list[int]) -> bytes:
    font = TTFont(source)
    options = subset.Options()
    options.layout_features = ["*"]
    options.name_IDs = ["*"]
    options.name_languages = ["*"]
    options.notdef_outline = True
    options.glyph_names = False
    subsetter = subset.Subsetter(options)
    subsetter.populate(unicodes=unicodes)
    subsetter.subset(font)
    font = instancer.instantiateVariableFont(font, {"wght": WEIGHTS})
    font.flavor = "woff2"
    buffer = io.BytesIO()
    font.save(buffer)
    return buffer.getvalue()


def _ranges(codepoints: list[int]) -> str:
    """``U+0020-007E, U+00A0`` — a CSS unicode-range for a sorted code-point list."""
    parts: list[str] = []
    start = previous = codepoints[0]
    for point in [*codepoints[1:], None]:
        if point is not None and point == previous + 1:
            previous = point
            continue
        parts.append(f"U+{start:04X}" if start == previous else f"U+{start:04X}-{previous:04X}")
        if point is not None:
            start = previous = point
    return ", ".join(parts)


def make_fonts() -> None:
    for family, filename in FAMILIES.items():
        source = FONTS / filename
        mapped = sorted(TTFont(source).getBestCmap())
        core = [point for point in CORE if point in mapped]
        rest = [point for point in mapped if point not in CORE]
        (FONTS / f"{family}-core.woff2").write_bytes(_subset(source, core))
        (FONTS / f"{family}-latin-rest.woff2").write_bytes(_subset(source, rest))
        print(f"{family}: core unicode-range {_ranges(core)}")
        print(f"{family}: rest unicode-range {_ranges(rest)}")


def make_logo() -> None:
    source = Image.open(ASSETS / "jt_logo.png").convert("RGBA")
    width, height = source.size
    for target in (96, 145):
        image = (
            source
            if target == height
            else source.resize((round(width * target / height), target), Image.Resampling.LANCZOS)
        )
        paletted = image.quantize(
            colors=256,
            method=Image.Quantize.FASTOCTREE,
            dither=Image.Dither.FLOYDSTEINBERG,
        )
        paletted.save(ASSETS / f"jt_logo-{target}.png", optimize=True)
        print(f"logo {target}px: {image.size}")


if __name__ == "__main__":
    make_fonts()
    make_logo()
