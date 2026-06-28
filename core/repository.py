"""
repository.py  -  High-level data access used by the CLI and (later) a web layer.

Every mutating call takes a backup, writes to SQLite, logs the change, and
refreshes the CSV mirror, so the two stores never drift.
"""
from __future__ import annotations

from datetime import datetime, date, timedelta

from . import db
from .names import canonical, display

# ----------------------------------------------------------------------------- members
def list_members(active_only: bool = False) -> list[dict]:
    conn = db.connect()
    q = "SELECT * FROM members"
    if active_only:
        q += " WHERE status='Active'"
    q += " ORDER BY name"
    rows = [dict(r) for r in conn.execute(q).fetchall()]
    conn.close()
    return rows


def member_names() -> list[str]:
    return [m["name"] for m in list_members()]


def get_member(name: str) -> dict | None:
    conn = db.connect()
    row = conn.execute("SELECT * FROM members WHERE name=?", (display(name),)).fetchone()
    conn.close()
    return dict(row) if row else None


def add_member(name, personal_hc=0, default_boat="", default_crew="",
               gender="", novice=False, notes="") -> dict:
    name = display(name)
    if novice and personal_hc == 0:
        personal_hc = int(db.get_setting("novice_initial_hc", "5"))
    db.backup()
    conn = db.connect()
    conn.execute(
        "INSERT OR REPLACE INTO members"
        "(name, canonical, personal_hc, default_boat, default_crew, gender,"
        " status, novice, last_raced, date_added, notes) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?)",
        (name, canonical(name), int(personal_hc), default_boat, default_crew,
         gender, "Active", 1 if novice else 0, "",
         date.today().isoformat(), notes),
    )
    conn.commit()
    conn.close()
    db.log_change("add", "member", name, "", personal_hc)
    db.mirror_to_csv(["members"])
    return get_member(name)


def set_member_hc(name, new_hc, source="manual", period=None) -> None:
    name = display(name)
    m = get_member(name)
    old = m["personal_hc"] if m else 0
    db.backup()
    conn = db.connect()
    conn.execute("UPDATE members SET personal_hc=? WHERE name=?", (int(new_hc), name))
    period = period or datetime.now().strftime("%Y-%m")
    conn.execute(
        "INSERT INTO handicap_history(member, period, personal_hc, source, date_applied)"
        " VALUES (?,?,?,?,?)",
        (name, period, int(new_hc), source, date.today().isoformat()),
    )
    conn.commit()
    conn.close()
    db.log_change("hc", "member", name, source, old, new_hc)
    db.mirror_to_csv(["members", "handicap_history"])


def set_member_status(name, status) -> None:
    conn = db.connect()
    conn.execute("UPDATE members SET status=? WHERE name=?", (status, display(name)))
    conn.commit()
    conn.close()
    db.log_change("status", "member", display(name), "", "", status)
    db.mirror_to_csv(["members"])


# ----------------------------------------------------------------------------- boats
def list_boats() -> list[dict]:
    conn = db.connect()
    rows = [dict(r) for r in conn.execute("SELECT * FROM boats ORDER BY make, sail_no")]
    conn.close()
    return rows


def get_boat(sail_no: str) -> dict | None:
    conn = db.connect()
    row = conn.execute("SELECT * FROM boats WHERE sail_no=?", (sail_no.upper(),)).fetchone()
    conn.close()
    return dict(row) if row else None


def add_boat(sail_no, make="", boat_name="", boat_hc=100, notes="") -> None:
    db.backup()
    conn = db.connect()
    conn.execute(
        "INSERT OR REPLACE INTO boats(sail_no, make, boat_name, boat_hc, notes)"
        " VALUES (?,?,?,?,?)",
        (sail_no.upper(), make.upper(), boat_name, float(boat_hc), notes),
    )
    conn.commit()
    conn.close()
    db.log_change("add", "boat", sail_no.upper(), make, boat_hc)
    db.mirror_to_csv(["boats"])


def apply_reference_boat_hcs() -> list[tuple[str, float, float]]:
    """Update existing boats' HCs to match config/reference/boat_hc.csv WITHOUT
    wiping anything (unlike a full re-seed, which rebuilds from raw/ and would
    drop races entered in-app). Only classes already in the boats table are
    touched; races, members, helm and crew HCs are left intact. Backs up first
    and mirrors the boats table to CSV. Returns the (class, old, new) rows that
    actually changed."""
    from . import refdata
    ref = refdata.load_boat_hc()                       # {CLASS KEY: hc_base100}
    conn = db.connect()
    current = [(r["sail_no"], float(r["boat_hc"]))
               for r in conn.execute("SELECT sail_no, boat_hc FROM boats")]
    conn.close()
    changed = [(s, old, float(ref[s.upper()]))
               for s, old in current
               if s.upper() in ref and float(ref[s.upper()]) != old]
    if not changed:
        return []
    db.backup()
    conn = db.connect()
    for sail_no, _old, new in changed:
        conn.execute("UPDATE boats SET boat_hc=? WHERE sail_no=?", (float(new), sail_no))
    conn.commit()
    conn.close()
    for sail_no, old, new in changed:
        db.log_change("update", "boat_hc", sail_no, f"{old:g}->{new:g}", new)
    db.mirror_to_csv(["boats"])
    return changed


# ----------------------------------------------------------------------------- crew
def list_crew() -> list[dict]:
    conn = db.connect()
    rows = [dict(r) for r in conn.execute("SELECT * FROM crew ORDER BY name")]
    conn.close()
    return rows


def get_crew(name: str) -> dict | None:
    conn = db.connect()
    row = conn.execute("SELECT * FROM crew WHERE name=?", (display(name),)).fetchone()
    conn.close()
    return dict(row) if row else None


def add_crew(name, crew_hc=0, notes="") -> None:
    conn = db.connect()
    conn.execute("INSERT OR REPLACE INTO crew(name, crew_hc, notes) VALUES (?,?,?)",
                 (display(name), float(crew_hc), notes))
    conn.commit()
    conn.close()
    db.mirror_to_csv(["crew"])


# ----------------------------------------------------------------------------- trophies
def list_trophies() -> list[dict]:
    conn = db.connect()
    rows = [dict(r) for r in conn.execute("SELECT * FROM trophies ORDER BY name")]
    conn.close()
    return rows


def get_trophy(name: str) -> dict | None:
    conn = db.connect()
    row = conn.execute("SELECT * FROM trophies WHERE name=?", (name,)).fetchone()
    conn.close()
    return dict(row) if row else None


# ----------------------------------------------------------------------------- races
def next_race_id() -> int:
    conn = db.connect()
    row = conn.execute("SELECT MAX(race_id) AS m FROM races").fetchone()
    conn.close()
    return (row["m"] or 0) + 1


def save_race(race: dict, results: list[dict]) -> int:
    """Persist a scored race + its result rows. Returns the race_id used."""
    db.backup()
    conn = db.connect()
    rid = race.get("race_id") or next_race_id()
    conn.execute("DELETE FROM races WHERE race_id=?", (rid,))
    conn.execute("DELETE FROM results WHERE race_id=?", (rid,))
    conn.execute(
        "INSERT INTO races(race_id, race_no, date, name, dosc, venue, windspeed,"
        " winddir, mode, num_starts, start_times, notes) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
        (rid, race.get("race_no", rid), race.get("date", ""), race.get("name", ""),
         race.get("dosc", ""), race.get("venue", ""), float(race.get("windspeed", 0) or 0),
         race.get("winddir", ""), race.get("mode", "standard"),
         int(race.get("num_starts", 1)), race.get("start_times", ""), race.get("notes", "")),
    )
    for r in results:
        conn.execute(
            "INSERT INTO results(race_id, member, boat_sail_no, boat_make, crew_name,"
            " per_h, boat_h, crew_h, net_h, adj_h, start_group, start_time, finish_time, code,"
            " elapsed, corrected_time, position, corrected_time2, h_sailed, median_time,"
            " deviation, status) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (rid, r.get("member"), r.get("boat_sail_no", ""), r.get("boat_make", ""),
             r.get("crew_name", ""), r.get("per_h", 0), r.get("boat_h", 0),
             r.get("crew_h", 0), r.get("net_h", 0), r.get("adj_h", 0), r.get("start_group", 1),
             r.get("start_time", ""), r.get("finish_time", ""), r.get("code", ""),
             r.get("elapsed"), r.get("corrected_time"), r.get("position"),
             r.get("corrected_time2"), r.get("h_sailed"), r.get("median_time"),
             r.get("deviation"), r.get("status", "")),
        )
    # update last_raced for finishers / all entrants
    for r in results:
        conn.execute("UPDATE members SET last_raced=?, status='Active' WHERE name=?",
                     (race.get("date", ""), display(r.get("member", ""))))
    conn.commit()
    conn.close()
    db.log_change("score", "race", str(rid), race.get("name", ""), "", len(results))
    db.mirror_to_csv(["races", "results", "members"])
    return rid


def list_races() -> list[dict]:
    conn = db.connect()
    rows = [dict(r) for r in conn.execute("SELECT * FROM races ORDER BY date, race_id")]
    conn.close()
    return rows


def get_race(race_id: int) -> dict | None:
    conn = db.connect()
    row = conn.execute("SELECT * FROM races WHERE race_id=?", (race_id,)).fetchone()
    conn.close()
    return dict(row) if row else None


def get_results(race_id: int) -> list[dict]:
    conn = db.connect()
    rows = [dict(r) for r in conn.execute(
        "SELECT * FROM results WHERE race_id=? ORDER BY (position IS NULL), position",
        (race_id,))]
    conn.close()
    return rows


# ----------------------------------------------------------------------------- HC update
def gather_deviations(start_date: str, end_date: str) -> tuple[dict, list[int]]:
    """Collect standard-mode deviations per member between two YYYY-MM-DD dates.

    Returns (deviations_by_member, [race_ids considered]).
    """
    conn = db.connect()
    races = conn.execute(
        "SELECT race_id FROM races WHERE mode='standard' AND date>=? AND date<=?",
        (start_date, end_date)).fetchall()
    rids = [r["race_id"] for r in races]
    devs: dict[str, list[float]] = {}
    if rids:
        ph = ",".join("?" * len(rids))
        rows = conn.execute(
            f"SELECT member, deviation FROM results WHERE race_id IN ({ph}) "
            f"AND status='FIN' AND deviation IS NOT NULL", rids).fetchall()
        for r in rows:
            devs.setdefault(r["member"], []).append(r["deviation"])
    conn.close()
    return devs, rids


def current_hc_map() -> dict[str, int]:
    return {m["name"]: m["personal_hc"] for m in list_members()}


def apply_handicap_updates(updates, period: str) -> None:
    """Write confirmed HelmUpdate objects (only those that change)."""
    db.backup()
    for u in updates:
        if u.applied_change != 0:
            set_member_hc(u.member, u.new_hc, source="auto", period=period)
    db.mirror_to_csv(["members", "handicap_history"])


# ----------------------------------------------------------------------------- personal adjustments
def list_adjustments(active_only: bool = False) -> list[dict]:
    conn = db.connect()
    q = "SELECT * FROM personal_adjustments"
    if active_only:
        q += " WHERE active=1"
    q += " ORDER BY member"
    rows = [dict(r) for r in conn.execute(q).fetchall()]
    conn.close()
    return rows


def get_adjustment(member: str) -> dict | None:
    conn = db.connect()
    row = conn.execute("SELECT * FROM personal_adjustments WHERE member=?",
                       (display(member),)).fetchone()
    conn.close()
    return dict(row) if row else None


def personal_adj_map() -> dict[str, int]:
    """{MEMBER: adjustment} for active adjustments (added to Rating)."""
    return {a["member"]: int(a["adjustment"])
            for a in list_adjustments(active_only=True) if a["adjustment"]}


def set_adjustment(member, adjustment, reason="", approved_by="Committee",
                   active=True) -> None:
    member = display(member)
    old = get_adjustment(member)
    db.backup()
    conn = db.connect()
    conn.execute(
        "INSERT OR REPLACE INTO personal_adjustments"
        "(member, adjustment, reason, approved_by, date, active) VALUES (?,?,?,?,?,?)",
        (member, int(adjustment), reason, approved_by,
         date.today().isoformat(), 1 if active else 0))
    conn.commit()
    conn.close()
    db.log_change("adjustment", "member", member, str(old["adjustment"]) if old else "",
                  adjustment)
    db.mirror_to_csv(["personal_adjustments"])


# ----------------------------------------------------------------------------- forced HC update
def _standard_race_months() -> list[str]:
    """Sorted distinct 'YYYY-MM' that contain at least one standard-mode race."""
    conn = db.connect()
    rows = conn.execute(
        "SELECT DISTINCT substr(date,1,7) AS ym FROM races "
        "WHERE mode='standard' AND date<>'' ORDER BY ym").fetchall()
    conn.close()
    return [r["ym"] for r in rows if r["ym"]]


def pending_update_months(today=None) -> list[str]:
    """Completed months (strictly before the current month) that contain
    standard races and have not yet been processed (after hc_updated_through).

    The current month is intentionally left until it completes, so a mid-month
    run never applies a premature partial update.
    """
    today = today or date.today()
    cur_ym = today.strftime("%Y-%m")
    marker = db.get_setting("hc_updated_through", "") or ""
    out = []
    for ym in _standard_race_months():
        if ym >= cur_ym:          # don't touch the in-progress month
            continue
        if marker and ym <= marker:
            continue
        out.append(ym)
    return out


def _advance_marker(ym: str) -> None:
    cur = db.get_setting("hc_updated_through", "") or ""
    if ym > cur:
        db.set_setting("hc_updated_through", ym)


def run_month_update(ym: str, *, force: bool = False) -> dict:
    """Apply the classic monthly +/-2 update for one calendar month using the
    deviations already stored on that month's saved results (past results are
    never re-scored). Advances the 'updated through' marker. Returns a summary.

    HARD RULE (task 10): the update for month M may only be applied on/after the
    last Sunday of M -- there is no bypass, `force` cannot override the timing.
    Also blocks (unless force) if the month is at/under the marker.
    """
    from . import handicap
    if not update_allowed(ym):
        return {"period": ym, "blocked": True, "reason": "before_last_sunday",
                "last_sunday": last_sunday_of(ym).isoformat(),
                "races": 0, "applied": 0, "updates": []}
    marker = db.get_setting("hc_updated_through", "") or ""
    if not force and marker and ym <= marker:
        return {"period": ym, "blocked": True, "reason": "already_updated",
                "marker": marker, "races": 0, "applied": 0, "updates": []}
    start, end = ym + "-01", ym + "-31"
    devs, rids = gather_deviations(start, end)
    cap = int(db.get_setting("hc_cap", "2"))
    minr = int(db.get_setting("hc_min_races", "2"))
    ups = handicap.compute_updates(devs, current_hc_map(), cap=cap, min_races=minr)
    apply_handicap_updates(ups, period=ym)
    _advance_marker(ym)
    applied = sum(1 for u in ups if u.applied_change != 0)
    return {"period": ym, "blocked": False, "races": len(rids),
            "applied": applied, "updates": ups}


def run_forced_updates(today=None) -> list[dict]:
    """Walk forward through every pending completed month in order, applying the
    monthly update for each. Past race results are not changed. Returns one
    summary dict per month processed (empty list if nothing was due)."""
    results = []
    for ym in pending_update_months(today):
        results.append(run_month_update(ym))
    return results


# ----------------------------------------------------------------------------- task 10: timing + rollback
def last_sunday_of(ym: str) -> date:
    """The last Sunday of month 'YYYY-MM'."""
    y, m = int(ym[:4]), int(ym[5:7])
    nxt = date(y + 1, 1, 1) if m == 12 else date(y, m + 1, 1)
    last = nxt - timedelta(days=1)
    return last - timedelta(days=(last.weekday() - 6) % 7)


def update_allowed(ym: str, today=None) -> bool:
    """A month's handicap update may only run on/after that month's last Sunday."""
    today = today or date.today()
    return today >= last_sunday_of(ym)


def auto_update_before_race(race_date: str, today=None) -> list[dict]:
    """Before scoring the first race of a new month, fold in every completed
    prior month's handicap update automatically. Returns the summaries applied
    (used to show the homepage / scoring banner). Safe to call before any save:
    it only runs months that are both completed and past their last Sunday."""
    if not race_date:
        return []
    applied = []
    for ym in pending_update_months(today):
        if update_allowed(ym, today):
            res = run_month_update(ym)
            if not res.get("blocked"):
                applied.append(res)
    return applied


def updates_blocking_race(race_date: str, today=None) -> list[str]:
    """Completed prior months still un-applied as of race_date -- scoring a race
    in a new month must run these first (task 10)."""
    if not race_date:
        return []
    rym = race_date[:7]
    marker = db.get_setting("hc_updated_through", "") or ""
    out = []
    for ym in _standard_race_months():
        if ym >= rym:
            continue
        if marker and ym <= marker:
            continue
        out.append(ym)
    return out


def last_update_period() -> str:
    """The most recent monthly ('YYYY-MM') update period that can be rolled back."""
    conn = db.connect()
    rows = [r["period"] for r in conn.execute(
        "SELECT DISTINCT period FROM handicap_history WHERE source='walk'").fetchall()]
    conn.close()
    months = [p for p in rows if len(p) == 7 and p[4] == "-"]
    return max(months) if months else ""


def rollback_last_update() -> dict:
    """Reverse the most recent monthly handicap update: restore each affected
    member's personal handicap to its prior value, delete that month's history
    rows, and move the 'updated through' marker back. Returns a summary."""
    period = last_update_period()
    if not period:
        return {"period": "", "restored": 0, "ok": False, "msg": "no monthly update to roll back"}
    db.backup()
    conn = db.connect()
    restored = 0
    rows = conn.execute(
        "SELECT member, MIN(id) AS rid FROM handicap_history "
        "WHERE period=? AND source='walk' GROUP BY member", (period,)).fetchall()
    for r in rows:
        member, rid = r["member"], r["rid"]
        prev = conn.execute(
            "SELECT personal_hc FROM handicap_history WHERE member=? AND id<? "
            "ORDER BY id DESC LIMIT 1", (member, rid)).fetchone()
        if prev is not None:
            conn.execute("UPDATE members SET personal_hc=? WHERE name=?",
                         (int(prev["personal_hc"]), member))
            restored += 1
    conn.execute("DELETE FROM handicap_history WHERE period=? AND source='walk'", (period,))
    conn.commit()
    # move marker back to the previous processed month
    rest = [p["period"] for p in conn.execute(
        "SELECT DISTINCT period FROM handicap_history WHERE source='walk'").fetchall()]
    conn.close()
    months = [p for p in rest if len(p) == 7 and p[4] == "-" and p < period]
    db.set_setting("hc_updated_through", max(months) if months else "")
    db.log_change("hc_rollback", "update", period, period, "")
    db.mirror_to_csv(["members", "handicap_history"])
    return {"period": period, "restored": restored, "ok": True,
            "marker": db.get_setting("hc_updated_through", "")}


# ----------------------------------------------------------------------------- returning sailors
def returning_members(race_date: str, members: list[str]) -> set[str]:
    """Members whose previous race was longer ago than the inactive window as of
    `race_date` (so their personal HC may be stale). Used to flag them on results.
    A member with no prior race at all is NOT flagged as returning (they are new)."""
    if not race_date:
        return set()
    inactive_days = int(db.get_setting("inactive_months", "6")) * 30
    conn = db.connect()
    out = set()
    for m in members:
        row = conn.execute(
            "SELECT MAX(ra.date) d FROM results res JOIN races ra ON ra.race_id=res.race_id "
            "WHERE res.member=? AND ra.date<? AND ra.date<>''", (m, race_date)).fetchone()
        prev = row["d"] if row else None
        if prev:
            try:
                gap = (date.fromisoformat(race_date) - date.fromisoformat(prev)).days
                if gap >= inactive_days:
                    out.add(m)
            except ValueError:
                pass
    conn.close()
    return out


# ----------------------------------------------------------------------------- honours board
def honours_data():
    """Trophy winners by year, from the archive.

    Returns (years, matrix, long_rows):
      years      sorted list of ints that have results
      matrix     {trophy_name: {year: winner_name}}
      long_rows  [{trophy, year, winner, date, boat}]  (for CSV export)
    The winner of a trophy in a year is the first-place helm of that trophy's
    race(s) that year; if a trophy ran more than once in a year, the most recent
    running is used."""
    conn = db.connect()
    races = conn.execute(
        "SELECT race_id, name, date FROM races WHERE date<>'' ORDER BY date").fetchall()
    matrix: dict[str, dict[int, str]] = {}
    chosen: dict[tuple, tuple] = {}     # (trophy, year) -> (date, winner, boat)
    years = set()
    for ra in races:
        trophy = (ra["name"] or "").strip()
        if not trophy or trophy.upper() in {"(UNNAMED)", "UNKWN", "UNKNOWN", "TEST"}:
            continue
        yr = int(ra["date"][:4])
        win = conn.execute(
            "SELECT member, boat_make FROM results WHERE race_id=? AND status='FIN' "
            "AND position=1 ORDER BY position LIMIT 1", (ra["race_id"],)).fetchone()
        if not win:
            continue
        years.add(yr)
        key = (trophy, yr)
        if key not in chosen or ra["date"] > chosen[key][0]:
            chosen[key] = (ra["date"], win["member"], win["boat_make"] or "")
    conn.close()
    long_rows = []
    for (trophy, yr), (dt, winner, boat) in sorted(chosen.items()):
        matrix.setdefault(trophy, {})[yr] = winner
        long_rows.append({"trophy": trophy, "year": yr, "winner": winner,
                          "date": dt, "boat": boat})
    return sorted(years), matrix, long_rows


# ----------------------------------------------------------------------------- HC trend
def hc_trend(member: str, lookback_months: int = 3) -> str:
    """Arrow for a member's recent handicap movement (lower HC = improving).
      down-arrow  HC fell (got faster / stronger) in the lookback window
      up-arrow    HC rose (eased)
      right-arrow no change
      ''          not enough history
    """
    member = display(member)
    conn = db.connect()
    rows = conn.execute(
        "SELECT period, personal_hc FROM handicap_history WHERE member=? "
        "ORDER BY date_applied DESC, id DESC LIMIT 6", (member,)).fetchall()
    conn.close()
    if len(rows) < 2:
        return ""
    latest = rows[0]["personal_hc"]
    older = rows[min(lookback_months, len(rows) - 1)]["personal_hc"]
    if latest < older:
        return "\u2193"   # improving (handicap reduced)
    if latest > older:
        return "\u2191"
    return "\u2192"


def hc_history_series(months: int = 12) -> tuple[list[str], list[dict]]:
    """Reconstruct each member's personal handicap at the start of each of the
    last `months` calendar months (anchored on the latest race month).

    Returns (periods, series) where periods is ['YYYY-MM', ...] chronological and
    series is one dict per member:
        {name, points:[hc|None per period], current, status, last_raced}
    The point for a month is the most recent handicap_history value dated on or
    before that month (carried forward); None before the member first appears.
    """
    conn = db.connect()
    anchor = conn.execute(
        "SELECT MAX(date) m FROM races WHERE date<>''").fetchone()["m"]
    if not anchor:
        conn.close()
        return [], []
    ay, am = int(anchor[:4]), int(anchor[5:7])
    periods: list[str] = []
    for k in range(months - 1, -1, -1):
        y, mo = ay, am - k
        while mo <= 0:
            y -= 1; mo += 12
        periods.append(f"{y:04d}-{mo:02d}")

    hist: dict[str, list[tuple[str, int]]] = {}
    for r in conn.execute(
            "SELECT member, personal_hc, date_applied FROM handicap_history "
            "ORDER BY date_applied, id"):
        hist.setdefault(r["member"], []).append(
            (r["date_applied"], int(r["personal_hc"])))
    members = [dict(r) for r in conn.execute(
        "SELECT name, personal_hc, status, last_raced FROM members ORDER BY name")]
    conn.close()

    def val_at(h, period):
        cutoff = period + "-31"          # lexical end-of-month for ISO dates
        v = None
        for da, hc in h:
            if da <= cutoff:
                v = hc
            else:
                break
        return v

    series = []
    for m in members:
        h = hist.get(m["name"], [])
        pts = [val_at(h, p) for p in periods]
        # if a member has no history rows at all, show their current HC flat
        if not h:
            pts = [int(m["personal_hc"])] * len(periods)
        current = next((v for v in reversed(pts) if v is not None),
                       int(m["personal_hc"]))
        series.append({"name": m["name"], "points": pts, "current": current,
                       "status": m.get("status", ""),
                       "last_raced": m.get("last_raced", "")})
    return periods, series
