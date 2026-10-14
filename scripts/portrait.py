# /// script
# requires-python = ">=3.11"
# dependencies = ["pillow>=11", "numpy>=2", "scipy>=1.14"]
# ///
"""
Turn Avatar.png into a monochrome ASCII portrait SVG that types itself in,
row by row, like a terminal printing it, then holds still.

GitHub renders SVGs embedded with <img> and plays their SMIL animations
(no JavaScript), so the reveal is a per-row clip-path wipe plus a block cursor.

    uv run scripts/portrait.py                    # writes images/portrait.svg
    uv run scripts/portrait.py --preview out.png  # also renders a static PNG
"""
import argparse
import html
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont
from scipy import ndimage

ROOT = Path(__file__).resolve().parent.parent

# ---- image prep -----------------------------------------------------------
CROP = (170, 50, 1090, 970)   # square box around head and shoulders (x0, y0, x1, y1)
BG_TOLERANCE = 38             # max RGB distance from the backdrop color
FLATTEN = 0.6                 # how far dark tones are lifted toward DARK_TARGET
DARK_TARGET = 0.6             # tones below this get lifted (hair, hoodie)
LOCAL_RADIUS = 10             # blur radius used to extract local detail
LOCAL_GAIN = 2.2              # how much local detail is added back
LINE_WEIGHT = 0.9             # how hard edges are pushed toward dark
GAMMA = 1.25                  # >1 brightens mids so skin lands on sparse chars
WHITE_FLOOR = 0.86            # luminance above this becomes a blank

# ---- ascii grid -----------------------------------------------------------
COLS = 150
RAMP = " .'`:-=+*cs#%@"       # sparse -> dense
CHAR_ASPECT = 15 / 8          # cell height / cell width

# ---- svg layout -----------------------------------------------------------
WIDTH = 840
PAD = 20
TITLEBAR_H = 30
STATUS_H = 34
BG_TOP, BG_BOTTOM = "#111722", "#0d1117"
FRAME = "#30363d"
MUTED = "#7d8590"
INK = "#c9d1d9"
TITLE = "angel@github: ~$ ./portrait.sh"
PROMPT = "angel@github:~$ whoami"
NAME = "Angel Loayza"
PRINT_SECONDS = 6.0


def remove_background(rgb: np.ndarray) -> np.ndarray:
    """Return an alpha mask (0..1): backdrop pixels connected to the border are 0."""
    # top corners only: the hoodie fills the bottom ones
    corners = np.concatenate([rgb[:20, :20], rgb[:20, -20:]])
    backdrop = np.median(corners.reshape(-1, 3), axis=0)
    close = np.linalg.norm(rgb.astype(np.float32) - backdrop, axis=2) < BG_TOLERANCE
    labels, _ = ndimage.label(close)
    border = np.unique(np.concatenate([labels[0], labels[-1], labels[:, 0], labels[:, -1]]))
    bg = np.isin(labels, border[border > 0])
    bg = ndimage.binary_opening(bg, iterations=2)
    return ndimage.gaussian_filter((~bg).astype(np.float32), 1.0)


def prepare(path: Path) -> np.ndarray:
    """Grayscale 0..1 image on white, with line work darkened."""
    img = Image.open(path).convert("RGB").crop(CROP)
    rgb = np.asarray(img)
    alpha = remove_background(rgb)

    gray = img.convert("L").filter(ImageFilter.MedianFilter(5))
    g = np.asarray(gray, dtype=np.float32)

    lo, hi = np.percentile(g[alpha > 0.5], [2, 95])
    tone = np.clip((g - lo) / (hi - lo), 0, 1)

    # local contrast: lifts dark masses (hair, hoodie) toward mid tones while
    # keeping their texture, so they read as curls/folds instead of solid blocks
    detail = (g - ndimage.gaussian_filter(g, LOCAL_RADIUS)) / 255.0
    lift = FLATTEN * np.clip(DARK_TARGET - tone, 0, None)
    tone = np.clip(tone + lift + LOCAL_GAIN * detail, 0, 1)

    fine = ndimage.gaussian_filter(g, 1.5)
    coarse = ndimage.gaussian_filter(g, 6)
    lines = np.clip((coarse - fine) / 40.0, 0, 1)
    tone = np.clip(tone - LINE_WEIGHT * lines, 0, 1)

    return tone * alpha + (1.0 - alpha)


def to_ascii(tone: np.ndarray) -> list[str]:
    rows = round(COLS / CHAR_ASPECT)
    small = Image.fromarray((tone * 255).astype(np.uint8)).resize((COLS, rows), Image.LANCZOS)
    lum = (np.asarray(small, dtype=np.float32) / 255.0) ** GAMMA
    idx = np.clip(((1.0 - lum) * (len(RAMP) - 1) + 0.5).astype(int), 0, len(RAMP) - 1)
    idx[lum >= WHITE_FLOOR] = 0
    return ["".join(RAMP[i] for i in row).rstrip().ljust(COLS) for row in idx]


def render_svg(lines: list[str]) -> str:
    art_w = WIDTH - 2 * PAD
    cell_w = art_w / COLS
    cell_h = cell_w * CHAR_ASPECT
    art_top = TITLEBAR_H + PAD * 0.5
    art_h = len(lines) * cell_h
    status_top = art_top + art_h + PAD * 0.5
    height = status_top + STATUS_H
    row_dur = PRINT_SECONDS / len(lines)
    font_size = cell_h * 0.86

    out = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{WIDTH}" height="{height:.0f}" '
        f'viewBox="0 0 {WIDTH} {height:.0f}" '
        f'font-family="ui-monospace, SFMono-Regular, Menlo, Consolas, monospace">',
        f'<defs><linearGradient id="bg" x1="0" y1="0" x2="0" y2="1">'
        f'<stop offset="0" stop-color="{BG_TOP}"/><stop offset="1" stop-color="{BG_BOTTOM}"/>'
        f"</linearGradient></defs>",
        f'<rect width="{WIDTH}" height="{height:.0f}" rx="12" fill="url(#bg)"/>',
        f'<rect x="0.5" y="0.5" width="{WIDTH - 1}" height="{height - 1:.0f}" rx="12" '
        f'fill="none" stroke="{FRAME}"/>',
        f'<line x1="0" y1="{TITLEBAR_H}" x2="{WIDTH}" y2="{TITLEBAR_H}" stroke="{FRAME}"/>',
    ]
    for i, color in enumerate(("#ff5f56", "#ffbd2e", "#27c93f")):
        out.append(f'<circle cx="{PAD + i * 16}" cy="{TITLEBAR_H / 2}" r="5" fill="{color}"/>')
    out.append(
        f'<text x="{WIDTH / 2}" y="{TITLEBAR_H / 2 + 4}" fill="{MUTED}" font-size="12" '
        f'text-anchor="middle">{html.escape(TITLE)}</text>'
    )

    for r, line in enumerate(lines):
        if not line.strip():
            continue
        top = art_top + r * cell_h
        begin = r * row_dur
        text = (
            f'<text xml:space="preserve" x="{PAD}" y="{top + cell_h * 0.78:.1f}" fill="{INK}" '
            f'font-size="{font_size:.2f}" textLength="{art_w}" lengthAdjust="spacing">'
            f"{html.escape(line)}</text>"
        )
        out.append(
            f'<clipPath id="r{r}"><rect x="{PAD}" y="{top:.1f}" width="0" height="{cell_h:.2f}">'
            f'<animate attributeName="width" from="0" to="{art_w}" begin="{begin:.3f}s" '
            f'dur="{row_dur:.3f}s" fill="freeze"/></rect></clipPath>'
            f'<g clip-path="url(#r{r})">{text}</g>'
            f'<rect y="{top + 1:.1f}" width="{cell_w:.2f}" height="{cell_h - 2:.2f}" fill="{INK}" opacity="0">'
            f'<animate attributeName="x" from="{PAD}" to="{PAD + art_w}" begin="{begin:.3f}s" '
            f'dur="{row_dur:.3f}s" fill="freeze"/>'
            f'<set attributeName="opacity" to="0.85" begin="{begin:.3f}s"/>'
            f'<set attributeName="opacity" to="0" begin="{begin + row_dur:.3f}s"/></rect>'
        )

    status_y = status_top + STATUS_H / 2 + 5
    cursor_x = PAD + (len(PROMPT) + len(NAME) + 2) * 13 * 0.6
    out += [
        f'<line x1="0" y1="{status_top:.1f}" x2="{WIDTH}" y2="{status_top:.1f}" stroke="{FRAME}"/>',
        f'<text x="{PAD}" y="{status_y:.1f}" fill="{MUTED}" font-size="13">{html.escape(PROMPT)} '
        f'<tspan fill="{INK}">{html.escape(NAME)}</tspan></text>',
        f'<rect x="{cursor_x:.1f}" y="{status_y - 12:.1f}" width="8" height="14" fill="{INK}">'
        f'<animate attributeName="opacity" values="1;1;0;0" keyTimes="0;0.5;0.51;1" '
        f'dur="1s" repeatCount="indefinite"/></rect>',
        "</svg>",
    ]
    return "".join(out)


def render_preview(lines: list[str], path: Path) -> None:
    """Static PNG of the final frame, for tuning without a browser."""
    font = ImageFont.truetype("/System/Library/Fonts/Menlo.ttc", 12)
    cw, ch = 7, 13
    img = Image.new("RGB", (COLS * cw + 40, len(lines) * ch + 40), BG_BOTTOM)
    draw = ImageDraw.Draw(img)
    for r, line in enumerate(lines):
        draw.text((20, 20 + r * ch), line, font=font, fill=INK)
    img.save(path)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--src", type=Path, default=ROOT / "Avatar.png")
    parser.add_argument("--out", type=Path, default=ROOT / "images" / "portrait.svg")
    parser.add_argument("--preview", type=Path)
    args = parser.parse_args()

    lines = to_ascii(prepare(args.src))
    svg = render_svg(lines)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(svg)
    print(f"wrote {args.out} ({len(svg) // 1024} KB, {COLS}x{len(lines)} chars)")
    if args.preview:
        render_preview(lines, args.preview)


if __name__ == "__main__":
    main()
