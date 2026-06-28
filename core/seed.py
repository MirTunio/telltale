"""
seed.py  -  Build Telltale's store from the club's reference data.

Sources (all already on the base-100 scale, = round(modified-RYA-PY / 10)):

  reference/helm_hc.csv   personal handicaps  (the starting point for the walk)
  reference/boat_hc.csv   one handicap per class / sub-class
  reference/crew_hc.csv   fixed crew list incl. categories (never auto-updated)
  reference/trophy_calendar.csv
  raw/races/*.csv         every race after the old system (the all_races set)

What it does:
  1. seed boats (by class), crew, trophies and settings;
  2. replay the race archive month-by-month from the helm reference handicaps
     (core.walkforward) - one update per month, >= 2 races to qualify, new helms
     in at 0 - and ADOPT the walked handicaps as the live personal handicaps;
  3. store every scored race + result row, and the month-by-month handicap trail.

Run:  python -m core.seed       (or the CLI's "Rebuild from reference data")
"""
from __future__ import annotations

from collections import Counter
from datetime import date

from . import config, db, raceio, refdata, walkforward
from . import trophies as trophies_mod
from .names import canonical, display


def _wipe(conn):
    for t in ("members", "boats", "crew", "trophies", "races", "results",
              "handicap_history", "series", "change_log"):
        conn.execute(f"DELETE FROM {t}")


def seed(verbose: bool = True) -> dict:
    db.init_db()

    # extra settings used by the new CLI
    settings = {
        "default_start_times": "13:30,13:35,13:40,13:45",
        "boat_select_by": "class",     # future option: "sail_no"
        "min_competitors": "3",
        "wind_directions": "N,NE,E,SE,S,SW,W,NW",
    }
    for k, v in settings.items():
        db.set_setting(k, v)

    helm_hc = refdata.load_helm_hc()
    helm_gender = refdata.load_helm_gender()
    boat_hc = refdata.load_boat_hc()
    crew_hc = refdata.load_crew_hc()
    races = raceio.list_races()

    if verbose:
        print(f"reference: {len(helm_hc)} helms, {len(boat_hc)} classes, "
              f"{len(crew_hc)} crew; {len(races)} races "
              f"({races[0]['date']} -> {races[-1]['date']})")

    # ---- walk the handicaps forward -------------------------------------
    cap = int(db.get_setting("hc_cap", "2"))
    min_races = int(db.get_setting("hc_min_races", "2"))
    wr = walkforward.walk(races, helm_hc, boat_hc, crew_hc,
                          cap=cap, min_races=min_races)
    final_hc = wr.final_hc
    if verbose:
        applied = sum(len(md.changes) for md in wr.digest)
        print(f"walk-forward: {len(wr.digest)} months, {applied} adjustments, "
              f"{sum(len(md.new_members) for md in wr.digest)} new helms")

    # ---- per-helm stats from the archive --------------------------------
    fav_class: dict[str, Counter] = {}
    last_raced: dict[str, str] = {}
    for r in races:
        for e in r["entries"]:
            m = e["member"]
            fav_class.setdefault(m, Counter())[e["boat_class"]] += 1
            if r["date"] > last_raced.get(m, ""):
                last_raced[m] = r["date"]

    anchor = races[-1]["date"]                       # "today" = latest race date
    inactive_months = int(db.get_setting("inactive_months", "6"))

    def _is_active(last: str) -> bool:
        if not last:
            return False
        ay, am = int(anchor[:4]), int(anchor[5:7])
        ly, lm = int(last[:4]), int(last[5:7])
        return (ay - ly) * 12 + (am - lm) <= inactive_months

    # ---- single write transaction ---------------------------------------
    conn = db.connect()
    _wipe(conn)

    # boats (by class)
    for cls, hc in sorted(boat_hc.items()):
        conn.execute(
            "INSERT OR REPLACE INTO boats(sail_no, make, boat_name, boat_hc, notes)"
            " VALUES (?,?,?,?,?)",
            (cls, refdata.class_display(cls), "", float(hc), "class handicap"))

    # crew (fixed list)
    for nm, hc in sorted(crew_hc.items()):
        note = "category" if nm in refdata.CREW_CATEGORIES else ""
        conn.execute("INSERT OR REPLACE INTO crew(name, crew_hc, notes) VALUES (?,?,?)",
                     (nm, float(hc), note))

    # trophies
    for t in trophies_mod.TROPHIES:
        conn.execute(
            "INSERT OR REPLACE INTO trophies(name, mode, ladies, series, explain,"
            " year, discontinued) VALUES (?,?,?,?,?,?,?)",
            (t.name, t.mode, 1 if t.ladies else 0, 1 if t.series else 0, t.explain,
             t.year, 1 if t.discontinued else 0))

    # members (union of reference helms + anyone who raced); adopt walked HC
    all_members = set(helm_hc) | set(final_hc) | set(last_raced)
    flags = []
    for m in sorted(all_members):
        hc_final = int(final_hc.get(m, helm_hc.get(m, 0)))
        fav = fav_class.get(m)
        default_boat = fav.most_common(1)[0][0] if fav else ""
        last = last_raced.get(m, "")
        status = "Active" if _is_active(last) else "Inactive"
        note = ""
        conn.execute(
            "INSERT OR REPLACE INTO members(name, canonical, personal_hc, default_boat,"
            " default_crew, gender, status, novice, last_raced, date_added, notes)"
            " VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (m, canonical(m), hc_final, default_boat, "", helm_gender.get(m, ""),
             status, 0, last, date.today().isoformat(), note))

    # races + results (scored standard during the alignment walk)
    for sr in wr.scored_races:
        race = sr["race"]
        rid = race["race_no"]
        conn.execute("DELETE FROM races WHERE race_id=?", (rid,))
        conn.execute("DELETE FROM results WHERE race_id=?", (rid,))
        conn.execute(
            "INSERT INTO races(race_id, race_no, date, name, dosc, venue, windspeed,"
            " winddir, mode, num_starts, start_times, notes) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            (rid, race["race_no"], race["date"], race["name"], "", config.DEFAULT_SETTINGS["venue"],
             0, "", "standard", race["num_starts"], race["start_times"],
             f"trophy={race['trophy']}" if race["trophy"] else "imported"))
        for r in sr["results"]:
            cls = r.get("boat_class", "")
            conn.execute(
                "INSERT INTO results(race_id, member, boat_sail_no, boat_make, crew_name,"
                " per_h, boat_h, crew_h, net_h, start_group, start_time, finish_time, code,"
                " elapsed, corrected_time, position, corrected_time2, h_sailed, median_time,"
                " deviation, status) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (rid, r.get("member"), cls, refdata.class_display(cls),
                 r.get("crew_name", ""), r.get("per_h", 0), r.get("boat_h", 0),
                 r.get("crew_h", 0), r.get("net_h", 0), r.get("start_group", 1),
                 r.get("start_time", ""), r.get("finish_time", ""), r.get("code", ""),
                 r.get("elapsed"), r.get("corrected_time"), r.get("position"),
                 r.get("corrected_time2"), r.get("h_sailed"), r.get("median_time"),
                 r.get("deviation"), r.get("status", "")))

    # handicap history: a seed baseline + each month a helm's HC actually moved
    for m in sorted(helm_hc):
        conn.execute(
            "INSERT INTO handicap_history(member, period, personal_hc, source, date_applied)"
            " VALUES (?,?,?,?,?)",
            (m, "seed-start", int(helm_hc[m]), "seed", races[0]["date"]))
    for md in wr.digest:
        for ch in md.changes:
            conn.execute(
                "INSERT INTO handicap_history(member, period, personal_hc, source, date_applied)"
                " VALUES (?,?,?,?,?)",
                (ch.member, md.period, int(ch.new_hc), "walk", md.period + "-01"))

    # personal adjustments: a transparent, logged, per-sailor time allowance the
    # committee can grant (e.g. an age/ability allowance). The mechanism ships
    # with NO rows seeded - add one from the app (Members -> Personal adjustments)
    # and it is recorded with who approved it and why.

    conn.commit()
    conn.close()

    db.log_change("seed", "system", "rebuild",
                  f"{len(all_members)} members, {len(races)} races, "
                  f"adopted walked handicaps", "", "")
    # the walk applied one update per month through the last race month, so mark
    # the HCs as updated through that month -- the startup forced-update then has
    # nothing to redo for already-processed months.
    db.set_setting("hc_updated_through", races[-1]["date"][:7])
    db.mirror_to_csv()

    if verbose and flags:
        print("flags:", ", ".join(flags))
    return {"members": len(all_members), "boats": len(boat_hc),
            "crew": len(crew_hc), "trophies": len(trophies_mod.TROPHIES),
            "races": len(races), "adjustments": sum(len(md.changes) for md in wr.digest)}


if __name__ == "__main__":
    print(seed())
