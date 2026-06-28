# Telltale

**Classic sailing-club race scoring and personal-handicap management.**

Telltale scores dinghy and catamaran races using a base-100 corrected-time
system, rolls each sailor's **personal handicap** forward month by month, handles
trophy-specific scoring rules, low-point series, the monohull/multihull split,
season awards, and produces clean, shareable **PNG/PDF result sheets**.

It runs as a friendly text menu (no install beyond Python + Pillow) and ships with
an optional local **web UI**. All data lives in plain files inside the project
folder, so you can keep the whole thing in a synced folder (Drive/OneDrive/Dropbox)
or a git repo and have human-readable backups for free.

> The repository ships with a **fictional example club** ("Example Sailing Club")
> so you can run everything immediately. None of the sailors, boats, or races are
> real. See [Using your own data](#using-your-own-data) to swap in yours.

---

## Quick start

You need **Python 3.9+** and one package (**Pillow**).

```bash
# 1. clone and enter
git clone https://github.com/mir-t/telltale.git
cd telltale

# 2. install the one dependency
pip install -r requirements.txt

# 3. run it
python telltale.py
```

On first launch Telltale notices the database is empty and offers to **build it
from the example reference data + race archive**. Say yes and you land in the main
menu with ~25 sailors, 14 boat classes, and 40 scored races ready to explore.

**Even quicker:**

| Platform | Command line | Web UI |
|----------|--------------|--------|
| macOS / Linux | `./run.sh` | `./run_web.sh` |
| Windows | double-click `run.bat` | double-click `run_web.bat` |

The web UI opens at `http://127.0.0.1:8765`. The CLI and web UI share the same
database — use whichever you like.

---

## What it does

* **Rulebook-faithful scoring.** Corrected time = `elapsed × base / net-handicap`
  (base 100 by default), lowest wins. Non-finishers (DNF/DNS/DNC/DSQ…) are scored
  per the usual "finishers + 1" convention.
* **Monthly personal handicaps.** Each calendar month, a sailor who raced enough
  times gets nudged by the rounded average of their deviations, capped at ±2.
  New sailors enter at 0 and converge. The whole history is stored and auditable.
* **Trophy-aware.** A master trophy register (`config/reference/trophies.csv`)
  defines each trophy's calendar date and scoring rules — boat-handicap-only
  events, lady-helm advantages, crew-only races, series with discards, and so on.
* **Monohull / multihull split.** Catamarans (Hobie/Nacra) are scored as their own
  fleet, with an optional light-air ("winter") rating that follows the recorded
  wind rather than the calendar.
* **Series & awards.** Low-point series with discards, progressive series tables,
  month/season/year awards with configurable qualification thresholds.
* **Shareable output.** Every result, handicap list, honours board, and series
  table renders to a clean PNG (and series to multi-page PDF) in `outputs/` and
  `race_results/`, ready to drop into WhatsApp or e-mail.
* **Optional e-mail publishing.** Point it at any SMTP mailbox and "Publish" mails
  the result sheet to a distribution list. Ships **disabled** and never blocks a
  save if e-mail isn't configured.
* **Optional live wind.** If your venue coordinates are set, the wind prompt can
  pre-fill a live suggestion from the public Open-Meteo API (purely a convenience).

---

## How scoring works (the short version)

Everything is on a **base-100** scale where lower = faster. A boat, a helm
(personal), and a crew each contribute a handicap; they combine into a **net
handicap** per entry. Corrected time is

```
corrected = elapsed_seconds × 100 / net_handicap
```

and the lowest corrected time wins. After each month, every qualifying helm's
personal handicap moves by `round(average deviation)`, capped at ±2.

The full, precise statement of the maths — scales, the PY↔base-100 conversion,
the monthly update, trophy modes, and the multihull rule — is in
[`docs/METHOD.md`](docs/METHOD.md).

---

## Daily use

The main menu:

```
1. Score a Race
2. Monthly Handicap Update
3. Members, Boats, Crew & Trophies
4. Reports
5. Series / Trophy Scoring
6. Backup / Data / Settings
0. Exit
```

A typical week: pick **Score a Race**, choose the trophy (or a plain club race),
enter the wind, then add finishers — helm and boat names auto-complete and
fuzzy-match against your roster. Telltale scores it, shows the result, writes the
PNG, and optionally publishes it. Once a month, **Monthly Handicap Update** applies
the ±2 personal-handicap adjustments. Everything else (members, boats, trophies,
series, reports, settings, backups) hangs off the other menu items.

---

## Project layout

```
telltale/
├── telltale.py            the command-line app (menu orchestrator)
├── run.sh / run.bat       launch the CLI
├── run_web.sh / run_web.bat   launch the local web UI
├── requirements.txt       one dependency: Pillow
│
├── core/                  the engine — small, single-purpose modules
│   ├── scoring.py         corrected-time scoring for one race
│   ├── handicap.py        personal-handicap maths
│   ├── walkforward.py     replay races month-by-month, roll handicaps forward
│   ├── series.py / series_progressive.py   low-point & progressive series
│   ├── trophies.py        the trophy register and per-trophy rules
│   ├── awards.py          month/season/year awards
│   ├── funfacts.py        result-sheet fun facts
│   ├── report.py          all PNG/PDF rendering (Pillow)
│   ├── raceio.py          read the per-race CSV files
│   ├── refdata.py         read the reference handicap sheets
│   ├── repository.py      data access over the store
│   ├── db.py              SQLite schema + the CSV mirror
│   ├── seed.py            build the whole store from reference + races
│   ├── mailer.py          optional SMTP publishing
│   └── …                  config, names, timeutil, wind_api
│
├── telltale_webui/        optional local web interface (stdlib http.server)
│
├── config/                ← everything you edit by hand
│   ├── settings.csv       every tunable as key,value
│   ├── email_config.ini   optional SMTP (ships disabled)
│   └── reference/         the SEED source (see below)
│
├── raw/races/             one CSV per race — the race archive that gets replayed
├── data/                  the live store: telltale.db + csv/ mirror + backups/
├── outputs/               generated reports & queries (timestamped)
├── race_results/          generated race-result images
├── assets/                bundled fonts + neutral brand placeholders
└── docs/                  METHOD.md and supporting docs
```

### The two kinds of data

Telltale draws a clean line between **source inputs** you edit and the
**derived store** it generates:

* **`config/reference/` + `raw/races/`** — the source of truth. Reference sheets
  hold starting personal handicaps, boat-class handicaps, the crew list, and the
  trophy register; `raw/races/` holds one CSV per race.
* **`data/`** — fully regenerable. The SQLite database and its CSV mirror are
  built from the sources by `core/seed.py`. Delete `data/telltale.db` any time and
  rebuild from **Backup / Data / Settings → Rebuild from reference data** (or
  `python -m core.seed`).

This is why the example data is safe and easy to replace: change the sources,
rebuild, done.

---

## Using your own data

1. **Settings.** Edit `config/settings.csv` — set `club_name`, `venue`, the
   handicap rules (`hc_cap`, `hc_min_races`, `novice_initial_hc`, …), and award
   thresholds. (You can also change all of these inside the app.)

2. **Sailors.** Replace `config/reference/helm_hc.csv` with your roster:
   `helm,hc_base100,hc_py` and an optional `gender` column (`M`/`F`, used only to
   pre-populate lady-helm trophies). `hc_base100 = round(PY / 10)`.

3. **Boats.** Replace `config/reference/boat_hc.csv` (`class,hc_base100,hc_py`),
   one row per class. Catamaran classes whose names contain `HOBIE` or `NACRA` are
   treated as multihulls; a `_WINTER` suffix marks the light-air variant.

4. **Crew.** Replace `config/reference/crew_hc.csv`. Keep the category rows
   (`NOCREW, GUEST, MEMBER, EXP_MEMBER, IN_TRAINING`) — the app relies on them.

5. **Trophies.** Edit `config/reference/trophies.csv` to your club's trophies and
   their calendar dates / scoring modes (the header documents every column).

6. **Races.** Drop your race CSVs into `raw/races/`, named `NNNN_YYYYMMDD.csv`
   with columns
   `RaceDate,RaceNo,RaceName,HelmName,CrewName,Class,Start,Finish,Code,Rating`.

7. **Rebuild:** **Backup / Data / Settings → Rebuild from reference data**, or
   `python -m core.seed`. From then on, score new races through the app and it
   keeps the live store and CSV mirror up to date.

### Branding

The bundled crest, logo, favicon, and ASCII banner in `assets/` and
`telltale_webui/static/` are **neutral placeholders**. To use your club's
identity, replace these files in place (keep the same filenames):

* `assets/brand/telltale_crest_light.png` / `…_dark.png` — the result-sheet crest
* `telltale_webui/static/logo.png`, `wordmark.png`, `favicon.ico` — the web UI
* `assets/banners/banner.txt` / `banner_color.txt` — the CLI splash

The result renderer falls back gracefully if the crest is missing, so nothing
breaks if you simply delete it.

---

## E-mail publishing (optional)

Ships **off**. To enable it, open `config/email_config.ini`, uncomment the
`[smtp]` block, and fill in your provider's host, port, username and password
(Gmail/Workspace and many others require an **app password**). Set
`email_recipients` in `config/settings.csv` to a comma-separated list. Then
"Publish" a race and the result sheet is mailed to the list.

> **Never commit a real password to a public repository.** Your filled-in
> `email_config.ini` is listed in `.gitignore` so it stays out of git by default.

---

## Configuration reference

All tunables live in `config/settings.csv` (and are editable in-app). Highlights:

| Key | Meaning |
|-----|---------|
| `club_name`, `venue` | shown on result sheets and the home screen |
| `scoring_base` | the "× 100" in the corrected-time formula |
| `hc_cap` | max personal-handicap change per monthly update (default 2) |
| `hc_min_races` | races needed in a month to qualify for an update |
| `novice_initial_hc`, `member_initial_hc` | starting handicaps |
| `inactive_months` | months without a race before a sailor is flagged Inactive |
| `min_competitors` | minimum entries for a valid race |
| `winter_wind_threshold` | wind (kt) below which a catamaran is offered its light-air rating |
| `award_min_month`, `award_season_per_month`, `award_min_year` | award qualification |
| `auto_email`, `email_recipients`, `whatsapp_number` | publishing |

---

## Requirements

* **Python 3.9 or newer**
* **Pillow** (`pip install -r requirements.txt`) — for PNG/PDF rendering

Everything else (storage, e-mail, the web server, CSV handling) uses the Python
standard library. No database server, no JavaScript build, no cloud account.

---

## License

Released under the **MIT License** — free to use, modify, and distribute. See
[`LICENSE`](LICENSE).

Contributions and forks are welcome. If you adapt Telltale for your club, you're
encouraged to keep the source line clean so others can adopt it too.

Created by **Mir T**.
