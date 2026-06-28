"""
scoring.py  -  The classic base-100 scoring engine.

This is a faithful, deliberately simple implementation of the method on
a classic club-handicap convention ("formulas for race results & handicap adjustments"),
verified against the historical RACES_D archive to the cent.

    Net Handicap         g  = boat_h + personal_h + crew_h
    Corrected Time       h  = round(elapsed * 100 / g)         -> rank ascending
    Corrected Time 2     i  = elapsed * 100 / (boat_h + personal_h)   (crew excluded)
    Median ("Mean") Time j  = median of all finishers' i        (the "middle boat")
    Handicap Sailed To   k  = elapsed * 100 / j
    Deviation               = k - (boat_h + personal_h)

Three race modes:
    standard    - full club handicap (g = boat + personal + crew). Feeds HC updates.
    boat_only   - championship trophies where "boat handicaps only shall apply"
                  (g = boat_h). Produces NO deviation and does NOT feed HC updates.
    one_design  - identical fleet / training: g = 100 for everyone, i.e. ranking
                  is by raw elapsed time.

No I/O here. Input and output are plain dicts so a web layer can reuse this.
"""
from __future__ import annotations

from statistics import median
from typing import Any

from .timeutil import elapsed_seconds

# Result codes that mean "no valid finishing time"
NON_FINISH_CODES = {"DNF", "DNS", "DNC", "DSQ", "OCS", "RET", "DNE", "DGM"}

MODE_STANDARD = "standard"
MODE_BOAT_ONLY = "boat_only"
MODE_ONE_DESIGN = "one_design"
ONE_DESIGN_HC = 100.0


def round_half_up(x: float) -> int:
    """Round to nearest integer, halves away from zero (what the old app did)."""
    if x >= 0:
        return int(x + 0.5)
    return -int(-x + 0.5)


def _net_handicap(entry: dict, mode: str) -> float:
    boat = float(entry.get("boat_h") or 0)
    per = float(entry.get("per_h") or 0)
    crew = float(entry.get("crew_h") or 0)
    adj = float(entry.get("adj_h") or 0)   # transparent personal adjustment (Johnie rule)
    if mode == MODE_BOAT_ONLY:
        return boat
    if mode == MODE_ONE_DESIGN:
        return ONE_DESIGN_HC
    # adjustment gives time allowance in the result but is deliberately NOT part
    # of the deviation base (boat + personal), so it never feeds the HC update.
    return boat + per + crew + adj


def score_race(entries: list[dict], mode: str = MODE_STANDARD) -> list[dict]:
    """Score one race. Returns a NEW list of result dicts (input not mutated).

    Each input entry dict should contain at least:
        member, boat_sail_no, boat_make, per_h, boat_h, crew_h,
        crew_name, start_group, start_time, finish_time, code
    """
    results: list[dict] = []

    # --- 1. compute elapsed, net handicap, corrected time for each entry ----
    for e in entries:
        r = dict(e)  # copy
        code = (e.get("code") or "").strip().upper()
        r["code"] = code
        elapsed = elapsed_seconds(e.get("start_time"), e.get("finish_time"))
        net = _net_handicap(e, mode)
        r["net_h"] = round(net, 2)
        r["adj_h"] = float(e.get("adj_h") or 0)
        r["elapsed"] = elapsed

        finished = (not code) and (elapsed is not None) and net > 0
        r["_finished"] = finished

        if finished:
            exact = elapsed * 100.0 / net
            r["_corrected_exact"] = exact        # used only for ranking
            r["corrected_time"] = round_half_up(exact)
        else:
            r["_corrected_exact"] = None
            r["corrected_time"] = None
            if not code:
                # blank finish time, no code -> treat as DNF so it is visible
                r["code"] = "DNF"
        # placeholders, filled below
        r["corrected_time2"] = None
        r["h_sailed"] = None
        r["median_time"] = None
        r["deviation"] = None
        r["to_win"] = None
        results.append(r)

    finishers = [r for r in results if r["_finished"]]

    # --- 2. handicap-adjustment maths (standard mode only) ------------------
    if mode == MODE_STANDARD and finishers:
        ct2_values = []
        for r in finishers:
            base = float(r.get("boat_h") or 0) + float(r.get("per_h") or 0)
            if base > 0:
                ct2 = r["elapsed"] * 100.0 / base
                r["corrected_time2"] = round(ct2, 2)
                ct2_values.append(ct2)
        if ct2_values:
            med = median(ct2_values)  # "middle boat" - avg of two middles if even
            for r in finishers:
                base = float(r.get("boat_h") or 0) + float(r.get("per_h") or 0)
                h_sailed = r["elapsed"] * 100.0 / med
                r["median_time"] = round(med, 2)
                r["h_sailed"] = round(h_sailed, 2)
                r["deviation"] = round(h_sailed - base, 2)

    # --- 3. rank finishers by corrected time (ascending), then the rest -----
    # Rank on the unrounded corrected time so two boats that merely round to the
    # same integer are still separated correctly. Genuine exact ties share a
    # position (standard competition ranking: 1, 2, 2, 4).
    finishers.sort(key=lambda r: r["_corrected_exact"])
    prev_exact = None
    prev_pos = 0
    winner_corrected = finishers[0]["_corrected_exact"] if finishers else None
    for idx, r in enumerate(finishers, start=1):
        if prev_exact is not None and abs(r["_corrected_exact"] - prev_exact) < 1e-9:
            r["position"] = prev_pos          # true tie -> share place
        else:
            r["position"] = idx
            prev_pos = idx
        prev_exact = r["_corrected_exact"]
        r["status"] = "FIN"
        # "to win" (BCE): how many seconds sooner this boat would have needed to
        # finish to tie the winner's corrected time. target_elapsed makes
        # target_elapsed * 100 / net == winner_corrected.
        net = float(r.get("net_h") or 0)
        if net > 0 and winner_corrected is not None:
            target_elapsed = winner_corrected * net / 100.0
            delta = r["elapsed"] - target_elapsed
            r["to_win"] = 0 if r["position"] == 1 else int(round(delta))
        else:
            r["to_win"] = None
    for r in results:
        if not r["_finished"]:
            r["position"] = None
            r["status"] = r["code"]

    for r in results:
        r.pop("_finished", None)
        r.pop("_corrected_exact", None)

    # stable output order: finishers by position, then non-finishers
    ordered = sorted(
        results,
        key=lambda r: (r["position"] is None, r["position"] or 0),
    )
    return ordered


def race_summary(results: list[dict]) -> dict[str, Any]:
    """Small roll-up used by the report header."""
    finishers = [r for r in results if r["status"] == "FIN"]
    return {
        "entries": len(results),
        "finishers": len(finishers),
        "non_finishers": len(results) - len(finishers),
    }


# ---------------------------------------------------------------------------
# Hull split  (added in the v2 feature build)
# ---------------------------------------------------------------------------
def split_by_hull(results: list[dict]) -> dict[str, list[dict]]:
    """Split scored results into monohull / multihull fleets, each re-ranked
    and re-timed *within itself*.

    Input is the output of score_race() (already ordered by overall corrected
    time). Output: {'mono': [...], 'multi': [...]} where each list is ordered,
    finishers carry a fresh fleet-local 'position' and 'to_win' (seconds sooner
    needed to beat that fleet's own winner), and non-finishers follow.

    Hull is decided from each row's boat class key (boat_sail_no) via
    refdata.hull_of(); imported lazily to keep this module I/O-free.
    """
    from .refdata import hull_of

    out: dict[str, list[dict]] = {"mono": [], "multi": []}
    for r in results:
        out[hull_of(r.get("boat_sail_no", ""))].append(dict(r))

    for hull, rows in out.items():
        finishers = [r for r in rows if r.get("status") == "FIN"]
        # preserve the overall ordering (already by exact corrected time)
        winner = finishers[0] if finishers else None
        winner_corrected = None
        if winner is not None:
            net0 = float(winner.get("net_h") or 0)
            if net0 > 0 and winner.get("elapsed") is not None:
                winner_corrected = winner["elapsed"] * 100.0 / net0
        for pos, r in enumerate(finishers, start=1):
            r["position"] = pos
            net = float(r.get("net_h") or 0)
            if net > 0 and winner_corrected is not None and r.get("elapsed") is not None:
                target = winner_corrected * net / 100.0
                r["to_win"] = 0 if pos == 1 else int(round(r["elapsed"] - target))
            else:
                r["to_win"] = None
        for r in rows:
            if r.get("status") != "FIN":
                r["position"] = None
                r["to_win"] = None
    return out
