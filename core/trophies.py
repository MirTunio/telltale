"""
trophies.py  -  Example trophy register, scoring rules and the calendar.

Every trophy carries:
  * mode        - the recommended scoring mode (standard / boat_only / one_design)
  * ladies      - True if the Ilse +3/+2 lady-helm advantage applies
  * series      - True if it is an annual series
  * explain     - a one-line plain-English description of the handicap scheme,
                  shown to the operator before a race so they know the default
                  (and can override it).

The names the old data uses are a mess (GRAY BURN / CORIANTHIAN / TOMTIN / MARY
MUDI ...), so match_trophy() normalises and fuzzy-matches onto the canonical
names from the rulebook (pp. 78-93).

Pure data + helpers, no I/O.
"""
from __future__ import annotations

import csv
import datetime as _dt
import os
import re
from dataclasses import dataclass

from . import config

STANDARD = "standard"
BOAT_ONLY = "boat_only"
ONE_DESIGN = "one_design"


@dataclass(frozen=True)
class Trophy:
    name: str
    mode: str = STANDARD
    ladies: bool = False          # lady-helm advantage (+3 / +2, capped)
    series: bool = False
    explain: str = "Standard club handicap: boat + personal + crew."
    year: int | None = None       # year first presented (rulebook pp.78-93); None = unknown
    discontinued: bool = False     # no longer raced (kept on the register for history)
    # --- v6: editable scoring rules + calendar + history (config/reference/trophies.csv) ---
    when: str = ""                # year-less calendar spec, e.g. "3rd Sunday of October" / "14 August"
    note: str = ""                # historical note (from the Trophy digest); shown everywhere
    crew_only: bool = False        # scored for the crew (e.g. Crews Cup) / crew helms
    tindal: bool = False           # tindals helm; committee-set staggered starts
    ladies_adv: int = 0            # +N helm advantage for a lady helm
    crew_lady_bonus: int = 0       # extra +N if the crew is also a lady
    ladies_cap: int = 5            # max combined ladies advantage
    series_races: int = 0          # races in the annual series (example = 12)
    discards: int = 0              # discards allowed in the series (example = 3)
    min_races: int = 0             # min races to qualify (example = 8)

    def effective_note(self) -> str:
        return self.note or self.explain


# Re-usable one-liners -------------------------------------------------------
_STD = "Standard club handicap: boat + personal + crew."
_BOAT = "Boat handicaps only - personal and crew handicaps are not applied."
_TINDAL = ("Tindals only - handicap is applied through committee-set staggered "
           "starts, so it is scored on elapsed time (one-design).")

# Example trophy register ----------------------------------------------------
# A GENERIC set of example trophies that exercises every scoring mode Telltale
# supports. Replace these with your own club's trophies (and edit calendar dates
# and rules in config/reference/trophies.csv, which overrides this list by name).
#
#   mode=STANDARD    boat + personal + crew handicaps (the default)
#   mode=BOAT_ONLY   boat handicaps only (personal & crew not applied)
#   mode=ONE_DESIGN  scored on elapsed time (handicap via staggered starts)
#   ladies=True      lady-helm advantage (+ladies_adv, +crew_lady_bonus, capped)
#   series=True      an annual low-point series (series_races/discards/min_races)
#   crew_only=True   scored for the crew rather than the helm
#
# `year` is just the (fictional) year the trophy was "first presented" - shown on
# the register; set it or leave it None. `discontinued=True` keeps a trophy on the
# register for history without wiring it into the active calendar.
#
TROPHIES: list[Trophy] = [
    # --- standard club races ---
    Trophy("SPRING CHALLENGE CUP", year=1962,
           explain="Standard club handicap: boat + personal + crew."),
    Trophy("AUTUMN CHALLENGE CUP", year=1965),
    Trophy("HARBOUR CUP", year=1968, explain="Long-distance harbour race; standard handicap."),
    Trophy("FOUNDERS TROPHY", year=1958),
    Trophy("MIDWINTER CUP", year=1971),
    Trophy("REGATTA ROSE BOWL", year=1974),
    Trophy("NOVICE CUP", year=1966, explain="Novice / junior helms; standard handicap."),
    Trophy("VETERANS TROPHY", explain="Veteran helms; standard handicap."),
    # --- boat-handicap-only ---
    Trophy("KEELBOAT TRAY", year=1964, mode=BOAT_ONLY, explain=_BOAT),
    Trophy("COMMODORE'S MEDAL", year=1977, mode=BOAT_ONLY, explain=_BOAT),
    # --- one-design (elapsed time / staggered starts) ---
    Trophy("ONE-DESIGN CUP", year=1953, mode=ONE_DESIGN, explain=_TINDAL),
    # --- ladies ---
    Trophy("LADIES CHALLENGE CUP", year=1925,
           explain="Lady helms only; standard handicap."),
    Trophy("MEMORIAL LADIES TROPHY", year=1949, ladies=True, ladies_adv=3,
           crew_lady_bonus=2, ladies_cap=5,
           explain="Standard handicap, plus +3 for a lady helm and +2 more if the "
                   "crew is also a lady (capped at +5)."),
    # --- annual series ---
    Trophy("SEASON GOLD MEDAL", year=1983, mode=BOAT_ONLY, series=True,
           series_races=12, discards=3, min_races=8,
           explain="Boat handicaps only; 12-race annual series, 3 discards, 8 to count."),
    Trophy("CLUB CHAMPIONSHIP", year=1980, series=True,
           explain="All classes; standard handicap; sailed as an annual series."),
    # --- crew-racing ---
    Trophy("CREW CUP", year=1958, mode=BOAT_ONLY, crew_only=True,
           explain="Awarded to the regular crew of the boat scoring lowest in the "
                   "season series. Boat handicaps only."),
    # --- a discontinued example (kept for history) ---
    Trophy("LEGACY SPONSOR CUP", discontinued=True,
           explain="A former sponsor's cup, kept on the register but no longer sailed."),
]

BY_NAME = {t.name: t for t in TROPHIES}

# Explicit aliases for spellings the fuzzy matcher would otherwise miss.
ALIASES = {
    # Spellings/short forms the fuzzy matcher might otherwise miss. Add your own
    # as needed (left = substring seen in a race name, right = canonical trophy).
    "CREW": "CREW CUP",
    "COMMODORE": "COMMODORE'S MEDAL",
    "COMMADORE": "COMMODORE'S MEDAL",
    "ONE DESIGN": "ONE-DESIGN CUP",
    "ONEDESIGN": "ONE-DESIGN CUP",
    "GOLD MEDAL": "SEASON GOLD MEDAL",
    "CHAMPIONSHIP": "CLUB CHAMPIONSHIP",
}

_NOISE = {"CUP", "TROPHY", "CHALLENGE", "TRAY", "BOWL", "JUG", "MUG", "SPOON",
          "MEDAL", "GOLD", "MEMORIAL", "SERIES", "THE", "ROSE", "CLUB",
          "PROVISIONAL", "S"}


def _norm(s: str) -> str:
    s = (s or "").upper()
    s = re.sub(r"^\s*\d+\s*-\s*", "", s)          # strip leading 'NNN-'
    s = re.sub(r"\(.*?\)", " ", s)                # drop bracketed bits
    s = re.sub(r"[^A-Z0-9 ]", " ", s)             # punctuation -> space
    s = re.sub(r"\bSERIES\b.*$", "", s)           # 'COMMODORE SERIES 5' -> 'COMMODORE'
    s = re.sub(r"\bTROPHY\b\s*\d+.*$", "", s)     # 'COMMODORE TROPHY 6' -> 'COMMODORE'
    return re.sub(r"\s+", " ", s).strip()


def _tokens(s: str) -> set[str]:
    return {w for w in _norm(s).split() if w not in _NOISE and len(w) > 1}


def match_trophy(raw: str) -> Trophy | None:
    """Best-effort map a raw/typo'd race name onto a canonical trophy."""
    if not raw:
        return None
    n = _norm(raw)
    if not n:
        return None
    # 1. alias table (substring)
    for key, canon in ALIASES.items():
        if key in n:
            return _apply_config(BY_NAME.get(canon))
    # 2. exact normalised
    for t in TROPHIES:
        if _norm(t.name) == n:
            return _apply_config(t)
    # 3. token-overlap score
    rt = _tokens(raw)
    if not rt:
        return None
    best, best_score = None, 0.0
    for t in TROPHIES:
        tt = _tokens(t.name)
        if not tt:
            continue
        inter = len(rt & tt)
        if inter == 0:
            continue
        score = inter / max(len(rt), len(tt))
        if score > best_score:
            best, best_score = t, score
    return _apply_config(best) if best_score >= 0.5 else None


def find_matches(query: str, limit: int = 8) -> list[Trophy]:
    """Type-ahead style ranking for the trophy picker."""
    q = _norm(query)
    if not q:
        return [_apply_config(t) for t in TROPHIES[:limit]]
    qt = _tokens(query)
    scored = []
    for t in TROPHIES:
        nm = _norm(t.name)
        if nm.startswith(q):
            s = 3.0
        elif q in nm:
            s = 2.0
        else:
            tt = _tokens(t.name)
            inter = len(qt & tt) if qt else 0
            s = inter / max(len(qt or {1}), len(tt or {1})) if inter else 0.0
        if s > 0:
            scored.append((s, t))
    scored.sort(key=lambda x: (-x[0], x[1].name))
    return [_apply_config(t) for _, t in scored[:limit]]


# ---- editable config (config/reference/trophies.csv) ----------------------
# One hand-editable row per trophy: scoring rules + year-less calendar + the
# historical note shown in the CLI, the web UI, the scoring screen and printed
# under the PNG results. Loaded lazily and overlaid onto the code defaults.
_CONFIG: dict | None = None
_CONFIG_MTIME: float = 0.0

_BOOL = {"1": True, "0": False, "true": True, "false": False, "yes": True,
         "no": False, "y": True, "n": False, "": None}


def _cfg_path() -> str:
    return os.path.join(config.REFERENCE_DIR, "trophies.csv")


def _load_config() -> dict:
    """norm-name -> dict of overrides read from config/reference/trophies.csv."""
    global _CONFIG, _CONFIG_MTIME
    p = _cfg_path()
    try:
        mt = os.path.getmtime(p)
    except OSError:
        _CONFIG = {}
        return _CONFIG
    if _CONFIG is not None and mt == _CONFIG_MTIME:
        return _CONFIG
    out: dict = {}
    with open(p, newline="", encoding="utf-8-sig") as fh:
        for row in csv.DictReader(fh):
            name = (row.get("Trophy") or "").strip()
            if not name:
                continue
            o: dict = {}
            mode = (row.get("Mode") or "").strip().lower()
            if mode in (STANDARD, BOAT_ONLY, ONE_DESIGN):
                o["mode"] = mode
            for col, field in (("CrewOnly", "crew_only"), ("Tindal", "tindal")):
                b = _BOOL.get((row.get(col) or "").strip().lower())
                if b is not None:
                    o[field] = b
            for col, field in (("LadiesAdv", "ladies_adv"), ("CrewLadyBonus", "crew_lady_bonus"),
                               ("LadiesCap", "ladies_cap"), ("SeriesRaces", "series_races"),
                               ("Discards", "discards"), ("MinRaces", "min_races")):
                v = (row.get(col) or "").strip()
                if v:
                    try:
                        o[field] = int(float(v))
                    except ValueError:
                        pass
            if o.get("ladies_adv"):
                o["ladies"] = True
            if o.get("series_races") or o.get("discards"):
                o["series"] = True
            when = (row.get("When") or "").strip()
            if when:
                o["when"] = when
            note = (row.get("Note") or "").strip()
            if note:
                o["note"] = note
            o["_display"] = name
            out[_norm(name)] = o
    _CONFIG, _CONFIG_MTIME = out, mt
    return out


def _apply_config(t: Trophy | None) -> Trophy | None:
    if t is None:
        return None
    o = _load_config().get(_norm(t.name))
    if not o:
        return t
    import dataclasses
    fields = {f.name for f in dataclasses.fields(Trophy)}
    clean = {k: v for k, v in o.items() if k in fields}
    return dataclasses.replace(t, **clean) if clean else t


# ---- calendar / next upcoming trophy --------------------------------------
_MONTHS = {m: i for i, m in enumerate(
    ["", "JANUARY", "FEBRUARY", "MARCH", "APRIL", "MAY", "JUNE", "JULY",
     "AUGUST", "SEPTEMBER", "OCTOBER", "NOVEMBER", "DECEMBER"])}
_MON3 = {m[:3]: i for m, i in _MONTHS.items() if m}
_NTH = {"first": 1, "1st": 1, "second": 2, "2nd": 2, "third": 3, "3rd": 3,
        "fourth": 4, "4th": 4, "fifth": 5, "5th": 5, "last": -1}


def _nth_sunday(year: int, month: int, nth: int) -> _dt.date:
    if nth == -1:                                   # last Sunday of the month
        d = _dt.date(year, month, 28)
        while (d + _dt.timedelta(days=7)).month == month:
            d += _dt.timedelta(days=7)
        return d - _dt.timedelta(days=(d.weekday() - 6) % 7)
    d = _dt.date(year, month, 1)
    offset = (6 - d.weekday()) % 7                   # weekday(): Mon=0 .. Sun=6
    return d + _dt.timedelta(days=offset + 7 * (nth - 1))


def parse_when(spec: str):
    """Parse a year-less calendar spec. Returns
       ('nth', nth, month)  e.g. '3rd Sunday of October'
       ('fixed', day, month) e.g. '14 August' / 'August 14'
       or None if unparseable."""
    s = (spec or "").strip().lower()
    if not s:
        return None
    # nth weekday of month
    m = re.match(r"(first|second|third|fourth|fifth|last|[1-5](?:st|nd|rd|th)?)\s+"
                 r"sun(?:day)?\s+(?:of\s+|in\s+)?([a-z]+)", s)
    if m:
        nth = _NTH.get(m.group(1))
        mon = _MONTHS.get(m.group(2).upper()) or _MON3.get(m.group(2)[:3].upper())
        if nth and mon:
            return ("nth", nth, mon)
    # fixed date: "14 august" or "august 14" (ignore any ordinal suffix)
    m = re.match(r"(\d{1,2})(?:st|nd|rd|th)?\s+([a-z]+)$", s)
    if m:
        day = int(m.group(1)); mon = _MONTHS.get(m.group(2).upper()) or _MON3.get(m.group(2)[:3].upper())
        if mon and 1 <= day <= 31:
            return ("fixed", day, mon)
    m = re.match(r"([a-z]+)\s+(\d{1,2})(?:st|nd|rd|th)?$", s)
    if m:
        mon = _MONTHS.get(m.group(1).upper()) or _MON3.get(m.group(1)[:3].upper()); day = int(m.group(2))
        if mon and 1 <= day <= 31:
            return ("fixed", day, mon)
    return None


def _when_date(spec: str, year: int):
    p = parse_when(spec)
    if not p:
        return None
    try:
        if p[0] == "nth":
            return _nth_sunday(year, p[2], p[1])
        return _dt.date(year, p[2], p[1])
    except ValueError:
        return None


def load_calendar(path: str | None = None) -> list[dict]:
    """Calendar rows {trophy, when}. Reads config/reference/trophies.csv (When
    column); falls back to the legacy trophy_calendar.csv (Pattern/Month)."""
    cfg = _load_config()
    out = [{"trophy": o.get("_display", k), "when": o["when"]}
           for k, o in cfg.items() if o.get("when")]
    if out:
        return out
    legacy = path or os.path.join(config.REFERENCE_DIR, "trophy_calendar.csv")
    if os.path.exists(legacy):
        with open(legacy, newline="", encoding="utf-8-sig") as fh:
            for row in csv.DictReader(fh):
                pat = (row.get("Pattern") or "").strip().lower().replace("_sunday", "")
                mon = _MONTHS.get((row.get("Month") or "").strip().upper())
                nth = {"first": 1, "second": 2, "third": 3, "fourth": 4, "fifth": 5}.get(pat)
                if mon and nth:
                    out.append({"trophy": (row.get("Trophy") or "").strip(),
                                "when": f"{('first second third fourth fifth'.split()[nth-1])} Sunday of "
                                        f"{list(_MONTHS)[mon].title()}"})
    return out


def next_trophy(today: _dt.date | None = None, path: str | None = None) -> dict | None:
    """The soonest scheduled trophy on/after `today`, with its date and rule."""
    today = today or _dt.date.today()
    cal = load_calendar(path)
    if not cal:
        return None
    candidates = []
    for yr in (today.year, today.year + 1):
        for ev in cal:
            d = _when_date(ev["when"], yr)
            if d and d >= today:
                candidates.append((d, ev))
    if not candidates:
        return None
    candidates.sort(key=lambda x: x[0])
    d, ev = candidates[0]
    return {"date": d, "name_raw": ev["trophy"], "trophy": match_trophy(ev["trophy"]),
            "days_away": (d - today).days, "when": ev["when"]}


def upcoming_trophies(today: _dt.date | None = None, limit: int = 12) -> list[dict]:
    """Next `limit` scheduled trophies, soonest first (for the calendar view)."""
    today = today or _dt.date.today()
    cal = load_calendar()
    seen = []
    for yr in (today.year, today.year + 1, today.year + 2):
        for ev in cal:
            d = _when_date(ev["when"], yr)
            if d and d >= today:
                t = match_trophy(ev["trophy"])
                seen.append({"date": d, "name_raw": ev["trophy"], "trophy": t,
                             "when": ev["when"], "days_away": (d - today).days})
    seen.sort(key=lambda x: x["date"])
    # de-dup by trophy name (keep soonest)
    out, used = [], set()
    for s in seen:
        key = _norm(s["name_raw"])
        if key in used:
            continue
        used.add(key); out.append(s)
        if len(out) >= limit:
            break
    return out
