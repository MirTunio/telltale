"""
report.py  -  PNG / PDF results renderer (SailWave "Blue Blocks" style).

WhatsApp-ready images for a single race (with the monohull / multihull split,
returning-sailor flags, personal-adjustment notes, fun facts and the month
leader), series standings (PNG + multi-page PDF), the handicap list (frequent
and full), an honours board, and a season summary.

Tall-canvas-then-crop keeps the layout simple: draw top-to-bottom, then trim.
Falls back gracefully if no TrueType font is found. Only dependency: Pillow.
"""
from __future__ import annotations

import os
import textwrap

from PIL import Image, ImageDraw, ImageFont

from . import config
from . import refdata
from .timeutil import format_elapsed


# Blue Blocks palette
BLUE = (71, 36, 114)        # header slate
BLUE_DK = (52, 26, 82)      # header slate (dark)
HEADERTXT = (255, 255, 255)
ROW_A = (255, 255, 255)
ROW_B = (226, 235, 244)
ROW_FLAG = (255, 247, 224)        # tint for a flagged (returning) row
TEXT = (25, 35, 45)
MUTED = (110, 120, 130)
ACCENT = (200, 150, 14)          # accent for fun facts / notes
LINE = (200, 210, 220)
BG = (247, 250, 252)

_FONT_CANDIDATES = [
    # Bundled with the app -> full glyph coverage (stars, arrows) on every OS,
    # including Windows where base Arial lacks U+2605/U+21A9.
    os.path.join(config.FONTS_DIR, "DejaVuSans.ttf"),
    os.path.join(config.FONTS_DIR, "DejaVuSans-Bold.ttf"),
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "C:/Windows/Fonts/arial.ttf",
    "C:/Windows/Fonts/arialbd.ttf",
    "/Library/Fonts/Arial.ttf",
]


def _hms(seconds) -> str:
    if seconds is None or seconds == "":
        return ""
    s = int(round(seconds))
    return f"{s // 3600}:{(s % 3600) // 60:02d}:{s % 60:02d}"


def _fmt_towin(seconds) -> str:
    """How much sooner a boat needed to finish; winner -> dash."""
    if seconds is None:
        return ""
    s = int(round(seconds))
    if s <= 0:
        return "\u2014"
    return f"{s // 60}:{s % 60:02d}"


def _font(size: int, bold: bool = False):
    names = [p for p in _FONT_CANDIDATES if (("Bold" in p or "bd" in p) == bold)]
    for p in names + _FONT_CANDIDATES:
        if os.path.exists(p):
            try:
                return ImageFont.truetype(p, size)
            except OSError:
                continue
    return ImageFont.load_default()


def _text_w(draw, text, font):
    return draw.textlength(str(text), font=font)


def _fit(draw, text, font, max_w):
    s = str(text)
    if max_w <= 0 or _text_w(draw, s, font) <= max_w:
        return s
    ell = "\u2026"
    while s and _text_w(draw, s + ell, font) > max_w:
        s = s[:-1]
    return (s + ell) if s else ell



BRAND_DIR = os.path.join(config.ASSETS_DIR, "brand")


def _paste_logo(img, x_right: int, y_top: int, h: int, light: bool = True) -> None:
    """Paste the club crest with its right edge at x_right, scaled to height h."""
    name = "telltale_crest_light.png" if light else "telltale_crest_dark.png"
    try:
        logo = Image.open(os.path.join(BRAND_DIR, name)).convert("RGBA")
    except Exception:
        return
    w0, h0 = logo.size
    w = max(1, int(w0 * h / h0))
    logo = logo.resize((w, h), Image.LANCZOS)
    img.paste(logo, (int(x_right - w), int(y_top)), logo)


def _wrap(text: str, width: int) -> list:
    out = []
    for para in (text or "").split("\n"):
        out.extend(textwrap.wrap(para, width=width) or [""])
    return out


def _draw_star(draw, cx, cy, r, filled, color=ACCENT):
    """Draw a 5-point star centred at (cx,cy). filled=True -> solid gold;
    False -> hollow outline. Drawn as a polygon so it renders on any OS,
    independent of whether the chosen font carries U+2605."""
    import math
    pts = []
    for i in range(10):
        ang = -math.pi / 2 + i * math.pi / 5
        rad = r if i % 2 == 0 else r * 0.42
        pts.append((cx + rad * math.cos(ang), cy + rad * math.sin(ang)))
    if filled:
        draw.polygon(pts, fill=color)
    else:
        draw.polygon(pts, outline=(180, 188, 196), width=1)


def _draw_trend_marker(draw, cx, cy, trend, size=11):
    """Prominent, colour-coded form arrow. We map the handicap-movement arrow to
    a performance reading: a handicap that FELL means the sailor got stronger.
        up green triangle   = improving (handicap fell)
        down red triangle   = easing    (handicap rose)
        grey bar            = steady (no change)
    Returns True if it drew anything."""
    GREEN = (34, 153, 84)
    RED = (200, 64, 52)
    GREY = (140, 150, 160)
    h = size
    w = size
    DN = "\u2193"; UP = "\u2191"; FLAT = "\u2192"
    if trend == DN:                       # HC fell -> improving -> point up, green
        draw.polygon([(cx, cy - h), (cx - w, cy + h * 0.7), (cx + w, cy + h * 0.7)],
                     fill=GREEN)
        return True
    if trend == UP:                       # HC rose -> easing -> point down, red
        draw.polygon([(cx, cy + h), (cx - w, cy - h * 0.7), (cx + w, cy - h * 0.7)],
                     fill=RED)
        return True
    if trend == FLAT:                     # steady
        draw.rectangle([cx - w, cy - 2, cx + w, cy + 2], fill=GREY)
        return True
    return False


def _table(draw, x, y, cols, widths, rows, header_font, cell_font,
           row_h=30, header_h=34, aligns=None, flag_rows=None):
    """Generic blue-header table of *string* cells. Returns y after the table."""
    total_w = sum(widths)
    aligns = aligns or ["l"] * len(cols)
    flag_rows = flag_rows or set()
    draw.rectangle([x, y, x + total_w, y + header_h], fill=BLUE)
    cx = x
    for c, w, a in zip(cols, widths, aligns):
        if a == "r":
            tx, anch = cx + w - 8, "rm"
        elif a == "c":
            tx, anch = cx + w // 2, "mm"
        else:
            tx, anch = cx + 8, "lm"
        draw.text((tx, y + header_h // 2), str(c), font=header_font,
                  fill=HEADERTXT, anchor=anch)
        cx += w
    y += header_h
    for i, row in enumerate(rows):
        fill = ROW_FLAG if i in flag_rows else (ROW_A if i % 2 == 0 else ROW_B)
        draw.rectangle([x, y, x + total_w, y + row_h], fill=fill)
        cx = x
        for val, w, a in zip(row, widths, aligns):
            if a == "r":
                tx, anch = cx + w - 8, "rm"
            elif a == "c":
                tx, anch = cx + w // 2, "mm"
            else:
                tx, anch = cx + 8, "lm"
            txt = "" if val is None else _fit(draw, val, cell_font, w - 12)
            draw.text((tx, y + row_h // 2), txt, font=cell_font, fill=TEXT,
                      anchor=anch)
            cx += w
        y += row_h
    draw.rectangle([x, y - row_h * len(rows) - header_h, x + total_w, y],
                   outline=LINE, width=1)
    return y


def _hc_breakdown(r: dict, mode: str) -> str:
    """'H-13 C+0 B110 = 97'  (adjustment shown only when non-zero)."""
    per = float(r.get("per_h") or 0)
    crew = float(r.get("crew_h") or 0)
    boat = float(r.get("boat_h") or 0)
    adj = float(r.get("adj_h") or 0)
    net = r.get("net_h")
    net_s = f"{net:g}" if net is not None else ""
    if mode == "boat_only":
        return f"B{boat:g} = {net_s}"
    if mode == "one_design":
        return f"OD = {net_s}"
    parts = f"H{per:+g} C{crew:+g} B{boat:g}"
    if adj:
        parts += f" A{adj:+g}"
    return f"{parts} = {net_s}"


# --------------------------------------------------------------------------- single race
def render_race_png(race: dict, results: list[dict], out_path: str,
                    club_name: str | None = None, *,
                    month_leader: dict | None = None,
                    fun_facts: list[str] | None = None,
                    returning: set[str] | None = None,
                    adjustments: dict[str, int] | None = None) -> str:
    from .scoring import split_by_hull
    club = club_name or config.DEFAULT_SETTINGS["club_name"]
    returning = returning or set()
    adjustments = adjustments or {}
    mode = race.get("mode", "standard")

    # 'to_win' is derived, not stored; recompute it for the overall table when
    # the rows came from the database (so regenerated PNGs match live ones).
    _fin = [r for r in results if r.get("status") == "FIN"]
    if _fin and all(r.get("to_win") is None for r in _fin):
        winner = min(_fin, key=lambda r: (r.get("corrected_time")
                     if r.get("corrected_time") is not None else 1e18))
        nw = float(winner.get("net_h") or 0)
        wc = (winner["elapsed"] * 100.0 / nw
              if nw > 0 and winner.get("elapsed") is not None else None)
        for r in _fin:
            net = float(r.get("net_h") or 0)
            if net > 0 and wc is not None and r.get("elapsed") is not None:
                r["to_win"] = 0 if r is winner else int(round(r["elapsed"] - wc * net / 100.0))

    f_title = _font(30, bold=True)
    f_sub = _font(16)
    f_info = _font(15)
    f_sect = _font(16, bold=True)
    f_head = _font(14, bold=True)
    f_cell = _font(14)
    f_foot = _font(13)

    # ----- overall table -----
    cols = ["Rank", "Helm", "Crew", "Class", "HC (H C B = Net)", "Start",
            "Finish", "Elapsed", "Corrected", "To Win"]
    widths = [46, 178, 100, 146, 206, 76, 86, 84, 92, 76]
    aligns = ["r", "l", "l", "l", "l", "l", "l", "r", "r", "r"]
    W = sum(widths) + 60

    def helm_label(name):
        return f"{name} \u21a9" if name in returning else name

    rows, flag_rows = [], set()
    for i, r in enumerate(results):
        rank = r["position"] if r.get("status") == "FIN" else (r.get("code") or "-")
        rows.append([
            str(rank), helm_label(r.get("member", "")), r.get("crew_name", "") or "",
            r.get("boat_make", ""), _hc_breakdown(r, mode),
            r.get("start_time", ""),
            r.get("finish_time", "") or (r.get("code") or ""),
            format_elapsed(r.get("elapsed")), _hms(r.get("corrected_time")),
            _fmt_towin(r.get("to_win")),
        ])
        if r.get("member") in returning:
            flag_rows.add(i)

    img = Image.new("RGB", (W, 4000), BG)
    d = ImageDraw.Draw(img)

    # banner
    header_h = 96
    d.rectangle([0, 0, W, header_h], fill=BLUE_DK)
    d.text((30, 26), race.get("name") or "CLUB RACE", font=f_title,
           fill=HEADERTXT, anchor="lm")
    sub = f"{club}   \u2022   {race.get('date', '')}"
    if race.get("venue"):
        sub += f"   \u2022   {race['venue']}"
    d.text((30, 64), sub, font=f_sub, fill=(224, 214, 240), anchor="lm")
    _paste_logo(img, W - 22, 14, 68, light=True)

    mode_lbl = {"standard": "Club Handicap (NHC)", "boat_only": "Boat Handicap Only",
                "one_design": "One-Design"}.get(mode, "")
    info = f"{mode_lbl}    Entries: {len(results)}"
    if race.get("windspeed"):
        info += f"    Wind: {race['windspeed']:g} kt {race.get('winddir', '')}".rstrip()
    if race.get("dosc"):
        info += f"    DOSC: {race['dosc']}"
    y = header_h + 16
    d.text((30, y + 14), info, font=f_info, fill=MUTED, anchor="lm")
    y += 44

    d.text((30, y), "OVERALL RESULT", font=f_sect, fill=BLUE_DK, anchor="lm")
    y += 24
    y = _table(d, 30, y, cols, widths, rows, f_head, f_cell, aligns=aligns,
               flag_rows=flag_rows)
    y += 26

    # ----- hull split (only when BOTH fleets actually have boats: task 2) -----
    split = split_by_hull(results)
    both_fleets = len(split["mono"]) >= 1 and len(split["multi"]) >= 1
    scols = ["Rank", "Helm", "Class", "Elapsed", "Corrected", "To Win"]
    swidths = [46, 200, 160, 92, 100, 80]
    saligns = ["r", "l", "l", "r", "r", "r"]
    for hull in (("mono", "multi") if both_fleets else ()):
        fleet = split[hull]
        if not any(r.get("status") == "FIN" for r in fleet):
            continue
        d.text((30, y), refdata.hull_label(hull).upper() + " \u2014 scored separately",
               font=f_sect, fill=BLUE_DK, anchor="lm")
        y += 24
        srows, sflags = [], set()
        for i, r in enumerate(fleet):
            rank = r["position"] if r.get("status") == "FIN" else (r.get("code") or "-")
            srows.append([str(rank), helm_label(r.get("member", "")),
                          r.get("boat_make", ""), format_elapsed(r.get("elapsed")),
                          _hms(r.get("corrected_time")), _fmt_towin(r.get("to_win"))])
            if r.get("member") in returning:
                sflags.add(i)
        y = _table(d, 30, y, scols, swidths, srows, f_head, f_cell, row_h=28,
                   aligns=saligns, flag_rows=sflags)
        y += 22

    # ----- notes: adjustments + returning -----
    note_lines = []
    applied_adj = [(r.get("member"), r.get("adj_h")) for r in results
                   if r.get("adj_h")]
    for m, a in applied_adj:
        note_lines.append(f"Personal adjustment applied: {m} {a:+g} "
                          f"(added to rating, excluded from handicap update).")
    if returning:
        note_lines.append("\u21a9 returning sailor \u2014 personal handicap may be "
                          "stale (no race within the inactive window).")
    for n in note_lines:
        d.text((30, y), n, font=f_foot, fill=MUTED, anchor="lm")
        y += 18
    if note_lines:
        y += 6

    # ----- fun facts -----
    if fun_facts:
        d.text((30, y), "DID YOU KNOW", font=f_sect, fill=ACCENT, anchor="lm")
        y += 24
        for f in fun_facts:
            d.text((44, y), "\u2022 " + f, font=f_info, fill=TEXT, anchor="lm")
            y += 22
        y += 6

    # ----- month leader -----
    if month_leader:
        ml = (f"{month_leader['label']} standings leader so far: "
              f"{month_leader['member']} (net {month_leader['net']} from "
              f"{month_leader['sailed']} race(s), {month_leader['races_in_month']} "
              f"club race(s) this month)")
        d.text((30, y), ml, font=f_info, fill=BLUE_DK, anchor="lm")
        y += 26

    # ----- trophy note (history / conditions: task 8) -----
    try:
        from . import trophies as _troph
        _t = _troph.match_trophy(race.get("name", ""))
        _note = _t.effective_note() if _t else ""
    except Exception:
        _note = ""
    if _note:
        d.text((30, y), "ABOUT THIS TROPHY", font=f_sect, fill=ACCENT, anchor="lm")
        y += 24
        for line in _wrap(_note, 112):
            d.text((30, y), line, font=f_foot, fill=TEXT, anchor="lm")
            y += 17
        y += 8

    # ----- footer -----
    y += 4
    d.text((30, y), "Scoring codes:  FIN finished  -  DNF did not finish  -  "
                    "DNS did not start  -  DNC did not come  -  DSQ disqualified "
                    "(non-finishers score finishers + 1 points).",
           font=f_foot, fill=MUTED, anchor="lm")
    y += 18
    if mode == "boat_only":
        d.text((30, y), "Boat handicaps only \u2014 personal and crew handicaps "
                        "not applied.", font=f_foot, fill=MUTED, anchor="lm")
        y += 16
    d.text((30, y), "Corrected Time = Elapsed \u00d7 100 / Net handicap (lowest wins). "
                    "'To Win' = how much sooner you needed to finish to beat the "
                    "winner.", font=f_foot, fill=MUTED, anchor="lm")
    y += 18
    d.text((30, y), "Generated by Telltale", font=f_foot, fill=LINE, anchor="lm")
    y += 26

    img.crop((0, 0, W, y)).save(out_path)
    return out_path


# --------------------------------------------------------------------------- handicap list
def render_handicap_list(title: str, rows: list[dict], out_path: str,
                         club_name: str | None = None, *,
                         show_stars: bool = True) -> str:
    """rows: {name, hc, last_raced, status, races, stars, trend, adj, returning}.

    The Trend and Consistency columns are drawn as shapes (coloured triangles and
    gold stars) rather than font glyphs, so they always render and read clearly.
    """
    club = club_name or config.DEFAULT_SETTINGS["club_name"]
    f_title = _font(26, bold=True)
    f_sub = _font(15)
    f_head = _font(14, bold=True)
    f_cell = _font(14)
    f_foot = _font(12)

    cols = ["Helm", "HC", "Adj", "Trend", "Consistency", "Races(12m)",
            "Status", "Last raced"]
    widths = [220, 60, 60, 70, 130, 100, 90, 110]
    aligns = ["l", "r", "r", "c", "l", "r", "l", "l"]
    x0, y0, header_h, row_h = 30, 96, 34, 28
    W = sum(widths) + 60

    table = []
    for m in rows:
        name = m["name"] + (" \u21a9" if m.get("returning") else "")
        adj = m.get("adj")
        table.append([
            name, f"{m['hc']:+d}", (f"{adj:+g}" if adj else ""),
            "", "",                                    # Trend + Consistency drawn below
            str(m.get("races", "")),
            m.get("status", ""), m.get("last_raced", "") or "-",
        ])

    img = Image.new("RGB", (W, 120 + header_h + row_h * len(table) + 96), BG)
    d = ImageDraw.Draw(img)
    d.rectangle([0, 0, W, 56], fill=BLUE_DK)
    _paste_logo(img, W - 16, 8, 42, light=True)
    d.text((30, 28), title, font=f_title, fill=HEADERTXT, anchor="lm")
    d.text((30, 72), f"{club}", font=f_sub, fill=MUTED, anchor="lm")
    y = _table(d, x0, y0, cols, widths, table, f_head, f_cell, row_h=row_h,
               header_h=header_h, aligns=aligns)

    # --- overlay shapes in the Trend (idx 3) and Consistency (idx 4) columns ---
    trend_cx = x0 + sum(widths[:3]) + widths[3] // 2
    cons_x0 = x0 + sum(widths[:4])
    for i, m in enumerate(rows):
        cy = y0 + header_h + i * row_h + row_h // 2
        _draw_trend_marker(d, trend_cx, cy, m.get("trend", ""), size=8)
        stars = int(m.get("stars", 0) or 0)
        if show_stars:
            for s in range(3):
                _draw_star(d, cons_x0 + 18 + s * 26, cy, 9, filled=(s < stars))

    # --- legend (drawn star sample, colour key) -------------------------------
    y += 16
    _draw_star(d, 36, y, 7, filled=True)
    d.text((48, y), "consistency (3 = very consistent finishing positions)",
           font=f_foot, fill=MUTED, anchor="lm")
    y += 18
    _draw_trend_marker(d, 37, y, "\u2193", size=6)
    d.text((48, y), "improving (handicap fell)", font=f_foot, fill=MUTED, anchor="lm")
    _draw_trend_marker(d, 240, y, "\u2191", size=6)
    d.text((251, y), "easing (handicap rose)", font=f_foot, fill=MUTED, anchor="lm")
    _draw_trend_marker(d, 430, y, "\u2192", size=6)
    d.text((441, y), "steady    \u21a9 returning (HC may be stale)",
           font=f_foot, fill=MUTED, anchor="lm")
    y += 18
    d.text((30, y), "Lower HC = stronger.  Generated by Telltale",
           font=f_foot, fill=LINE, anchor="lm")
    img.crop((0, 0, W, y + 24)).save(out_path)
    return out_path


# --------------------------------------------------------------------------- series
def _standings_rows(standings, race_labels):
    rows = []
    for s in standings:
        pts = []
        for i, p in enumerate(s["points"]):
            pts.append(f"({p})" if i in s.get("discards", set()) else f"{p}")
        rows.append([str(s["rank"]), s["member"]] + pts +
                    [str(s["total"]), str(s["nett"])])
    return rows


def render_series_png(series: dict, standings: list[dict], race_labels: list[str],
                      out_path: str, club_name: str | None = None, *,
                      mono: list[dict] | None = None,
                      multi: list[dict] | None = None) -> str:
    club = club_name or config.DEFAULT_SETTINGS["club_name"]
    f_title = _font(28, bold=True)
    f_sub = _font(16)
    f_sect = _font(16, bold=True)
    f_head = _font(14, bold=True)
    f_cell = _font(14)
    f_foot = _font(13)

    cols = ["Rank", "Helm"] + race_labels + ["Total", "Nett"]
    widths = [50, 232] + [56] * len(race_labels) + [70, 70]
    aligns = ["r", "l"] + ["r"] * len(race_labels) + ["r", "r"]
    W = sum(widths) + 60

    img = Image.new("RGB", (W, 4000), BG)
    d = ImageDraw.Draw(img)
    header_h = 90
    d.rectangle([0, 0, W, header_h], fill=BLUE_DK)
    d.text((30, 26), series.get("name", "SERIES"), font=f_title, fill=HEADERTXT, anchor="lm")
    d.text((30, 60), f"{club}   \u2022   {len(race_labels)} races"
                     f"   \u2022   {series.get('discards', 0)} discard(s)",
           font=f_sub, fill=(224, 214, 240), anchor="lm")
    y = header_h + 18
    d.text((30, y), "OVERALL STANDINGS", font=f_sect, fill=BLUE_DK, anchor="lm")
    y += 24
    y = _table(d, 30, y, cols, widths, _standings_rows(standings, race_labels),
               f_head, f_cell, row_h=28, aligns=aligns)
    y += 24

    for hull, data in (("mono", mono), ("multi", multi)):
        if not data:
            continue
        d.text((30, y), refdata.hull_label(hull).upper() + " \u2014 scored separately",
               font=f_sect, fill=BLUE_DK, anchor="lm")
        y += 24
        y = _table(d, 30, y, cols, widths, _standings_rows(data, race_labels),
                   f_head, f_cell, row_h=28, aligns=aligns)
        y += 24

    d.text((30, y), "Low-point scoring \u2014 discarded scores in (brackets). "
                    "Lowest nett wins.", font=f_foot, fill=MUTED, anchor="lm")
    y += 18
    d.text((30, y), "Generated by Telltale", font=f_foot, fill=LINE, anchor="lm")
    img.crop((0, 0, W, y + 24)).save(out_path)
    return out_path


def render_series_pdf(series: dict, standings: list[dict], race_labels: list[str],
                      per_race_pages: list[str], out_path: str,
                      club_name: str | None = None, *,
                      mono=None, multi=None) -> str:
    """Page 1 = overall standings (+ hull splits); following pages = each race's
    full result PNG. `per_race_pages` is a list of already-rendered race PNG paths.
    Combined into a single PDF with Pillow (no extra dependency)."""
    tmp_dir = os.path.dirname(out_path)
    standings_png = os.path.join(tmp_dir, "_series_page1.png")
    render_series_png(series, standings, race_labels, standings_png, club_name,
                      mono=mono, multi=multi)
    pages = [standings_png] + list(per_race_pages)
    imgs = [Image.open(p).convert("RGB") for p in pages if os.path.exists(p)]
    if not imgs:
        return out_path
    imgs[0].save(out_path, save_all=True, append_images=imgs[1:])
    try:
        os.remove(standings_png)
    except OSError:
        pass
    return out_path


# --------------------------------------------------------------------------- honours board
def render_honours_board(years: list[int], matrix: dict[str, dict[int, str]],
                         out_path: str, club_name: str | None = None) -> str:
    """matrix[trophy][year] = winner name. Trophies as rows, years as columns."""
    club = club_name or config.DEFAULT_SETTINGS["club_name"]
    f_title = _font(26, bold=True)
    f_sub = _font(15)
    f_head = _font(13, bold=True)
    f_cell = _font(13)
    f_foot = _font(12)

    trophies = sorted(matrix.keys())
    cols = ["Trophy"] + [str(y) for y in years]
    widths = [260] + [140] * len(years)
    aligns = ["l"] + ["l"] * len(years)
    W = sum(widths) + 60

    rows = []
    for t in trophies:
        rows.append([t] + [matrix[t].get(y, "") for y in years])

    img = Image.new("RGB", (W, 120 + 34 + 26 * len(rows) + 70), BG)
    d = ImageDraw.Draw(img)
    d.rectangle([0, 0, W, 56], fill=BLUE_DK)
    d.text((30, 28), "HONOURS BOARD", font=f_title, fill=HEADERTXT, anchor="lm")
    d.text((30, 72), f"{club}   \u2022   trophy winners by year", font=f_sub,
           fill=MUTED, anchor="lm")
    y = _table(d, 30, 96, cols, widths, rows, f_head, f_cell, row_h=26, aligns=aligns)
    y += 14
    d.text((30, y), "Winner = first place in that trophy's race(s) that year.",
           font=f_foot, fill=MUTED, anchor="lm")
    y += 16
    d.text((30, y), "Generated by Telltale", font=f_foot, fill=LINE, anchor="lm")
    img.crop((0, 0, W, y + 24)).save(out_path)
    return out_path


# --------------------------------------------------------------------------- season summary
def render_season_summary(aw: dict, out_path: str,
                          club_name: str | None = None) -> str:
    club = club_name or config.DEFAULT_SETTINGS["club_name"]
    f_title = _font(28, bold=True)
    f_sub = _font(16)
    f_sect = _font(16, bold=True)
    f_head = _font(14, bold=True)
    f_cell = _font(14)
    f_foot = _font(13)

    W = 760
    img = Image.new("RGB", (W, 4000), BG)
    d = ImageDraw.Draw(img)
    header_h = 92
    d.rectangle([0, 0, W, header_h], fill=BLUE_DK)
    d.text((30, 26), f"{aw['label']} \u2014 SEASON SUMMARY", font=f_title,
           fill=HEADERTXT, anchor="lm")
    d.text((30, 62), f"{club}   \u2022   {aw['races']} races   \u2022   "
                     f"qualify: {aw['min_to_qualify']}+ races", font=f_sub,
           fill=(224, 214, 240), anchor="lm")
    y = header_h + 18

    # awards block
    d.text((30, y), "AWARDS", font=f_sect, fill=ACCENT, anchor="lm")
    y += 26
    awcols = ["Award", "Sailor", "Detail"]
    awwidths = [180, 220, 280]
    awrows = [[c["award"], c["member"], c["detail"]] for c in aw["categories"]]
    y = _table(d, 30, y, awcols, awwidths, awrows, f_head, f_cell, row_h=28)
    y += 24

    # top of the overall standings
    if aw["overall"]:
        d.text((30, y), "OVERALL STANDINGS (top 10)", font=f_sect, fill=BLUE_DK, anchor="lm")
        y += 26
        cols = ["Rank", "Helm", "Net", "Races", "Wins"]
        widths = [60, 320, 90, 100, 90]
        aligns = ["r", "l", "r", "r", "r"]
        rows = [[str(s["rank"]), s["member"], str(s["net"]), str(s["sailed"]),
                 str(s["wins"])] for s in aw["overall"][:10]]
        y = _table(d, 30, y, cols, widths, rows, f_head, f_cell, row_h=28, aligns=aligns)
        y += 20

    d.text((30, y), "Generated by Telltale", font=f_foot, fill=LINE, anchor="lm")
    img.crop((0, 0, W, y + 24)).save(out_path)
    return out_path


# --------------------------------------------------------------------------- HC history
# A distinct, readable palette for the line chart (cycled if more series).
_HC_PALETTE = [
    (31, 119, 180), (214, 39, 40), (44, 160, 44), (148, 103, 189),
    (255, 127, 14), (23, 190, 207), (227, 119, 194), (140, 86, 75),
    (188, 189, 34), (127, 127, 127), (31, 78, 121), (176, 122, 28),
    (0, 158, 115), (204, 121, 167), (86, 180, 233), (213, 94, 0),
]


def render_hc_history(title: str, series: list[dict], periods: list[str],
                      out_path: str, club_name: str | None = None,
                      *, subtitle: str = "") -> str:
    """Multi-line chart of personal handicap over time (Pillow only).

    series: [{name, points:[hc|None per period], current, races}]
    periods: ['YYYY-MM', ...] chronological.
    The y-axis is inverted so a *lower* handicap (= stronger) sits higher, hence
    an improving sailor's line trends upward.
    """
    club = club_name or config.DEFAULT_SETTINGS["club_name"]
    f_title = _font(26, bold=True)
    f_sub = _font(15)
    f_axis = _font(13)
    f_lab = _font(13, bold=True)
    f_foot = _font(12)

    # ---- collect value range ----
    vals = [p for s in series for p in s["points"] if p is not None]
    if not vals:
        vals = [0]
    vmin, vmax = min(vals), max(vals)
    if vmin == vmax:
        vmin -= 1; vmax += 1
    pad = max(1, round((vmax - vmin) * 0.12))
    vmin -= pad; vmax += pad
    span = vmax - vmin

    # ---- layout ----
    n = max(1, len(periods))
    left, right, top, bottom = 64, 290, 92, 70
    plot_w = max(360, 60 * (n - 1) + 40)
    plot_h = 26 * max(8, len(series)) if series else 260
    plot_h = max(300, min(plot_h, 560))
    W = left + plot_w + right
    H = top + plot_h + bottom

    img = Image.new("RGB", (W, H), BG)
    d = ImageDraw.Draw(img)
    d.rectangle([0, 0, W, 56], fill=BLUE_DK)
    d.text((30, 28), title, font=f_title, fill=HEADERTXT, anchor="lm")
    sub = subtitle or club
    d.text((30, 74), sub, font=f_sub, fill=MUTED, anchor="lm")
    _paste_logo(img, W - 16, 8, 42, light=True)

    px0, py0 = left, top
    px1, py1 = left + plot_w, top + plot_h

    def X(i):
        return px0 if n == 1 else px0 + (px1 - px0) * i / (n - 1)

    def Y(v):                                   # inverted: vmin at top
        return py0 + (v - vmin) / span * (py1 - py0)

    # plot frame
    d.rectangle([px0, py0, px1, py1], fill=(255, 255, 255), outline=LINE, width=1)

    # y gridlines + labels (integer handicap ticks)
    step = max(1, round(span / 6))
    lo = int(vmin - (vmin % step)) if step else int(vmin)
    v = lo
    while v <= vmax:
        if vmin <= v <= vmax:
            yy = Y(v)
            d.line([px0, yy, px1, yy], fill=(235, 240, 245), width=1)
            d.text((px0 - 8, yy), f"{v:+d}", font=f_axis, fill=MUTED, anchor="rm")
        v += step
    # (axis is labelled by the +/- handicap ticks; the explanatory note that a
    #  lower handicap is stronger lives in the footer to avoid label collisions)

    # x labels (months); thin them if crowded
    show_every = 1 if n <= 13 else 2
    for i, pm in enumerate(periods):
        xx = X(i)
        d.line([xx, py0, xx, py1], fill=(245, 248, 250), width=1)
        if i % show_every == 0:
            lab = pm[2:]                         # 'YY-MM'
            d.text((xx, py1 + 8), lab, font=f_axis, fill=MUTED, anchor="ma")

    # ---- series lines ----
    # label de-collision at the right edge
    end_label_y = []
    order = sorted(range(len(series)),
                   key=lambda k: (series[k]["points"][-1]
                                  if series[k]["points"][-1] is not None else 9e9))
    for k in order:
        s = series[k]
        col = _HC_PALETTE[k % len(_HC_PALETTE)]
        pts = [(X(i), Y(v)) for i, v in enumerate(s["points"]) if v is not None]
        if len(pts) >= 2:
            d.line(pts, fill=col, width=2, joint="curve")
        for (xx, yy) in pts:
            d.ellipse([xx - 2.5, yy - 2.5, xx + 2.5, yy + 2.5], fill=col)
        # right-edge label (name + current HC), nudged to avoid overlap
        last = next((v for v in reversed(s["points"]) if v is not None), None)
        if last is None:
            continue
        ly_true = Y(last)
        ly = ly_true
        for used in end_label_y:
            if abs(ly - used) < 15:
                ly = used + 15
        end_label_y.append(ly)
        # leader line from the true end value across to the (nudged) label dot,
        # so tied handicaps still read to the correct name
        d.line([px1, ly_true, px1 + 9, ly_true, px1 + 17, ly], fill=col, width=1)
        d.ellipse([px1 + 17, ly - 3, px1 + 23, ly + 3], fill=col)
        d.text((px1 + 29, ly), f"{s['name'][:20]}  {last:+d}", font=f_lab,
               fill=(40, 48, 56), anchor="lm")

    y = py1 + 40
    d.text((30, y), f"{len(series)} sailors  |  {periods[0]} \u2192 {periods[-1]}"
                    "  |  lower handicap = stronger, so a rising line = improving",
           font=f_foot, fill=MUTED, anchor="lm")
    y += 16
    d.text((30, y), "Generated by Telltale", font=f_foot, fill=LINE, anchor="lm")
    img.save(out_path)
    return out_path


# --------------------------------------------------------------------------- HC history TABLE
_MON3_LBL = ["", "Jan", "Feb", "Mar", "Apr", "May", "Jun",
             "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]


def _month_label(p: str) -> str:
    try:
        y, m = p.split("-")
        return f"{_MON3_LBL[int(m)]} {y[2:]}"
    except Exception:
        return p


def render_hc_history_table(periods: list, series: list, out_path: str,
                            club_name: str | None = None, *,
                            subtitle: str = "", provisional: bool | None = None) -> str:
    """Tabular personal-handicap history. Columns are months (oldest -> newest),
    then Current, then Name (rightmost). Rows are sorted lowest-HC (best) on top.
    (Task 11.)"""
    club = club_name or config.DEFAULT_SETTINGS["club_name"]
    rows_data = sorted(
        series, key=lambda r: (r.get("current") if r.get("current") is not None else 9999,
                               r.get("name", "")))
    cols = ["#"] + [_month_label(p) for p in periods] + ["Current", "Name"]
    widths = [42] + [58] * len(periods) + [78, 230]
    aligns = ["r"] + ["r"] * len(periods) + ["r", "l"]
    W = sum(widths) + 60

    table = []
    for i, r in enumerate(rows_data, 1):
        pts = list(r.get("points") or [])
        cells = [str(i)]
        for j in range(len(periods)):
            v = pts[j] if j < len(pts) else None
            cells.append(f"{v:+d}" if isinstance(v, int) else "\u00b7")
        cur = r.get("current")
        cells.append(f"{cur:+d}" if isinstance(cur, int) else "\u00b7")
        cells.append(r.get("name", ""))
        table.append(cells)

    f_title = _font(26, bold=True); f_sub = _font(15)
    f_head = _font(13, bold=True);  f_cell = _font(13)
    header_h = 76
    H = header_h + 30 + 34 + 28 * max(1, len(table)) + 80
    img = Image.new("RGB", (W, H), BG)
    d = ImageDraw.Draw(img)
    d.rectangle([0, 0, W, header_h], fill=BLUE_DK)
    d.text((30, 26), "HANDICAP HISTORY", font=f_title, fill=HEADERTXT, anchor="lm")
    sub = subtitle or f"{club}   \u2022   personal handicap by month (lower = stronger)"
    d.text((30, 54), sub, font=f_sub, fill=(224, 214, 240), anchor="lm")
    _paste_logo(img, W - 20, 12, 52, light=True)

    y = header_h + 14
    if provisional is not None:
        stamp = "PROVISIONAL" if provisional else "FINAL"
        col = ACCENT if provisional else (31, 138, 76)
        d.text((W - 30, y + 6), stamp, font=_font(14, bold=True), fill=col, anchor="rm")
    y += 18
    y = _table(d, 30, y, cols, widths, table, f_head, f_cell, row_h=28, aligns=aligns)
    y += 18
    d.text((30, y), f"{len(table)} sailors   \u2022   "
                    f"{(_month_label(periods[0]) + ' to ' + _month_label(periods[-1])) if periods else ''}"
                    "   \u2022   sorted lowest handicap first",
           font=_font(12), fill=MUTED, anchor="lm")
    y += 16
    d.text((30, y), "Generated by Telltale", font=_font(12), fill=LINE, anchor="lm")
    img.crop((0, 0, W, y + 22)).save(out_path)
    return out_path


# --------------------------------------------------------------------------- progressive series (task 12)
def render_progressive_series(series_name: str, standings: list, per_race: list,
                              out_path: str, club_name: str | None = None, *,
                              scheme_label: str = "", provisional: bool = True) -> str:
    """Commodore-style progressive-series output: a points-per-race standings
    block, then a per-race digest showing the handicap used each race with an
    up/down flag versus the previous race. Stamped Provisional / Final."""
    club = club_name or config.DEFAULT_SETTINGS["club_name"]
    labels = [pr["label"] for pr in per_race]
    n = len(labels)

    f_title = _font(26, bold=True); f_sub = _font(15)
    f_sect = _font(16, bold=True); f_head = _font(13, bold=True); f_cell = _font(13)
    f_foot = _font(12)
    GREEN = (31, 138, 76)

    # ----- standings table -----
    s_cols = ["#", "Helm"] + labels + ["Total", "Nett"]
    s_w = [40, 200] + [52] * n + [62, 62]
    s_align = ["r", "l"] + ["r"] * n + ["r", "r"]
    W = max(720, sum(s_w) + 60)
    s_rows = []
    for s in standings:
        cells = [str(s["rank"]), s["member"]]
        for i, p in enumerate(s["points"]):
            cells.append(f"({p})" if i in s["discards"] else str(p))
        cells += [str(s["total"]), str(s["nett"])]
        s_rows.append(cells)

    # ----- digest sizing -----
    digest_rows = sum(len(pr["rows"]) + 2 for pr in per_race)
    H = 90 + 30 + 34 + 28 * max(1, len(s_rows)) + 50 + 28 * digest_rows + 120
    img = Image.new("RGB", (W, H), BG)
    d = ImageDraw.Draw(img)

    header_h = 90
    d.rectangle([0, 0, W, header_h], fill=BLUE_DK)
    d.text((30, 26), f"{series_name}", font=f_title, fill=HEADERTXT, anchor="lm")
    sub = f"{club}   \u2022   {scheme_label}   \u2022   {n} races"
    d.text((30, 56), sub, font=f_sub, fill=(224, 214, 240), anchor="lm")
    _paste_logo(img, W - 20, 12, 60, light=True)

    y = header_h + 16
    stamp = "PROVISIONAL  (series in progress)" if provisional else "FINAL  (series complete)"
    d.text((30, y), stamp, font=f_sect, fill=(ACCENT if provisional else GREEN), anchor="lm")
    y += 30
    d.text((30, y), "STANDINGS  -  points per race (discards in brackets)",
           font=f_sect, fill=BLUE_DK, anchor="lm")
    y += 26
    y = _table(d, 30, y, s_cols, s_w, s_rows, f_head, f_cell, row_h=28, aligns=s_align)
    y += 28

    # ----- per-race digest: results with timings + handicap + up/down flag -----
    d.text((30, y), "PER-RACE DIGEST  -  results, timings and handicap used each race",
           font=f_sect, fill=BLUE_DK, anchor="lm")
    y += 28
    ARROW = {"up": "\u25b2", "down": "\u25bc", "same": "\u2014"}
    for pr in per_race:
        title = f"{pr['label']}   {pr.get('date', '')}   {pr.get('name', '')}".strip()
        d.text((30, y), title, font=f_head, fill=BLUE, anchor="lm")
        y += 22
        cols = ["Place", "Helm", "Elapsed", "Corrected", "HC used", "vs prev"]
        widths = [56, 210, 96, 96, 80, 70]
        aligns = ["r", "l", "r", "r", "r", "c"]
        rows = []
        ordered = sorted(pr["rows"], key=lambda r: (r["place"] is None, r["place"] or 999))
        for r in ordered:
            place = str(r["place"]) if r["place"] else (r["status"] or "-")
            elapsed = format_elapsed(r.get("elapsed")) if r.get("elapsed") else "\u2014"
            corr = r.get("corrected")
            corrected = _hms(corr) if corr is not None else "\u2014"
            hc = f"{r['hc_used']:g}"
            rows.append([place, r["member"], elapsed, corrected, hc,
                         ARROW.get(r["flag"], "")])
        y = _table(d, 30, y, cols, widths, rows, f_head, f_cell, row_h=26, aligns=aligns)
        y += 18

    d.text((30, y), "Elapsed = finish - start.  Corrected = handicap-adjusted time "
                    "(lower wins).  Up/down arrows compare the handicap used with "
                    "the previous race for that helm.", font=f_foot, fill=MUTED, anchor="lm")
    y += 16
    d.text((30, y), "Generated by Telltale", font=f_foot, fill=LINE, anchor="lm")
    img.crop((0, 0, W, y + 22)).save(out_path)
    return out_path
