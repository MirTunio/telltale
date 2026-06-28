"""
config.py  -  Paths and tunable settings for Telltale.

Everything lives under the application directory so the whole folder can sit in
a Google Drive / OneDrive / Dropbox folder for automatic cloud backup.
"""
from __future__ import annotations

import os

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# --- source inputs (hand-edited or immutable) -------------------------------
RAW_DIR = os.path.join(BASE_DIR, "raw")                 # source race files + archives
RACES_DIR = os.path.join(RAW_DIR, "races")              # all_races CSVs for seeding
CONFIG_DIR = os.path.join(BASE_DIR, "config")           # all editable configuration
REFERENCE_DIR = os.path.join(CONFIG_DIR, "reference")   # seed source: helm/boat/crew HC + calendar
EMAIL_CONFIG_PATH = os.path.join(CONFIG_DIR, "email_config.ini")
SETTINGS_FILE = os.path.join(CONFIG_DIR, "settings.csv")  # human-editable settings mirror

# --- derived store (regenerable from raw + config) --------------------------
DATA_DIR = os.path.join(BASE_DIR, "data")
DB_PATH = os.path.join(DATA_DIR, "telltale.db")
CSV_DIR = os.path.join(DATA_DIR, "csv")                 # the live "current mirror"
BACKUP_DIR = os.path.join(DATA_DIR, "backups")          # .db backups
CSV_SNAPSHOT_DIR = os.path.join(BACKUP_DIR, "csv")      # timestamped CSV snapshots

# --- generated artefacts ----------------------------------------------------
RACE_RESULTS_DIR = os.path.join(BASE_DIR, "race_results")  # computed race result images
OUTPUTS_DIR = os.path.join(BASE_DIR, "outputs")         # user reports/queries, timestamped
DOCS_DIR = os.path.join(BASE_DIR, "docs")
ASSETS_DIR = os.path.join(BASE_DIR, "assets")           # bundled fonts, banners, brand
FONTS_DIR = os.path.join(ASSETS_DIR, "fonts")           # DejaVuSans (full glyph set)
BANNER_DIR = os.path.join(ASSETS_DIR, "banners")        # CLI splash + home-screen art

for d in (DATA_DIR, CSV_DIR, RACE_RESULTS_DIR, OUTPUTS_DIR, BACKUP_DIR, CSV_SNAPSHOT_DIR,
          RAW_DIR, RACES_DIR, REFERENCE_DIR, DOCS_DIR, CONFIG_DIR):
    os.makedirs(d, exist_ok=True)

# ---- defaults stored in the settings table (editable in the app) -----------
DEFAULT_SETTINGS = {
    "club_name": "EXAMPLE SAILING CLUB",
    "venue": "EXAMPLE BAY",
    "hc_cap": "2",              # max personal-HC change per monthly update
    "hc_min_races": "2",        # races needed in a month to qualify
    "novice_initial_hc": "5",   # complete-novice starting personal handicap
    "member_initial_hc": "0",   # ordinary new-member starting handicap
    "inactive_months": "6",     # months without a race -> flagged Inactive
    "max_backups": "50",
    "scoring_base": "100",      # the "x 100" in the corrected-time formula
}

# ---- settings introduced by this build (seeded if missing) -----------------
EXTRA_SETTINGS = {
    "default_start_times": "13:30,13:35,13:40,13:45",
    "boat_select_by": "class",            # future option: "sail_no"
    "min_competitors": "3",
    "wind_directions": "N,NE,E,SE,S,SW,W,NW",
    # awards qualification (see core/awards.py) -- all adjustable here
    "award_min_month": "3",               # min races to qualify for a month award
    "award_season_per_month": "2",        # season min = this x months-in-season
    "award_min_year": "20",               # min races to qualify for a year award
    # winter handicap suggestion for catamarans (wind-based, not calendar):
    # below this recorded wind the WINTER rating is recommended, at/above it the
    # standard rating. ~12 kt is a typical threshold where a catamaran's speed edge sets in.
    "winter_wind_threshold": "12",        # recommend winter rig below this wind (kt)
    # publishing
    "auto_email": "ask",                  # off | ask | auto
    "email_recipients": "results@example.org",
    "whatsapp_number": "",   # optional: e.g. +10000000000 for the click-to-send link
    # the marker that drives the forced month-by-month HC update on startup
    "hc_updated_through": "",             # 'YYYY-MM' of the last applied update
}

# Trophies scored with "boat handicaps only" (kept in sync with the trophy
# register in core/trophies.py / config/reference/trophies.csv).
BOAT_ONLY_TROPHIES = {
    "KEELBOAT TRAY", "COMMODORE'S MEDAL", "SEASON GOLD MEDAL", "CREW CUP",
}

RESULT_CODES = ["DNF", "DNS", "DNC", "DSQ", "OCS", "RET", "DNE"]

# ---- Example monthly average wind (knots) ----------------------------------
# Used to suggest multihull "winter" (light-air) handicaps when no wind speed is
# recorded, and for wind-themed fun facts. Light-wind months (< winter_wind_threshold)
# are where a fast catamaran is genuinely slowed and the light-air rating is fair.
# These are placeholder values - edit to match your venue's seasonal wind.
MONTHLY_WIND_KT = {
    1: 2, 2: 2, 3: 4, 4: 6, 5: 8, 6: 8,
    7: 8, 8: 8, 9: 6, 10: 4, 11: 2, 12: 2,
}

# ---- Seasons (3 months each; editable conceptually, defaults below) --------
# Winter spans the low-wind months, which is exactly when the catamaran winter
# handicap matters; the four seasons tile the calendar year.
SEASONS = {
    "Winter":  (11, 12, 1),
    "Spring":  (2, 3, 4),
    "Summer":  (5, 6, 7),
    "Monsoon": (8, 9, 10),
}


# --------------------------------------------------------------------------- about / brand (task 3,4,5)
ABOUT_TEXT = (
    "Telltale - a sailing race and regatta scoring system.\n"
    "Rulebook-faithful base-100 corrected-time scoring with monthly\n"
    "personal-handicap updates, trophy-aware series, awards and reports.\n"
    "\n"
    "Released under the MIT License - free to use, modify and distribute."
)
BRAND_PURPLE = "#472472"
BRAND_GOLD = "#E5AD10"

# Venue coordinates used only for the OPTIONAL live wind-speed *suggestion* on
# the wind prompt (via the Open-Meteo public API). The on-water reading is always
# authoritative. Set these to your club's start area (decimal degrees), or leave
# as-is to disable the suggestion's usefulness. Example below is a placeholder.
VENUE_LAT = 0.0
VENUE_LON = 0.0
