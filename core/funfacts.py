"""
funfacts.py  -  Deterministic, archive-grounded post-race commentary.

Generates a small pool of *true* one-liners about a freshly scored race by
comparing it against everything already stored, scores each candidate for how
interesting it is ("salience"), and returns the top few. Salience-ranking (with
a race-seeded jitter to break near-ties) means the report shows the genuinely
notable facts and doesn't print the same three lines every week.

No LLM, no network. Everything is computed from the SQLite archive.
"""
from __future__ import annotations

import statistics
from collections import defaultdict
from datetime import date

from . import db, refdata


def _prior_standard(before_date: str, exclude_id: int | None):
    """All standard-mode result rows strictly before `before_date`
    (plus same-date races with a smaller id, to be safe), as (race, rows)."""
    conn = db.connect()
    races = conn.execute(
        "SELECT * FROM races WHERE mode='standard' AND date<>'' AND date<? "
        "ORDER BY date, race_id", (before_date,)).fetchall()
    out = []
    for race in races:
        if exclude_id is not None and race["race_id"] == exclude_id:
            continue
        rows = conn.execute("SELECT * FROM results WHERE race_id=?",
                            (race["race_id"],)).fetchall()
        out.append((dict(race), [dict(r) for r in rows]))
    conn.close()
    return out


def compute(race: dict, results: list[dict], *, exclude_id: int | None = None,
            limit: int = 3) -> list[str]:
    """Return up to `limit` fun-fact strings for a scored race."""
    rdate = race.get("date") or ""
    finishers = [r for r in results if r.get("status") == "FIN"]
    if not finishers:
        return []
    finishers = sorted(finishers, key=lambda r: r.get("position") or 999)
    winner = finishers[0]
    prior = _prior_standard(rdate, exclude_id) if rdate else []

    year = rdate[:4]
    season = refdata.season_of(int(rdate[5:7])) if len(rdate) >= 7 else ""

    cands: list[tuple[float, str]] = []  # (salience, text)

    def add(sal, text):
        cands.append((sal, text))

    # --- closest finish (margin between 1st and 2nd corrected time) ---------
    if len(finishers) >= 2 and finishers[0].get("corrected_time") is not None \
            and finishers[1].get("corrected_time") is not None:
        margin = finishers[1]["corrected_time"] - finishers[0]["corrected_time"]
        # how does this margin compare to the year's other races?
        year_margins = []
        for ra, rows in prior:
            if ra["date"][:4] != year:
                continue
            fs = sorted([x for x in rows if x.get("status") == "FIN"],
                        key=lambda x: x.get("position") or 999)
            if len(fs) >= 2 and fs[0].get("corrected_time") is not None \
                    and fs[1].get("corrected_time") is not None:
                year_margins.append(fs[1]["corrected_time"] - fs[0]["corrected_time"])
        if margin <= 5:
            sal = 9.0
            tail = " - the closest finish of the year!" if (
                not year_margins or margin <= min(year_margins)) else "."
            add(sal, f"Photo finish: {winner['member']} took it by just "
                     f"{int(margin)}s on corrected time{tail}")
        elif year_margins and margin <= min(year_margins):
            add(7.5, f"Closest finish of {year} so far - {int(margin)}s between "
                     f"1st and 2nd.")

    # --- personal-best corrected time for the winner (and front-runners) ----
    best_by_helm: dict[str, float] = {}
    races_by_helm: dict[str, list[tuple[str, int]]] = defaultdict(list)
    wins_by_helm: dict[str, int] = defaultdict(int)
    for ra, rows in prior:
        for x in rows:
            if x.get("status") == "FIN":
                ct = x.get("corrected_time")
                if ct is not None:
                    best_by_helm[x["member"]] = min(best_by_helm.get(x["member"], 1e18), ct)
                races_by_helm[x["member"]].append((ra["date"], x.get("position")))
                if x.get("position") == 1:
                    wins_by_helm[x["member"]] += 1
    for r in finishers[:3]:
        ct = r.get("corrected_time")
        if ct is None:
            continue
        prev_best = best_by_helm.get(r["member"])
        if prev_best is not None and ct < prev_best:
            add(6.0, f"Personal best for {r['member']}: fastest corrected time "
                     f"in the records.")
            break

    # --- first-ever win / win streak for the winner -------------------------
    w = winner["member"]
    if w not in wins_by_helm or wins_by_helm[w] == 0:
        add(8.0, f"First recorded win for {w} - one for the scrapbook.")
    else:
        # streak: consecutive most-recent races (by date) the winner finished 1st
        recent = sorted(races_by_helm.get(w, []), key=lambda t: t[0])
        streak = 0
        for d, pos in reversed(recent):
            if pos == 1:
                streak += 1
            else:
                break
        if streak >= 2:
            add(7.0, f"{w} makes it {streak + 1} wins in a row.")

    # --- turnout ------------------------------------------------------------
    n = len(results)
    season_sizes = [len(rows) for ra, rows in prior
                    if refdata.season_of(int(ra['date'][5:7])) == season
                    and ra['date'][:4] == year]
    if n >= 6 and (not season_sizes or n > max(season_sizes)):
        add(5.0, f"Biggest turnout of the {season.lower() or 'season'}: {n} boats "
                 f"on the line.")

    # --- returning helm -----------------------------------------------------
    inactive_days = int(db.get_setting("inactive_months", "6")) * 30
    last_seen: dict[str, str] = {}
    for ra, rows in prior:
        for x in rows:
            if ra["date"] > last_seen.get(x["member"], ""):
                last_seen[x["member"]] = ra["date"]
    for r in finishers:
        prev = last_seen.get(r["member"])
        if prev and rdate:
            gap = (date.fromisoformat(rdate) - date.fromisoformat(prev)).days
            if gap >= inactive_days:
                add(6.5, f"Welcome back {r['member']} - first race in "
                         f"{gap // 30} months, finishing "
                         f"{_ord(r.get('position'))}.")
                break

    # --- wind facts (only when wind was actually recorded) ------------------
    wind = float(race.get("windspeed") or 0)
    wdir = (race.get("winddir") or "").strip()
    if wind > 0:
        season_winds = [float(ra.get("windspeed") or 0) for ra, _ in prior
                        if ra['date'][:4] == year and (ra.get("windspeed") or 0) > 0]
        if season_winds and wind >= max(season_winds):
            add(4.5, f"Windiest race of {year} so far at {wind:g} kt.")
        elif season_winds and wind <= min(season_winds):
            add(4.5, f"Lightest race of {year} so far at just {wind:g} kt.")
        else:
            add(2.5, f"Breeze: {wind:g} kt{(' from the ' + wdir) if wdir else ''}.")
        # new wind direction this year
        if wdir:
            dirs_this_year = {(ra.get("winddir") or "").strip() for ra, _ in prior
                              if ra['date'][:4] == year}
            if wdir not in dirs_this_year:
                add(4.0, f"First race from the {wdir} this year.")

    if not cands:
        return []
    # rank by salience; jitter ties deterministically by race id so the pool
    # rotates week to week instead of always showing the same lines.
    seed = int(race.get("race_id") or race.get("race_no") or 0)
    cands.sort(key=lambda c: (-c[0], (hash((c[1], seed)) & 0xffff)))
    seen, out = set(), []
    for _, text in cands:
        if text in seen:
            continue
        seen.add(text)
        out.append(text)
        if len(out) >= limit:
            break
    return out


def _ord(n) -> str:
    try:
        n = int(n)
    except (TypeError, ValueError):
        return str(n)
    suf = "th" if 10 <= n % 100 <= 20 else {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
    return f"{n}{suf}"
