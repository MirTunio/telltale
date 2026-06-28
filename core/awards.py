"""
awards.py  -  Season / month / year awards, consistency stars and head-to-head,
all computed deterministically from the stored race archive (no LLM, no guesses).

The headline "Champion" is the lowest low-point net over the period, using the
operator's qualification + per-sailor discard rule (all adjustable in settings):

    * a sailor must have sailed at least `min_to_qualify` races to appear;
    * each sailor drops their worst (sailed - min_to_qualify) results, i.e. they
      are scored on their best `min_to_qualify` races. So everyone is compared on
      the same number of their best results.

Defaults:
    month   min 3   (sailed 4 -> drop 1, 5 -> drop 2, ...)        award_min_month
    season  min 2 x months-in-season = 6                          award_season_per_month
    year    min 20                                                award_min_year

Hull champions reuse the same maths on the monohull-only / multihull-only
re-rankings of each race (mirrors the per-race hull split).
"""
from __future__ import annotations

import statistics
from collections import defaultdict
from datetime import date, datetime

from . import db
from . import refdata


# --------------------------------------------------------------------------- periods
def month_bounds(ym: str) -> tuple[str, str, str]:
    y, m = int(ym[:4]), int(ym[5:7])
    last = 31
    start = f"{y:04d}-{m:02d}-01"
    end = f"{y:04d}-{m:02d}-{last:02d}"
    label = datetime(y, m, 1).strftime("%B %Y")
    return start, end, label


def season_bounds(year: int, season: str) -> tuple[str, str, str]:
    """A season spans 3 months; Winter (Nov-Jan) straddles the year boundary,
    so its November/December belong to `year-1` going into `year`."""
    months = refdata.season_months(season)
    if not months:
        raise ValueError(f"unknown season {season!r}")
    spans = []
    for mth in months:
        yr = year - 1 if (season == "Winter" and mth in (11, 12)) else year
        spans.append((yr, mth))
    spans.sort()
    (y0, m0), (y1, m1) = spans[0], spans[-1]
    start = f"{y0:04d}-{m0:02d}-01"
    end = f"{y1:04d}-{m1:02d}-31"
    return start, end, f"{season} {year}"


def year_bounds(year: int) -> tuple[str, str, str]:
    return f"{year:04d}-01-01", f"{year:04d}-12-31", str(year)


def min_to_qualify(kind: str, season: str | None = None) -> int:
    if kind == "month":
        return int(db.get_setting("award_min_month", "3"))
    if kind == "season":
        per = int(db.get_setting("award_season_per_month", "2"))
        n = len(refdata.season_months(season)) if season else 3
        return per * n
    if kind == "year":
        return int(db.get_setting("award_min_year", "20"))
    return int(db.get_setting("award_min_year", "20"))  # all-time


# --------------------------------------------------------------------------- data
def _gather(start: str, end: str) -> list[dict]:
    """Standard-mode races (with their result rows) inside [start, end]."""
    conn = db.connect()
    races = conn.execute(
        "SELECT * FROM races WHERE mode='standard' AND date>=? AND date<=? "
        "ORDER BY date, race_id", (start, end)).fetchall()
    out = []
    for race in races:
        rows = conn.execute(
            "SELECT * FROM results WHERE race_id=?", (race["race_id"],)).fetchall()
        out.append({"race": dict(race), "results": [dict(r) for r in rows]})
    conn.close()
    return out


def _fleet_points(gathered: list[dict], hull: str | None) -> dict[str, dict]:
    """Per-helm tally over the period for an optional hull filter.

    Returns {member: {points:[...], sailed, wins, positions:[...], devs:[...]}}.
    Finishers are re-ranked *within the fleet* (so monohull/multihull boards are
    scored on their own positions)."""
    tally: dict[str, dict] = defaultdict(
        lambda: {"points": [], "sailed": 0, "wins": 0, "positions": [], "devs": []})
    for g in gathered:
        rows = g["results"]
        if hull:
            rows = [r for r in rows if refdata.hull_of(r.get("boat_sail_no", "")) == hull]
        finishers = [r for r in rows if r.get("status") == "FIN"]
        finishers.sort(key=lambda r: (r.get("corrected_time") if r.get("corrected_time")
                                      is not None else 1e18,
                                      r.get("elapsed") or 1e18))
        n_fin = len(finishers)
        dnf_score = n_fin + 1
        ranked = {id(r): i + 1 for i, r in enumerate(finishers)}
        for r in rows:
            m = r["member"]
            t = tally[m]
            t["sailed"] += 1
            if r.get("status") == "FIN":
                pos = ranked[id(r)]
                t["points"].append(pos)
                t["positions"].append(pos)
                if pos == 1:
                    t["wins"] += 1
                if r.get("deviation") is not None:
                    t["devs"].append(r["deviation"])
            else:
                t["points"].append(dnf_score)
    return tally


def _standings(tally: dict[str, dict], min_q: int) -> list[dict]:
    rows = []
    for m, t in tally.items():
        if t["sailed"] < min_q:
            continue
        scores = sorted(t["points"])                 # low-point: best are smallest
        kept = scores[:min_q]                         # best min_q (drop the rest)
        net = sum(kept)
        rows.append({
            "member": m, "sailed": t["sailed"], "net": net,
            "discards": t["sailed"] - min_q, "wins": t["wins"],
            "positions": t["positions"], "kept": kept,
        })
    rows.sort(key=lambda s: (s["net"], sorted(s["kept"]), -s["wins"]))
    for i, s in enumerate(rows, 1):
        s["rank"] = i
    return rows


# --------------------------------------------------------------------------- awards
def _hc_at(member: str, on_or_before: str) -> int | None:
    conn = db.connect()
    row = conn.execute(
        "SELECT personal_hc FROM handicap_history WHERE member=? AND date_applied<=? "
        "ORDER BY date_applied DESC, id DESC LIMIT 1", (member, on_or_before)).fetchone()
    if row is None:
        row = conn.execute(
            "SELECT personal_hc FROM handicap_history WHERE member=? "
            "ORDER BY date_applied ASC, id ASC LIMIT 1", (member,)).fetchone()
    conn.close()
    return int(row["personal_hc"]) if row else None


def _returning_in(gathered: list[dict], inactive_days: int) -> dict[str, dict]:
    """Best result by any helm who returned after a long lay-off during the
    period. Returns {member: {position, date}} keyed to their best returning result."""
    # build per-member chronological race dates from the whole archive
    conn = db.connect()
    hist = defaultdict(list)
    for r in conn.execute(
            "SELECT res.member AS m, ra.date AS d, res.position AS p, res.status AS s "
            "FROM results res JOIN races ra ON ra.race_id=res.race_id "
            "WHERE ra.date<>'' ORDER BY ra.date").fetchall():
        hist[r["m"]].append((r["d"], r["p"], r["s"]))
    conn.close()
    period_dates = {g["race"]["date"] for g in gathered}
    best: dict[str, dict] = {}
    for m, recs in hist.items():
        prev = None
        for d, p, s in recs:
            if prev is not None and d in period_dates and s == "FIN":
                gap = (date.fromisoformat(d) - date.fromisoformat(prev)).days
                if gap >= inactive_days:
                    cur = best.get(m)
                    if cur is None or (p is not None and p < cur["position"]):
                        best[m] = {"position": p, "date": d, "gap_days": gap}
            prev = d
    return best


def compute(kind: str, *, ym: str | None = None, year: int | None = None,
            season: str | None = None) -> dict:
    """Compute the full award set for a period. `kind` in
    {month, season, year, all}. Returns a dict ready for display/PNG."""
    if kind == "month":
        start, end, label = month_bounds(ym)
    elif kind == "season":
        start, end, label = season_bounds(year, season)
    elif kind == "year":
        start, end, label = year_bounds(year)
    else:  # all-time
        conn = db.connect()
        row = conn.execute("SELECT MIN(date) a, MAX(date) b FROM races "
                           "WHERE date<>''").fetchone()
        conn.close()
        start, end, label = (row["a"] or "0000-01-01"), (row["b"] or "9999-12-31"), "All-time"

    gathered = _gather(start, end)
    min_q = min_to_qualify(kind, season)

    overall = _standings(_fleet_points(gathered, None), min_q)
    mono = _standings(_fleet_points(gathered, "mono"), min_q)
    multi = _standings(_fleet_points(gathered, "multi"), min_q)

    # categories ------------------------------------------------------------
    cats: list[dict] = []

    def add(title, member, detail):
        if member:
            cats.append({"award": title, "member": member, "detail": detail})

    if overall:
        c = overall[0]
        add("Champion", c["member"], f"net {c['net']} from {c['sailed']} races")
    if mono:
        add("Monohull Champion", mono[0]["member"], f"net {mono[0]['net']}")
    if multi:
        add("Multihull Champion", multi[0]["member"], f"net {multi[0]['net']}")

    # Iron Helm (most races)
    sailed_counts = {s["member"]: s["sailed"] for s in
                     _standings(_fleet_points(gathered, None), 1)}
    if sailed_counts:
        m = max(sailed_counts, key=sailed_counts.get)
        add("Iron Helm", m, f"{sailed_counts[m]} races sailed")

    # Most Wins (overall firsts)
    wins = defaultdict(int)
    for g in gathered:
        for r in g["results"]:
            if r.get("status") == "FIN" and r.get("position") == 1:
                wins[r["member"]] += 1
    if wins:
        m = max(wins, key=wins.get)
        if wins[m] > 0:
            add("Most Wins", m, f"{wins[m]} race win(s)")

    # Most Consistent (lowest spread of finishing positions, qualified helms)
    cons = []
    for s in overall:
        if len(s["positions"]) >= 2:
            cons.append((statistics.pstdev(s["positions"]), s["member"], s["positions"]))
    if cons:
        cons.sort(key=lambda x: x[0])
        sd, m, pos = cons[0]
        add("Most Consistent", m, f"finishes {min(pos)}-{max(pos)} (sd {sd:.2f})")

    # Comeback (best result by a returning helm)
    inactive_days = int(db.get_setting("inactive_months", "6")) * 30
    comeback = _returning_in(gathered, inactive_days)
    if comeback:
        m = min(comeback, key=lambda k: comeback[k]["position"] or 999)
        cb = comeback[m]
        add("Comeback", m, f"{_ordinal(cb['position'])} back after "
                           f"{cb['gap_days']//30} months")

    # Most Improved (biggest favourable HC move start->end of period)
    improved = []
    raced = set(sailed_counts)
    for m in raced:
        h0, h1 = _hc_at(m, start), _hc_at(m, end)
        if h0 is not None and h1 is not None and h1 < h0:
            improved.append((h0 - h1, m, h0, h1))
    if improved:
        improved.sort(reverse=True)
        d, m, h0, h1 = improved[0]
        add("Most Improved", m, f"HC {h0:+d} -> {h1:+d} ({-d:+d})")

    return {
        "kind": kind, "label": label, "start": start, "end": end,
        "min_to_qualify": min_q, "races": len(gathered),
        "overall": overall, "mono": mono, "multi": multi, "categories": cats,
    }


def month_champion(ym: str) -> dict | None:
    """Leader of a month so far (>=1 race). Used for the live race-PNG note and
    the monthly-update announcement. No qualification gate here -- it's a
    'standings leader so far'."""
    gathered = _gather(*month_bounds(ym)[:2])
    if not gathered:
        return None
    standings = _standings(_fleet_points(gathered, None), 1)
    if not standings:
        return None
    top = standings[0]
    return {"member": top["member"], "net": top["net"], "sailed": top["sailed"],
            "races_in_month": len(gathered), "label": month_bounds(ym)[2]}


# --------------------------------------------------------------------------- consistency stars
def consistency_stars(positions: list[int]) -> int:
    """1-3 stars from finishing-position spread (lower spread = more stars)."""
    if len(positions) < 3:
        return 0
    sd = statistics.pstdev(positions)
    if sd <= 1.0:
        return 3
    if sd <= 2.0:
        return 2
    return 1


def consistency_table(months: int = 12) -> dict[str, dict]:
    """Per-member consistency over the last `months` of standard racing."""
    conn = db.connect()
    cutoff = conn.execute("SELECT MAX(date) b FROM races WHERE date<>''").fetchone()["b"]
    conn.close()
    if not cutoff:
        return {}
    cy, cm = int(cutoff[:4]), int(cutoff[5:7])
    start_m = cm - months
    sy = cy + (start_m - 1) // 12
    sm = (start_m - 1) % 12 + 1
    start = f"{sy:04d}-{sm:02d}-01"
    gathered = _gather(start, cutoff)
    tally = _fleet_points(gathered, None)
    out = {}
    for m, t in tally.items():
        out[m] = {"stars": consistency_stars(t["positions"]),
                  "races": t["sailed"], "positions": t["positions"]}
    return out


# --------------------------------------------------------------------------- head to head
def head_to_head(a: str, b: str, start: str | None = None,
                 end: str | None = None) -> dict:
    """Win/loss record between two helms in races they both finished."""
    a, b = a.upper(), b.upper()
    start = start or "0000-01-01"
    end = end or "9999-12-31"
    gathered = _gather(start, end)
    a_wins = b_wins = meetings = 0
    detail = []
    for g in gathered:
        byname = {r["member"]: r for r in g["results"] if r.get("status") == "FIN"}
        if a in byname and b in byname:
            meetings += 1
            pa, pb = byname[a]["position"], byname[b]["position"]
            if pa < pb:
                a_wins += 1
                winner = a
            elif pb < pa:
                b_wins += 1
                winner = b
            else:
                winner = "tie"
            detail.append({"date": g["race"]["date"], "race": g["race"]["name"],
                           "a_pos": pa, "b_pos": pb, "winner": winner})
    return {"a": a, "b": b, "meetings": meetings, "a_wins": a_wins,
            "b_wins": b_wins, "detail": detail}


def _ordinal(n) -> str:
    try:
        n = int(n)
    except (TypeError, ValueError):
        return str(n)
    if 10 <= n % 100 <= 20:
        s = "th"
    else:
        s = {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
    return f"{n}{s}"
