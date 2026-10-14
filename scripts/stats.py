# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""
Render a terminal-style stats card (streaks, totals, contributions per month)
from GitHub's public contributions calendar. No token needed: it reads the same
HTML fragment the profile page loads.

Sized to sit next to images/portrait.svg (840 x 884).

    uv run scripts/stats.py                   # fetch live data, write images/stats.svg
    uv run scripts/stats.py --html saved.html # render from a saved calendar page
"""
import argparse
import datetime as dt
import html
import os
import re
import urllib.request
from collections import OrderedDict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
USER = os.environ.get("GH_USER", "angel452")

WIDTH, HEIGHT = 840, 884
PAD = 20
TITLEBAR_H = 30
STATUS_H = 34
BG_TOP, BG_BOTTOM = "#111722", "#0d1117"
PANEL = "#161b22"
FRAME = "#30363d"
MUTED = "#7d8590"
INK = "#e6edf3"
GREEN = "#3fb950"
BAR = "#238636"
BAR_PEAK = "#3fb950"


# ---- data -----------------------------------------------------------------
def fetch_calendar(user: str) -> str:
    req = urllib.request.Request(
        f"https://github.com/users/{user}/contributions",
        headers={"User-Agent": "profile-stats-card"},
    )
    with urllib.request.urlopen(req, timeout=30) as res:
        return res.read().decode("utf-8")


def parse_days(page: str) -> dict[dt.date, int]:
    """Map each calendar date to its contribution count."""
    dates = {}
    for tag in re.findall(r"<td\b[^>]*ContributionCalendar-day[^>]*>", page):
        day, cell = re.search(r'data-date="([^"]+)"', tag), re.search(r'\bid="([^"]+)"', tag)
        if day and cell:
            dates[cell.group(1)] = day.group(1)
    counts = {}
    for cell, label in re.findall(r'<tool-tip[^>]*\bfor="([^"]+)"[^>]*>([^<]*)</tool-tip>', page):
        if cell in dates:
            m = re.match(r"([\d,]+) contribution", label)
            counts[dt.date.fromisoformat(dates[cell])] = int(m.group(1).replace(",", "")) if m else 0
    if not counts:
        raise SystemExit("no contribution days found; GitHub markup may have changed")
    return dict(sorted(counts.items()))


def streaks(days: dict[dt.date, int]) -> tuple[tuple, tuple]:
    """Return (current, longest) streaks as (length, start, end)."""
    dates = list(days)
    longest, run_start, run_len = (0, None, None), None, 0
    for d in dates:
        if days[d] > 0:
            run_start = run_start or d
            run_len += 1
            if run_len > longest[0]:
                longest = (run_len, run_start, d)
        else:
            run_start, run_len = None, 0

    # today still counts as "in progress": a streak survives until tomorrow
    end = len(dates) - 1
    if days[dates[end]] == 0:
        end -= 1
    length = 0
    while end - length >= 0 and days[dates[end - length]] > 0:
        length += 1
    current = (length, dates[end - length + 1], dates[end]) if length else (0, None, None)
    return current, longest


def monthly(days: dict[dt.date, int], months: int = 13) -> list[tuple[str, int]]:
    totals: OrderedDict[str, int] = OrderedDict()
    for d, n in days.items():
        key = d.strftime("%Y-%m")
        totals[key] = totals.get(key, 0) + n
    return list(totals.items())[-months:]


# ---- svg ------------------------------------------------------------------
def esc(s) -> str:
    return html.escape(str(s))


def span(start, end) -> str:
    if not start:
        return "no active streak"
    fmt = lambda d: d.strftime("%b %-d")
    return fmt(start) if start == end else f"{fmt(start)} – {fmt(end)}"


def fade_in(delay: float) -> str:
    return (
        f'<animate attributeName="opacity" from="0" to="1" begin="{delay:.2f}s" '
        f'dur="0.5s" fill="freeze"/>'
    )


def tile(x, y, w, h, label, value, unit, sub, color, delay) -> str:
    big = 56
    unit_x = x + 24 + len(value) * big * 0.6 + 8
    return (
        f'<g opacity="0">{fade_in(delay)}'
        f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="10" fill="{PANEL}" stroke="{FRAME}"/>'
        f'<text x="{x + 24}" y="{y + 38}" fill="{MUTED}" font-size="20">$ {esc(label)}</text>'
        f'<text x="{x + 24}" y="{y + 98}" fill="{color}" font-size="{big}" font-weight="700">{esc(value)}</text>'
        f'<text x="{unit_x:.0f}" y="{y + 98}" fill="{MUTED}" font-size="22">{esc(unit)}</text>'
        f'<text x="{x + 24}" y="{y + 128}" fill="{MUTED}" font-size="18">{esc(sub)}</text>'
        "</g>"
    )


def bar_chart(x, y, w, h, months, delay) -> str:
    out = [
        f'<g opacity="0">{fade_in(delay)}'
        f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="10" fill="{PANEL}" stroke="{FRAME}"/>'
        f'<text x="{x + 24}" y="{y + 38}" fill="{MUTED}" font-size="20">$ contributions / month</text></g>'
    ]
    plot_l, plot_r = x + 24, x + w - 24
    plot_top, base = y + 84, y + h - 44
    slot = (plot_r - plot_l) / len(months)
    bar_w = slot * 0.62
    peak = max(n for _, n in months) or 1
    peak_i = max(range(len(months)), key=lambda i: months[i][1])

    for i, (key, n) in enumerate(months):
        bh = max(2.0, (base - plot_top) * n / peak) if n else 2.0
        bx = plot_l + i * slot + (slot - bar_w) / 2
        begin = delay + 0.3 + i * 0.07
        color = BAR_PEAK if i == peak_i else BAR
        out.append(
            f'<rect x="{bx:.1f}" y="{base:.1f}" width="{bar_w:.1f}" height="0" rx="3" fill="{color}">'
            f'<animate attributeName="height" from="0" to="{bh:.1f}" begin="{begin:.2f}s" dur="0.6s" fill="freeze"/>'
            f'<animate attributeName="y" from="{base:.1f}" to="{base - bh:.1f}" begin="{begin:.2f}s" dur="0.6s" fill="freeze"/>'
            "</rect>"
        )
        letter = dt.date.fromisoformat(key + "-01").strftime("%b")[0]
        out.append(
            f'<text x="{bx + bar_w / 2:.1f}" y="{base + 30:.1f}" fill="{MUTED}" font-size="18" '
            f'text-anchor="middle">{letter}</text>'
        )
        if i == peak_i and n:
            out.append(
                f'<text x="{bx + bar_w / 2:.1f}" y="{base - bh - 10:.1f}" fill="{INK}" font-size="18" '
                f'font-weight="700" text-anchor="middle" opacity="0">{fade_in(begin + 0.6)}{n:,}</text>'
            )
    return "".join(out)


def render(days: dict[dt.date, int], today: dt.date) -> str:
    current, longest = streaks(days)
    total = sum(days.values())
    active = sum(1 for n in days.values() if n)
    best_day, best = max(days.items(), key=lambda kv: (kv[1], kv[0]))
    avg = total / active if active else 0

    tiles = [
        ("current streak", f"{current[0]}", " days", span(current[1], current[2]), GREEN),
        ("longest streak", f"{longest[0]}", " days", span(longest[1], longest[2]), INK),
        ("contributions", f"{total:,}", "", "in the last year", INK),
        ("active days", f"{active}", f" / {len(days)}", f"{active / len(days):.0%} of the year", INK),
        ("best day", f"{best}", "", best_day.strftime("%b %-d, %Y"), INK),
        ("avg / active day", f"{avg:.1f}", "", "contributions", INK),
    ]

    out = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{WIDTH}" height="{HEIGHT}" '
        f'viewBox="0 0 {WIDTH} {HEIGHT}" '
        f'font-family="ui-monospace, SFMono-Regular, Menlo, Consolas, monospace">',
        f'<defs><linearGradient id="bg" x1="0" y1="0" x2="0" y2="1">'
        f'<stop offset="0" stop-color="{BG_TOP}"/><stop offset="1" stop-color="{BG_BOTTOM}"/>'
        f"</linearGradient></defs>",
        f'<rect width="{WIDTH}" height="{HEIGHT}" rx="12" fill="url(#bg)"/>',
        f'<rect x="0.5" y="0.5" width="{WIDTH - 1}" height="{HEIGHT - 1}" rx="12" fill="none" stroke="{FRAME}"/>',
        f'<line x1="0" y1="{TITLEBAR_H}" x2="{WIDTH}" y2="{TITLEBAR_H}" stroke="{FRAME}"/>',
    ]
    for i, color in enumerate(("#ff5f56", "#ffbd2e", "#27c93f")):
        out.append(f'<circle cx="{PAD + i * 16}" cy="{TITLEBAR_H / 2}" r="5" fill="{color}"/>')
    out.append(
        f'<text x="{WIDTH / 2}" y="{TITLEBAR_H / 2 + 4}" fill="{MUTED}" font-size="12" '
        f'text-anchor="middle">angel@github: ~$ ./stats.sh</text>'
    )

    gap = 16
    tile_w = (WIDTH - 2 * PAD - gap) / 2
    tile_h = 146
    top = TITLEBAR_H + PAD
    for i, t in enumerate(tiles):
        col, row = i % 2, i // 2
        x = PAD + col * (tile_w + gap)
        y = top + row * (tile_h + gap)
        out.append(tile(x, y, tile_w, tile_h, *t, delay=0.2 + i * 0.15))

    chart_y = top + 3 * (tile_h + gap)
    status_top = HEIGHT - STATUS_H
    out.append(bar_chart(PAD, chart_y, WIDTH - 2 * PAD, status_top - PAD * 0.5 - chart_y, monthly(days), 1.2))

    status_y = status_top + STATUS_H / 2 + 5
    out += [
        f'<line x1="0" y1="{status_top}" x2="{WIDTH}" y2="{status_top}" stroke="{FRAME}"/>',
        f'<text x="{PAD}" y="{status_y:.1f}" fill="{MUTED}" font-size="13">angel@github:~$ '
        f'<tspan fill="{INK}">updated {today.isoformat()}</tspan></text>',
        "</svg>",
    ]
    return "".join(out)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--html", type=Path, help="render from a saved calendar page")
    parser.add_argument("--out", type=Path, default=ROOT / "images" / "stats.svg")
    args = parser.parse_args()

    page = args.html.read_text() if args.html else fetch_calendar(USER)
    days = parse_days(page)
    svg = render(days, dt.date.today())
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(svg)
    print(f"wrote {args.out} ({len(svg) // 1024} KB, {len(days)} days, {sum(days.values())} contributions)")


if __name__ == "__main__":
    main()
