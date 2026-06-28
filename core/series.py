"""
series.py  -  Low-point series / trophy scoring (RRS App. A / rulebook Part IX).

A low-point convention is used across the series trophies:
    finishers score 1, 2, 3, ... by position;
    DNF / DNS / DSQ score (number of finishers in that race) + 1.

Supports discards (e.g. 3 discards, best 9 of 12) and a minimum-races
qualification (e.g. "only helms completing eight races shall be considered").

score_series() is pure. compute_series_from_db() is the convenience wrapper.
"""
from __future__ import annotations

from collections import defaultdict

from . import repository as repo


def score_series(race_results: list[list[dict]], discards: int = 0,
                 min_races: int = 0) -> list[dict]:
    """race_results: list (one per race) of result-row dicts as stored.

    Returns ranked standings:
        {rank, member, crew, points:[per-race], discards:set(idx), total, nett, sailed}
    """
    n_races = len(race_results)
    # points[member][race_index] = score
    points: dict[str, list[int]] = {}
    sailed: dict[str, int] = defaultdict(int)
    crew_of: dict[str, str] = {}

    # establish full helm roster across the series
    all_members = set()
    for rr in race_results:
        for row in rr:
            all_members.add(row["member"])
    for m in all_members:
        points[m] = [0] * n_races

    for ri, rr in enumerate(race_results):
        finishers = [r for r in rr if r.get("status") == "FIN"]
        n_fin = len(finishers)
        dnf_score = n_fin + 1
        present = set()
        for r in rr:
            m = r["member"]
            present.add(m)
            if r.get("status") == "FIN":
                points[m][ri] = r["position"]
                sailed[m] += 1
            else:
                points[m][ri] = dnf_score   # DNF/DNS/DSQ etc.
                sailed[m] += 1              # they started -> counts as a race sailed
            if r.get("crew_name"):
                crew_of[m] = r["crew_name"]
        # helms in the series who were absent this race -> DNS = n_fin + 1
        for m in all_members - present:
            points[m][ri] = dnf_score

    standings = []
    for m in all_members:
        if min_races and sailed[m] < min_races:
            continue
        pts = points[m]
        # choose the `discards` worst scores to drop
        order = sorted(range(n_races), key=lambda i: pts[i], reverse=True)
        drop = set(order[:discards]) if discards else set()
        total = sum(pts)
        nett = sum(p for i, p in enumerate(pts) if i not in drop)
        standings.append({
            "member": m, "crew": crew_of.get(m, ""), "points": pts,
            "discards": drop, "total": total, "nett": nett, "sailed": sailed[m],
        })

    # rank by nett; tie-break by count of better finishes then last-race score
    def tiebreak_key(s):
        counts = sorted(p for i, p in enumerate(s["points"]) if i not in s["discards"])
        return (s["nett"], counts, s["points"][-1] if s["points"] else 0)

    standings.sort(key=tiebreak_key)
    for i, s in enumerate(standings, start=1):
        s["rank"] = i
    return standings


def compute_series_from_db(race_ids: list[int], discards: int = 0,
                           min_races: int = 0):
    race_results, labels = [], []
    for rid in race_ids:
        race = repo.get_race(rid)
        race_results.append(repo.get_results(rid))
        labels.append(f"R{race['race_no']}" if race else f"R{rid}")
    standings = score_series(race_results, discards, min_races)
    return standings, labels


def _rerank_by_hull(rows: list[dict], hull: str) -> list[dict]:
    """Keep only one hull's rows and re-rank its finishers 1..n by corrected time."""
    from .refdata import hull_of
    sub = [dict(r) for r in rows if hull_of(r.get("boat_sail_no", "")) == hull]
    fin = [r for r in sub if r.get("status") == "FIN"]
    fin.sort(key=lambda r: (r.get("corrected_time") if r.get("corrected_time")
                            is not None else 1e18, r.get("elapsed") or 1e18))
    for i, r in enumerate(fin, 1):
        r["position"] = i
    return sub


def compute_hull_series_from_db(race_ids: list[int], hull: str,
                                discards: int = 0, min_races: int = 0):
    """Series standings for a single hull (mono/multi), each race re-ranked
    within that hull. Returns standings (same shape as score_series)."""
    race_results = []
    for rid in race_ids:
        race_results.append(_rerank_by_hull(repo.get_results(rid), hull))
    return score_series(race_results, discards, min_races)
