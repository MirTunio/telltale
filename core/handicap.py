"""
handicap.py  -  Classic monthly personal-handicap update.

Straight from page 75 of the rules:

    Average Deviation = (sum of a helm's deviations over the month)
                        / (number of races sailed that month)

    If Average Deviation is +/-1 or +/-2, the Personal Handicap is adjusted
    accordingly. If more than +/-2, the adjustment is limited to +/-2.

Notes that keep this faithful to the *old* system (i.e. "dumber" than Telltale):
  * A helm needs at least MIN_RACES (default 2) results in the period to be
    adjusted - the rule literally reads "for 2 or more races".
  * Only STANDARD-mode races contribute. Boat-only championships and one-design
    races produce no personal deviation and are ignored.
  * NO fleet-wide normalisation. Each helm moves only by their own capped
    deviation. Inactive helms are simply not touched.
  * The new personal handicap is rounded to an integer (handicaps are integers).

Pure logic. Feed it deviations; it hands back proposed changes for the operator
to confirm before anything is written.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from statistics import mean

DEFAULT_CAP = 2          # maximum change per update period
DEFAULT_MIN_RACES = 2    # minimum races in the period to qualify for a change


@dataclass
class HelmUpdate:
    member: str
    old_hc: int
    new_hc: int
    races: int
    deviations: list[float] = field(default_factory=list)
    avg_deviation: float = 0.0
    raw_change: int = 0          # round(avg_deviation) before capping
    applied_change: int = 0      # after +/- cap
    reason: str = ""


def _clamp(value: int, cap: int) -> int:
    if value > cap:
        return cap
    if value < -cap:
        return -cap
    return value


def round_half_up(x: float) -> int:
    if x >= 0:
        return int(x + 0.5)
    return -int(-x + 0.5)


def compute_updates(
    deviations_by_member: dict[str, list[float]],
    current_hc: dict[str, int],
    cap: int = DEFAULT_CAP,
    min_races: int = DEFAULT_MIN_RACES,
) -> list[HelmUpdate]:
    """Return one HelmUpdate per member who sailed in the period.

    deviations_by_member : {MEMBER: [deviation, deviation, ...]}  (standard races)
    current_hc           : {MEMBER: current personal handicap (int)}
    """
    updates: list[HelmUpdate] = []
    for member, devs in sorted(deviations_by_member.items()):
        devs = [d for d in devs if d is not None]
        old = int(current_hc.get(member, 0))
        n = len(devs)
        if n == 0:
            continue
        avg = mean(devs)
        if n < min_races:
            upd = HelmUpdate(
                member=member, old_hc=old, new_hc=old, races=n,
                deviations=devs, avg_deviation=round(avg, 2),
                raw_change=0, applied_change=0,
                reason=f"no change - only {n} race(s), need {min_races}",
            )
            updates.append(upd)
            continue
        raw = round_half_up(avg)
        applied = _clamp(raw, cap)
        new = old + applied
        if applied == 0:
            reason = "no change - average deviation rounds to 0"
        elif abs(raw) > cap:
            reason = f"deviation {avg:+.2f} -> capped at {applied:+d}"
        else:
            reason = f"deviation {avg:+.2f} -> {applied:+d}"
        updates.append(HelmUpdate(
            member=member, old_hc=old, new_hc=new, races=n,
            deviations=devs, avg_deviation=round(avg, 2),
            raw_change=raw, applied_change=applied, reason=reason,
        ))
    return updates
