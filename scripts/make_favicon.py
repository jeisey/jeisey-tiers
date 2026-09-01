"""Generate the site favicon from the owner's logo artwork.

`web/src/assets/jt_logo.png` is a chrome-blue "Jeisey tiers" wordmark with a football
flying over it. A wordmark 434px wide is illegible in a 16px browser tab, so the favicon
takes the logo's *football* and its *palette* rather than shrinking its text — the same
visual identity, at a size a tab can render.

Every colour below is sampled from the logo itself (run with ``--sample`` to reprint the
counts): deep navy shadows around ``#001030``, a mid chrome blue around ``#00A0F0`` and
near-white highlights around ``#E0F0F0``, over the heavy black outline the artwork uses.

The shape is an implicit prolate-spheroid silhouette,
``(u/A)^2 + (|v|/B)^(1/p) = 1``, rotated to the tilt the logo draws the ball at. ``p > 0.5``
draws the width down faster near the ends and pinches them into a football's points; at
``p = 0.5`` the shape is exactly an ellipse and reads as an egg in a 16px tab. Everything
is rendered supersampled and box-filtered down, because a favicon is judged entirely on
its edges.

Outputs, all written into ``web/public/`` and all committed:

* ``favicon.ico``  — 16/32/48, the file a browser asks for by name
* ``favicon.png``  — 48px, transparent, for the explicit ``<link rel="icon">``
* ``apple-touch-icon.png`` — 180px on the app's own dark ground, because iOS composites
  a transparent touch icon onto black and squares off the corners itself

Usage::

    uv run python scripts/make_favicon.py            # write the assets
    uv run python scripts/make_favicon.py --check    # fail if the committed bytes differ
    uv run python scripts/make_favicon.py --sample   # reprint the palette evidence
"""

from __future__ import annotations

import argparse
import math
import struct
import sys
import zlib
from collections import Counter
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
LOGO = REPO_ROOT / "web" / "src" / "assets" / "jt_logo.png"
PUBLIC = REPO_ROOT / "web" / "public"

# The app's own ground, matching `<meta name="theme-color">` in web/index.html.
APPLE_BACKGROUND = (5, 11, 20)

Rgb = tuple[int, int, int]

# The chrome sweep, top edge to bottom edge of the ball, in the logo's own hues.
# A tab bar may be white or near-black, so the sweep bottoms out at a mid blue rather than
# at the logo's navy: a ball that fades to #021435 loses its lower silhouette on a dark tab.
CHROME: tuple[tuple[float, Rgb], ...] = (
    (-1.00, (0x8F, 0xD8, 0xFF)),
    (-0.70, (0xF0, 0xFB, 0xFF)),
    (-0.34, (0xA8, 0xDE, 0xFF)),
    (0.02, (0x2E, 0x9F, 0xE8)),
    (0.45, (0x12, 0x63, 0xB8)),
    (1.00, (0x0B, 0x40, 0x86)),
)
LACE = (0xF2, 0xFB, 0xFF)
OUTLINE = (0x02, 0x08, 0x14)

TILT_DEGREES = -24.0
HALF_LENGTH = 0.472  # A, as a fraction of the canvas
HALF_WIDTH = 0.296  # B, as a fraction of the canvas
POINT = 0.66  # p; above 0.5 the ends come to a football's points
STROKE = 0.048  # dark outline, as a fraction of the canvas
RIM = 0.034  # bright inner rim along the lit edge


def _ramp(position: float) -> Rgb:
    """The chrome sweep sampled at ``position`` in [-1, 1], linearly interpolated."""
    stops = CHROME
    if position <= stops[0][0]:
        return stops[0][1]
    if position >= stops[-1][0]:
        return stops[-1][1]
    for (p0, c0), (p1, c1) in zip(stops, stops[1:], strict=False):
        if p0 <= position <= p1:
            t = (position - p0) / (p1 - p0)
            return (
                round(c0[0] + (c1[0] - c0[0]) * t),
                round(c0[1] + (c1[1] - c0[1]) * t),
                round(c0[2] + (c1[2] - c0[2]) * t),
            )
    return stops[-1][1]


def _shape(ux: float, vy: float) -> tuple[float, float]:
    """Signed distance to the football outline, and the normalised across-ball coordinate.

    ``F = (u/A)^2 + (|v|/B)^(1/p) - 1`` is zero on the silhouette; dividing by ``|grad F|``
    turns it into a distance good enough for a 3px stroke, including at the points where a
    naive normalised radius would collapse.
    """
    a, b, p = HALF_LENGTH, HALF_WIDTH, POINT
    av = abs(vy)
    ratio = av / b
    exponent = 1.0 / p
    f = (ux / a) ** 2 + ratio**exponent - 1.0
    d_du = 2.0 * ux / (a * a)
    if av < 1e-9:
        d_dv = 0.0
    else:
        d_dv = (exponent * ratio ** (exponent - 1.0)) / b * (1.0 if vy >= 0 else -1.0)
    grad = math.hypot(d_du, d_dv)
    distance = f / grad if grad > 1e-9 else f
    return distance, max(-1.0, min(1.0, vy / b))


def _laces(ux: float, vy: float) -> bool:
    """The four crossbars and their spine, on the ball's visible face."""
    a, b = HALF_LENGTH, HALF_WIDTH
    centre = -0.04 * b
    if abs(ux) < 0.30 * a and abs(vy - centre) < 0.060 * b:
        return True
    for offset in (-0.225, -0.075, 0.075, 0.225):
        if abs(ux - offset * a) < 0.042 * a and abs(vy - centre) < 0.26 * b:
            return True
    return False


def _render(size: int, supersample: int, background: Rgb | None) -> bytearray:
    """One RGBA canvas, box-filtered down from ``supersample``x."""
    theta = math.radians(TILT_DEGREES)
    cos_t, sin_t = math.cos(theta), math.sin(theta)
    hi = size * supersample
    px = bytearray(size * size * 4)
    inv = 1.0 / hi
    samples = supersample * supersample

    for y in range(size):
        for x in range(size):
            acc_r = acc_g = acc_b = acc_a = 0.0
            for sy in range(supersample):
                fy = ((y * supersample + sy) + 0.5) * inv - 0.5
                for sx in range(supersample):
                    fx = ((x * supersample + sx) + 0.5) * inv - 0.5
                    ux = fx * cos_t - fy * sin_t
                    vy = fx * sin_t + fy * cos_t
                    distance, across = _shape(ux, vy)
                    if distance > 0.0:
                        continue
                    if distance > -STROKE:
                        r, g, b = OUTLINE
                    elif _laces(ux, vy):
                        r, g, b = LACE
                    else:
                        r, g, b = _ramp(across)
                        if distance > -(STROKE + RIM) and across < 0.25:
                            r, g, b = 0xE8, 0xF8, 0xFF
                    acc_r += r
                    acc_g += g
                    acc_b += b
                    acc_a += 255.0
            i = (y * size + x) * 4
            if acc_a <= 0.0:
                if background is not None:
                    px[i], px[i + 1], px[i + 2], px[i + 3] = *background, 255
                continue
            alpha = acc_a / samples
            cov = acc_a / 255.0
            r, g, b = acc_r / cov, acc_g / cov, acc_b / cov
            if background is not None:
                w = alpha / 255.0
                r = r * w + background[0] * (1 - w)
                g = g * w + background[1] * (1 - w)
                b = b * w + background[2] * (1 - w)
                alpha = 255.0
            px[i] = round(r)
            px[i + 1] = round(g)
            px[i + 2] = round(b)
            px[i + 3] = round(alpha)
    return px


def _png_bytes(size: int, px: bytearray) -> bytes:
    raw = bytearray()
    stride = size * 4
    for y in range(size):
        raw.append(0)
        raw += px[y * stride : (y + 1) * stride]

    def chunk(tag: bytes, body: bytes) -> bytes:
        return (
            struct.pack(">I", len(body))
            + tag
            + body
            + struct.pack(">I", zlib.crc32(tag + body) & 0xFFFFFFFF)
        )

    header = struct.pack(">IIBBBBB", size, size, 8, 6, 0, 0, 0)
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", header)
        + chunk(b"IDAT", zlib.compress(bytes(raw), 9))
        + chunk(b"IEND", b"")
    )


def _ico_bytes(entries: list[tuple[int, bytes]]) -> bytes:
    """A PNG-compressed ICO. Every browser this project supports reads them."""
    count = len(entries)
    out = bytearray(struct.pack("<HHH", 0, 1, count))
    offset = 6 + 16 * count
    for size, payload in entries:
        out += struct.pack(
            "<BBBBHHII",
            0 if size >= 256 else size,
            0 if size >= 256 else size,
            0,
            0,
            1,
            32,
            len(payload),
            offset,
        )
        offset += len(payload)
    for _, payload in entries:
        out += payload
    return bytes(out)


def _read_logo_rgba(path: Path) -> tuple[int, int, bytearray]:
    data = path.read_bytes()
    if data[:8] != b"\x89PNG\r\n\x1a\n":
        raise SystemExit(f"{path} is not a PNG")
    pos, idat, meta = 8, b"", None
    while pos < len(data):
        length = struct.unpack(">I", data[pos : pos + 4])[0]
        tag = data[pos + 4 : pos + 8]
        body = data[pos + 8 : pos + 8 + length]
        if tag == b"IHDR":
            meta = struct.unpack(">IIBBBBB", body)
        elif tag == b"IDAT":
            idat += body
        pos += 12 + length
    if meta is None or meta[2] != 8 or meta[3] != 6 or meta[6] != 0:
        raise SystemExit(f"{path}: expected 8-bit RGBA non-interlaced, got {meta!r}")
    width, height = meta[0], meta[1]
    raw = zlib.decompress(idat)
    stride = width * 4
    out = bytearray(height * stride)
    prev = bytearray(stride)
    cursor = 0
    for y in range(height):
        filter_type = raw[cursor]
        cursor += 1
        line = bytearray(raw[cursor : cursor + stride])
        cursor += stride
        if filter_type == 1:
            for i in range(4, stride):
                line[i] = (line[i] + line[i - 4]) & 255
        elif filter_type == 2:
            for i in range(stride):
                line[i] = (line[i] + prev[i]) & 255
        elif filter_type == 3:
            for i in range(stride):
                left = line[i - 4] if i >= 4 else 0
                line[i] = (line[i] + ((left + prev[i]) >> 1)) & 255
        elif filter_type == 4:
            for i in range(stride):
                left = line[i - 4] if i >= 4 else 0
                up = prev[i]
                upleft = prev[i - 4] if i >= 4 else 0
                predictor = left + up - upleft
                pa, pb, pc = abs(predictor - left), abs(predictor - up), abs(predictor - upleft)
                if pa <= pb and pa <= pc:
                    line[i] = (line[i] + left) & 255
                elif pb <= pc:
                    line[i] = (line[i] + up) & 255
                else:
                    line[i] = (line[i] + upleft) & 255
        out[y * stride : (y + 1) * stride] = line
        prev = line
    return width, height, out


def _sample_palette() -> None:
    width, height, px = _read_logo_rgba(LOGO)
    print(f"{LOGO.relative_to(REPO_ROOT)}: {width}x{height}")
    regions = {
        "football": (230, 20, 300, 60),
        "wordmark-left": (20, 60, 190, 110),
        "wordmark-right": (300, 60, 420, 110),
    }
    for label, (x0, y0, x1, y1) in regions.items():
        counts: Counter[Rgb] = Counter()
        for y in range(y0, y1):
            for x in range(x0, x1):
                i = (y * width + x) * 4
                if px[i + 3] > 200:
                    counts[(px[i] // 16 * 16, px[i + 1] // 16 * 16, px[i + 2] // 16 * 16)] += 1
        top = ", ".join(f"#{r:02X}{g:02X}{b:02X}x{n}" for (r, g, b), n in counts.most_common(6))
        print(f"  {label:>14}: {top}")


def build() -> dict[Path, bytes]:
    """Every generated asset, as path -> bytes. Deterministic."""
    ico_entries = [(size, _png_bytes(size, _render(size, 12, None))) for size in (16, 32, 48)]
    return {
        PUBLIC / "favicon.ico": _ico_bytes(ico_entries),
        PUBLIC / "favicon.png": _png_bytes(48, _render(48, 12, None)),
        PUBLIC / "apple-touch-icon.png": _png_bytes(180, _render(180, 4, APPLE_BACKGROUND)),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="fail if committed bytes differ")
    parser.add_argument("--sample", action="store_true", help="reprint the logo palette")
    args = parser.parse_args()

    if args.sample:
        _sample_palette()
        return 0

    assets = build()
    if args.check:
        stale = [
            path
            for path, payload in assets.items()
            if not path.exists() or path.read_bytes() != payload
        ]
        for path in stale:
            print(f"stale: {path.relative_to(REPO_ROOT)}", file=sys.stderr)
        if stale:
            print("run: uv run python scripts/make_favicon.py", file=sys.stderr)
            return 1
        print(f"{len(assets)} favicon assets are current")
        return 0

    PUBLIC.mkdir(parents=True, exist_ok=True)
    for path, payload in assets.items():
        path.write_bytes(payload)
        print(f"wrote {path.relative_to(REPO_ROOT)} ({len(payload)} bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
