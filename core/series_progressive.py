"""
series_progressive.py  -  progressive per-race handicapping for a series
(task 12: Commodore-style series).

Two schemes, selected by the operator when scoring a series:

  scheme "a"  (simple, accelerated monthly):
      Every helm starts the series on personal handicap 0 (NOT their club HC --
      this is series-only and never touches the monthly club handicap). After
      each race the personal handicap moves by at most +/-1 in the direction of
      the helm's deviation from the fleet, exactly like the monthly +/-1/+/-2
      method but applied per race with a hard +/-1 cap. The race is scored on
      net = boat + crew + this progressive personal handicap.

  scheme "b"  (NHC-like, base 100):
      Every helm starts on a rating of 100. The race is scored on
      corrected = elapsed * 100 / rating (lower corrected wins). After each race
      the rating is recalculated with the RYA NHC algorithm adapted to base 100:
        achieved   Ha = sum(H1/Te) / sum(1/Te)          (over finishers)
        provisional Hp = 0.7*H1 + 0.3*Ha                 (alpha = 0.3)
        extreme performers (corrected > 1 SD from the fleet mean) have their
            achieved contribution clamped to the +/-1 SD threshold elapsed time,
        non-finishers carry their rating forward,
        the whole fleet is realigned so the mean returns to 100, and each rating
            is clamped to [90, 110] (90%-110% of base).
      Needs at least three finishers to recalculate; otherwise ratings carry.

Both return per-race placings (fed to series.score_series for the standings,
reusing the tested discard logic) plus a per-race digest of the handicap used
and whether it rose or fell versus the previous race.

Pure computation; no I/O beyond reading saved races through the repository.
"""
from __future__ import annotations

import statistics

from . import repository as repo

ALPHA = 0.3
BASE = 100.0
CLAMP_LO, CLAMP_HI = 0.90, 1.10      # 90%-110% of base


def _corrected_a(elapsed, boat_h, crew_h, personal):
    net = (boat_h or 0) + (crew_h or 0) + personal
    return elapsed * 100.0 / net if net > 0 else float(elapsed)


def _corrected_b(elapsed, rating):
    return elapsed * BASE / rating if rating > 0 else float(elapsed)


def _update_scheme_a(hc, fin):
    """fin: [(member, elapsed, corrected)] finishers. +/-1 toward deviation."""
    if not fin:
        return
    mean_c = statistics.mean(c for _, _, c in fin)
    for m, _, c in fin:
        if c < mean_c:           # beat the fleet -> handicap made harder (lower)
            hc[m] -= 1
        elif c > mean_c:         # below the fleet -> handicap eased (higher)
            hc[m] += 1
        # exactly on the mean -> no change


def _update_scheme_b(hc, fin):
    """fin: [(member, elapsed, corrected)] finishers. RYA NHC adapted to base 100.

    Per boat the achieved handicap is the rating that would have placed it at the
    fleet's mean corrected time this race:
        Ha_i = H1_i * (CT_i / CT_mean)
    so a boat faster than the fleet (CT below the mean) has its rating reduced
    (penalised) and a slower boat is helped -- this differentiates even when all
    boats start equal at 100, which a single fleet-wide achieved value would not.
    Extreme performers (>1 SD from the mean) are clamped to the +/-1 SD corrected
    time; non-finishers carry; the fleet is realigned to base and clamped 90-110%.
    """
    if len(fin) < 3:             # NHC needs >=3 finishers, else carry forward
        return
    corrs = [c for _, _, c in fin]
    mu = statistics.mean(corrs)
    sd = statistics.pstdev(corrs) if len(corrs) > 1 else 0.0
    if mu <= 0:
        return

    prov = {}
    for m, _, c in fin:
        h1 = hc[m]
        eff_c = c
        if sd > 0 and abs(c - mu) > sd:           # clamp extreme performers to +/-1 SD
            eff_c = (mu - sd) if c < mu else (mu + sd)
        ha = h1 * (eff_c / mu)                     # achieved rating (relative to fleet)
        prov[m] = (1 - ALPHA) * h1 + ALPHA * ha

    for m in hc:                  # non-finishers carry forward
        prov.setdefault(m, hc[m])

    # realign so the fleet mean returns to base, then clamp each to [90,110]
    s_hp = sum(prov.values())
    factor = (BASE * len(prov)) / s_hp if s_hp else 1.0
    for m, v in prov.items():
        v *= factor
        v = max(CLAMP_LO * BASE, min(CLAMP_HI * BASE, v))
        hc[m] = round(v, 1)


def score_progressive(race_ids: list[int], scheme: str = "a") -> dict:
    """Score a list of races progressively. Returns
        {race_results, per_race, helms, scheme}
    where race_results feeds series.score_series, and per_race holds the digest."""
    scheme = (scheme or "a").lower()
    races = [repo.get_race(r) for r in race_ids]
    results = [repo.get_results(r) for r in race_ids]

    helms = set()
    for rs in results:
        for row in rs:
            helms.add(row["member"])

    hc = {m: (BASE if scheme == "b" else 0.0) for m in helms}

    race_results, per_race = [], []
    used_prev = None
    for idx, (race, rs) in enumerate(zip(races, results)):
        used_this = dict(hc)
        fin = []
        for row in rs:
            m, st, el = row["member"], row.get("status"), row.get("elapsed")
            if st == "FIN" and el:
                if scheme == "b":
                    c = _corrected_b(el, hc[m])
                else:
                    c = _corrected_a(el, row.get("boat_h"), row.get("crew_h"), hc[m])
                fin.append((m, el, c))

        fin.sort(key=lambda t: t[2])
        place = {m: i for i, (m, _, _) in enumerate(fin, 1)}
        times = {m: (el, c) for (m, el, c) in fin}   # finisher timings for the digest

        rr, digest = [], []
        for row in rs:
            m = row["member"]
            crew = row.get("crew_name") or ""
            if m in place:
                rr.append({"member": m, "status": "FIN", "position": place[m],
                           "crew_name": crew})
            else:
                rr.append({"member": m, "status": row.get("status") or "DNC",
                           "position": None, "code": row.get("code") or "DNC",
                           "crew_name": crew})
            flag = "same"
            if used_prev is not None and m in used_prev:
                if used_this[m] < used_prev[m] - 1e-9:
                    flag = "down"
                elif used_this[m] > used_prev[m] + 1e-9:
                    flag = "up"
            el_m, corr_m = times.get(m, (None, None))
            digest.append({"member": m, "hc_used": round(used_this[m], 1),
                           "place": place.get(m), "status": rr[-1]["status"],
                           "elapsed": el_m,
                           "corrected": round(corr_m, 1) if corr_m is not None else None,
                           "flag": flag})

        race_results.append(rr)
        per_race.append({
            "label": f"R{race['race_no']}" if race else f"R{idx + 1}",
            "name": (race or {}).get("name", ""),
            "date": (race or {}).get("date", ""),
            "rows": digest,
        })

        # update handicaps for the NEXT race using THIS race's finishers
        if scheme == "b":
            _update_scheme_b(hc, fin)
        else:
            _update_scheme_a(hc, fin)
        used_prev = used_this

    return {"race_results": race_results, "per_race": per_race,
            "helms": sorted(helms), "scheme": scheme}


SCHEME_LABEL = {
    "a": "Progressive +/-1 per race (from 0)",
    "b": "Progressive NHC-style (base 100)",
}
