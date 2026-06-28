"""
walkforward.py  -  Replay races month-by-month and roll personal handicaps
forward under the classic monthly rules.

Given a starting set of personal handicaps and a chronological list of races,
this walks calendar month by calendar month:

  * every race in a month is scored with the handicaps as they stand at the
    START of that month (one update per month - the rulebook's cadence);
  * each helm's deviations for the month are collected (crew is excluded from
    the deviation maths, per the rules);
  * at month end, helms with >= min_races get their personal handicap nudged by
    round(avg deviation), capped at +/- cap; nobody else moves;
  * a helm appearing for the first time enters at 0 (rulebook: a helm with no
    club handicap starts at zero).

Per the operator's instruction this "alignment" pass scores every race the
*default* way (boat + personal + crew) regardless of trophy, and fills any
missing boat/crew handicap with a sensible default - the goal is to get every
handicap into the right ballpark, not to reproduce special-trophy scoring.

Pure logic: hand it data, get back the final handicaps, a month-by-month digest
and the scored races. No I/O.
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field

from . import handicap, refdata, scoring


@dataclass
class MonthChange:
    member: str
    old_hc: int
    new_hc: int
    races: int
    avg_deviation: float
    applied: int
    note: str = ""


@dataclass
class MonthDigest:
    period: str                      # 'YYYY-MM'
    races: int
    entries: int
    new_members: list[str] = field(default_factory=list)
    changes: list[MonthChange] = field(default_factory=list)
    no_change: list[MonthChange] = field(default_factory=list)


@dataclass
class WalkResult:
    final_hc: dict[str, int]
    digest: list[MonthDigest]
    scored_races: list[dict]
    start_hc: dict[str, int]
    first_seen: dict[str, str]       # member -> first race date


def _net_default(class_hc: int, per: int, crew: int) -> dict:
    return {"boat_h": class_hc, "per_h": per, "crew_h": crew}


def walk(races: list[dict],
         start_hc: dict[str, int],
         boat_hc: dict[str, int] | None = None,
         crew_hc: dict[str, int] | None = None,
         *,
         cap: int = 2,
         min_races: int = 2,
         default_boat_hc: int = 110,
         new_member_hc: int = 0) -> WalkResult:
    boat_hc = boat_hc or refdata.load_boat_hc()
    crew_hc = crew_hc or refdata.load_crew_hc()

    races = sorted(races, key=lambda r: (r["date"], r.get("race_no", 0)))
    hc: dict[str, int] = dict(start_hc)
    first_seen: dict[str, str] = {}
    digest: list[MonthDigest] = []
    scored_all: list[dict] = []

    # group by calendar month, preserving chronological order
    months: dict[str, list[dict]] = defaultdict(list)
    order: list[str] = []
    for r in races:
        if not r.get("date"):
            continue
        ym = r["date"][:7]
        if ym not in months:
            order.append(ym)
        months[ym].append(r)

    for ym in order:
        month_devs: dict[str, list[float]] = defaultdict(list)
        md = MonthDigest(period=ym, races=len(months[ym]), entries=0)

        for race in months[ym]:
            entries = []
            for e in race["entries"]:
                helm = e["member"]
                if helm not in hc:
                    hc[helm] = new_member_hc
                    if helm not in first_seen:
                        md.new_members.append(helm)
                first_seen.setdefault(helm, race["date"])
                cls = e.get("boat_class", "")
                b = boat_hc.get(cls)
                if b is None:
                    # fall back to the race-time net rating if we have it
                    if e.get("rating"):
                        b = max(1, round(e["rating"] / 10) - hc[helm]
                                - crew_hc.get(e.get("crew_name", ""), 0))
                    else:
                        b = default_boat_hc
                entries.append({
                    **e,
                    **_net_default(b, hc[helm],
                                   crew_hc.get(e.get("crew_name", ""), 0)),
                })
            # alignment pass: always score the default (standard) way
            scored = scoring.score_race(entries, mode=scoring.MODE_STANDARD)
            md.entries += len(scored)
            scored_all.append({"race": race, "results": scored,
                               "hc_snapshot": {e["member"]: hc[e["member"]]
                                               for e in race["entries"]}})
            for r in scored:
                if r.get("deviation") is not None:
                    month_devs[r["member"]].append(r["deviation"])

        # month-end update
        updates = handicap.compute_updates(month_devs, hc, cap=cap,
                                           min_races=min_races)
        for u in updates:
            mc = MonthChange(member=u.member, old_hc=u.old_hc, new_hc=u.new_hc,
                             races=u.races, avg_deviation=u.avg_deviation,
                             applied=u.applied_change, note=u.reason)
            if u.applied_change != 0:
                hc[u.member] = u.new_hc
                md.changes.append(mc)
            else:
                md.no_change.append(mc)
        digest.append(md)

    return WalkResult(final_hc=hc, digest=digest, scored_races=scored_all,
                      start_hc=dict(start_hc), first_seen=first_seen)
