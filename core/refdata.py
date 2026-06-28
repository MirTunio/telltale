"""
refdata.py  -  Load the authoritative handicap reference lists.

The club's master handicaps live in three spreadsheets that were exported to
CSV under reference/ during setup, already converted from the modified RYA-PY
scale to the club's base-100 scale (base-100 = round(PY / 10)).

  reference/helm_hc.csv   helm, hc_base100, hc_py      (personal handicaps)
  reference/boat_hc.csv   class, hc_base100, hc_py      (one HC per class/sub-class)
  reference/crew_hc.csv   crew, hc_base100, hc_py       (fixed list incl. categories)

Boat handicaps are per class / sub-class (e.g. WAYFARER vs WAYFARER_VINTAGE,
etc.). Crew handicaps are a fixed hand-maintained list and are never updated by
the monthly process.
"""
from __future__ import annotations

import csv
import os

from . import config


def _load(path: str, key_col: int = 0, val_col: int = 1) -> dict[str, int]:
    out: dict[str, int] = {}
    if not os.path.exists(path):
        return out
    with open(path, newline="", encoding="utf-8-sig") as fh:
        r = csv.reader(fh)
        next(r, None)  # header
        for row in r:
            if len(row) <= max(key_col, val_col) or not row[key_col].strip():
                continue
            try:
                out[row[key_col].strip().upper()] = int(round(float(row[val_col])))
            except ValueError:
                pass
    return out


def load_helm_hc() -> dict[str, int]:
    return _load(os.path.join(config.REFERENCE_DIR, "helm_hc.csv"))


def load_boat_hc() -> dict[str, int]:
    return _load(os.path.join(config.REFERENCE_DIR, "boat_hc.csv"))


def load_crew_hc() -> dict[str, int]:
    return _load(os.path.join(config.REFERENCE_DIR, "crew_hc.csv"))


def load_helm_gender() -> dict[str, str]:
    """Optional helm gender from helm_hc.csv (a 'gender' column: '', 'M' or 'F').

    Used only to pre-populate the lady-helm trophies with data. Entirely
    optional - if the column is absent, everyone is seeded ungendered ('') and
    you set gender per sailor in the app.
    """
    path = os.path.join(config.REFERENCE_DIR, "helm_hc.csv")
    out: dict[str, str] = {}
    if not os.path.exists(path):
        return out
    with open(path, newline="", encoding="utf-8-sig") as fh:
        for row in csv.DictReader(fh):
            name = (row.get("helm") or "").strip().upper()
            g = (row.get("gender") or "").strip().upper()[:1]
            if name and g in ("M", "F"):
                out[name] = g
    return out


# Crew "categories" that aren't real people (shown first in the crew picker).
CREW_CATEGORIES = ["NOCREW", "GUEST", "MEMBER", "EXP_MEMBER", "IN_TRAINING"]


def class_display(raw: str) -> str:
    """'CLUB WAYFARER_CLASSIC' -> 'Wayfarer (Classic)'  for friendly display."""
    s = (raw or "").strip()
    # Strip an optional "CLUB " prefix ("CLUB Wayfarer" -> "Wayfarer") for display.
    if s.upper().startswith("CLUB "):
        s = s[5:]
    sub = ""
    for tag in ("_VINTAGE", "_CLASSIC", "_WINTER"):
        if s.upper().endswith(tag):
            sub = tag[1:].title()
            s = s[: -len(tag)]
            break
    s = s.replace("_", " ").strip()
    # tidy a few known names
    pretty = {"ILCA 7 / LASER": "ILCA 7 / Laser", "RS 400": "RS 400",
              "MERLIN-ROCKET": "Merlin-Rocket", "MUSTO SKIFF": "Musto Skiff"}.get(
        s.upper(), s.title())
    return f"{pretty} ({sub})" if sub else pretty


# ---------------------------------------------------------------------------
# Hull type, winter handicaps, and seasons  (added in the v2 feature build)
# ---------------------------------------------------------------------------
from . import config as _config  # noqa: E402

# Catamaran classes ("double hull"). Matched by substring so the
# _WINTER sub-classes are caught too.
MULTIHULL_KEYS = ("NACRA", "HOBIE")


def hull_of(class_key: str) -> str:
    """'multi' for catamarans (Nacra/Hobie), else 'mono'. Case-insensitive."""
    k = (class_key or "").upper()
    return "multi" if any(tag in k for tag in MULTIHULL_KEYS) else "mono"


def is_multihull(class_key: str) -> bool:
    return hull_of(class_key) == "multi"


def hull_label(hull: str) -> str:
    return "Multihull (double hull)" if hull == "multi" else "Monohull"


def base_class(class_key: str) -> str:
    """Strip a trailing _WINTER tag -> the base class key."""
    k = (class_key or "").strip()
    return k[:-7] if k.upper().endswith("_WINTER") else k


def winter_variant(class_key: str) -> str:
    """The _WINTER class key for a base class (whether or not it exists)."""
    return base_class(class_key) + "_WINTER"


def typical_wind(month: int) -> int:
    """Example long-run average wind (kt) for a calendar month (1-12)."""
    return _config.MONTHLY_WIND_KT.get(int(month), 6)


def should_suggest_winter(class_key: str, month: int | None,
                          windspeed: float | None,
                          threshold: float = 12.0) -> bool:
    """True when a catamaran should be put on its winter handicap.

    Winter handicaps exist so a fast catamaran (low base HC) is not over-
    penalised in light air: in light wind it is genuinely slower, so the higher
    winter rating is the fair one. The decision follows the *wind*, not the
    calendar:
      * if a wind speed was recorded (including a dead-calm 0 kt), winter when
        it is below `threshold` kt;
      * only when no wind was recorded at all do we fall back to the season
        (the low-wind winter months), since the monthly averages sit on a
        lighter scale than real on-water readings.
    """
    if not is_multihull(class_key):
        return False
    if windspeed is not None:                 # 0 kt (dead calm) is valid & light
        return float(windspeed) < float(threshold)
    if month is not None:
        return season_of(int(month)) == "Winter"
    return False


def season_of(month: int) -> str:
    """Which configured season a calendar month falls in."""
    for name, months in _config.SEASONS.items():
        if int(month) in months:
            return name
    return ""


def season_months(season: str) -> tuple[int, ...]:
    return _config.SEASONS.get(season, ())
