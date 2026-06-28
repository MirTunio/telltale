"""
raceio.py  -  Read the club's per-race CSV files (the all_races format).

Each file is named  NNNN_YYYYMMDD.csv  and looks like:

    RaceDate,RaceNo,RaceName,HelmName,CrewName,Class,Start,Finish,Code,Rating
    08/03/2025,1,1001-SPRING CHALLENGE CUP,ALEX MORGAN,GRACE,CLUB WAYFARER,13:40:00,14:26:57,,1090

We trust the *filename* for the race number and date (the in-file RaceNo is
always 1), parse the trophy from RaceName, and turn each data row into an entry.
Start groups are inferred from the distinct start times.
"""
from __future__ import annotations

import csv
import glob
import os
import re

from . import config
from . import trophies as _trophies

_FN = re.compile(r"(\d+)_(\d{4})(\d{2})(\d{2})\.csv$")


def _iso(datestr: str, fallback: str) -> str:
    datestr = (datestr or "").strip()
    for fmt in ("%m/%d/%Y", "%m/%d/%y", "%Y-%m-%d", "%d/%m/%Y"):
        try:
            import datetime
            return datetime.datetime.strptime(datestr, fmt).strftime("%Y-%m-%d")
        except ValueError:
            continue
    return fallback


def parse_race_file(path: str) -> dict | None:
    m = _FN.search(os.path.basename(path))
    if not m:
        return None
    race_no = int(m.group(1))
    iso_from_name = f"{m.group(2)}-{m.group(3)}-{m.group(4)}"

    rows = []
    race_name = ""
    file_date = ""
    with open(path, newline="", encoding="utf-8-sig") as fh:
        for row in csv.DictReader(fh):
            helm = (row.get("HelmName") or "").strip()
            if not helm:
                continue
            if not race_name:
                race_name = (row.get("RaceName") or "").strip()
                file_date = row.get("RaceDate") or ""
            rows.append(row)
    if not rows:
        return None

    date = _iso(file_date, iso_from_name)
    trophy = _trophies.match_trophy(race_name)
    clean_name = re.sub(r"^\s*\d+\s*-\s*", "", race_name).strip() or "(unnamed)"

    # distinct start times -> start groups (1 = earliest)
    starts = sorted({(r.get("Start") or "").strip() for r in rows
                     if (r.get("Start") or "").strip()})
    grp = {s: i + 1 for i, s in enumerate(starts)}

    entries = []
    for r in rows:
        st = (r.get("Start") or "").strip()
        try:
            rating = float(r.get("Rating")) if (r.get("Rating") or "").strip() else None
        except ValueError:
            rating = None
        entries.append({
            "member": (r.get("HelmName") or "").strip().upper(),
            "crew_name": (r.get("CrewName") or "").strip().upper(),
            "boat_class": (r.get("Class") or "").strip().upper(),
            "start_time": st,
            "finish_time": (r.get("Finish") or "").strip(),
            "code": (r.get("Code") or "").strip().upper(),
            "start_group": grp.get(st, 1),
            "rating": rating,
        })

    return {
        "race_no": race_no,
        "date": date,
        "name": clean_name,
        "race_name_raw": race_name,
        "trophy": trophy.name if trophy else "",
        "trophy_obj": trophy,
        "mode": trophy.mode if trophy else _trophies.STANDARD,
        "num_starts": len(starts) or 1,
        "start_times": ",".join(starts),
        "entries": entries,
    }


def list_races(races_dir: str | None = None) -> list[dict]:
    """All parsed races, sorted chronologically (date, then race number)."""
    races_dir = races_dir or config.RACES_DIR
    out = []
    for f in glob.glob(os.path.join(races_dir, "*.csv")):
        r = parse_race_file(f)
        if r:
            out.append(r)
    out.sort(key=lambda r: (r["date"], r["race_no"]))
    return out


def write_race_file(race: dict, results: list[dict],
                    races_dir: str | None = None) -> str:
    """Write (or refresh) the per-race CSV in raw/races/ in the same all_races
    format the seeder reads, so races scored or edited in the app are saved to
    the raw logs too. One file per race number (NNNN_YYYYMMDD.csv); if the race's
    date changed, the stale file for that number is removed first.

    Rating is written as round(net_h * 10) - the entry's net handicap on the PY
    scale - which is exactly what the importer needs to recover an unknown boat
    class, so a round-trip through the file reproduces the same boat handicap.
    """
    import datetime as _dt
    races_dir = races_dir or config.RACES_DIR
    os.makedirs(races_dir, exist_ok=True)
    rid = int(race.get("race_id") or race.get("race_no") or 0)
    iso = (race.get("date") or "").strip()

    for old in glob.glob(os.path.join(races_dir, f"{rid:04d}_*.csv")):
        try:
            os.remove(old)
        except OSError:
            pass

    compact = iso.replace("-", "")
    path = os.path.join(races_dir, f"{rid:04d}_{compact or '00000000'}.csv")
    try:
        dd = _dt.date.fromisoformat(iso)
        racedate = f"{dd.month}/{dd.day}/{dd.year}"     # m/d/Y, matches the archive
    except ValueError:
        racedate = iso
    name = (race.get("name") or "").strip()
    race_name = f"{rid}-{name}" if name else f"{rid}-"

    with open(path, "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["RaceDate", "RaceNo", "RaceName", "HelmName", "CrewName",
                    "Class", "Start", "Finish", "Code", "Rating"])
        for r in results:
            net = r.get("net_h")
            rating = "" if net in (None, "") else str(int(round(float(net) * 10)))
            w.writerow([racedate, 1, race_name,
                        (r.get("member") or "").upper(),
                        (r.get("crew_name") or "").upper(),
                        (r.get("boat_sail_no") or "").upper(),
                        r.get("start_time") or "",
                        r.get("finish_time") or "",
                        (r.get("code") or "").upper(),
                        rating])
    return path
