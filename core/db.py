"""
db.py  -  Dual storage: SQLite (system of record) + CSV mirror (human-readable).

SQLite holds everything: members, boats, crew, races, results, handicap history,
series and a full change log. After any write, the affected tables are dumped to
data/csv/*.csv so there is always a plain-text copy you can open in Excel,
diff in git, or eyeball. The two stay in lock-step; SQLite is authoritative.

A timestamped copy of the .db file is taken before risky operations (backup()).
"""
from __future__ import annotations

import csv
import os
import shutil
import sqlite3
from datetime import datetime

from . import config

SCHEMA = """
CREATE TABLE IF NOT EXISTS settings (
    key   TEXT PRIMARY KEY,
    value TEXT
);

CREATE TABLE IF NOT EXISTS members (
    name         TEXT PRIMARY KEY,      -- display name (UPPER)
    canonical    TEXT,                  -- match key
    personal_hc  INTEGER DEFAULT 0,
    default_boat TEXT DEFAULT '',
    default_crew TEXT DEFAULT '',
    gender       TEXT DEFAULT '',       -- '', 'M', 'F'
    status       TEXT DEFAULT 'Active', -- Active / Inactive
    novice       INTEGER DEFAULT 0,
    last_raced   TEXT DEFAULT '',
    date_added   TEXT DEFAULT '',
    notes        TEXT DEFAULT ''
);

CREATE TABLE IF NOT EXISTS boats (
    sail_no   TEXT PRIMARY KEY,         -- class key, e.g. CLUB WAYFARER_CLASSIC
                                        -- (per-sail-number mode is a future option)
    make      TEXT DEFAULT '',          -- friendly class name, e.g. Wayfarer (Classic)
    boat_name TEXT DEFAULT '',
    boat_hc   REAL DEFAULT 100,
    notes     TEXT DEFAULT ''
);

CREATE TABLE IF NOT EXISTS trophies (
    name    TEXT PRIMARY KEY,
    mode    TEXT DEFAULT 'standard',    -- standard / boat_only / one_design
    ladies  INTEGER DEFAULT 0,          -- Ilse +3/+2 lady-helm advantage
    series  INTEGER DEFAULT 0,
    explain TEXT DEFAULT '',
    year    INTEGER,                     -- year first presented (NULL = unknown)
    discontinued INTEGER DEFAULT 0       -- 1 = kept for history, no longer raced
);

CREATE TABLE IF NOT EXISTS crew (
    name    TEXT PRIMARY KEY,
    crew_hc REAL DEFAULT 0,
    notes   TEXT DEFAULT ''
);

CREATE TABLE IF NOT EXISTS races (
    race_id     INTEGER PRIMARY KEY,
    race_no     INTEGER,
    date        TEXT,                   -- YYYY-MM-DD
    name        TEXT DEFAULT '',        -- cup / trophy / race name
    dosc        TEXT DEFAULT '',
    venue       TEXT DEFAULT '',
    windspeed   REAL DEFAULT 0,
    winddir     TEXT DEFAULT '',
    mode        TEXT DEFAULT 'standard',-- standard / boat_only / one_design
    num_starts  INTEGER DEFAULT 1,
    start_times TEXT DEFAULT '',        -- comma list aligned to groups 1..n
    notes       TEXT DEFAULT ''
);

CREATE TABLE IF NOT EXISTS results (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    race_id        INTEGER,
    member         TEXT,
    boat_sail_no   TEXT DEFAULT '',
    boat_make      TEXT DEFAULT '',
    crew_name      TEXT DEFAULT '',
    per_h          REAL DEFAULT 0,
    boat_h         REAL DEFAULT 0,
    crew_h         REAL DEFAULT 0,
    net_h          REAL DEFAULT 0,
    adj_h          REAL DEFAULT 0,
    start_group    INTEGER DEFAULT 1,
    start_time     TEXT DEFAULT '',
    finish_time    TEXT DEFAULT '',
    code           TEXT DEFAULT '',
    elapsed        INTEGER,
    corrected_time INTEGER,
    position       INTEGER,
    corrected_time2 REAL,
    h_sailed       REAL,
    median_time    REAL,
    deviation      REAL,
    status         TEXT DEFAULT ''
);

CREATE TABLE IF NOT EXISTS handicap_history (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    member      TEXT,
    period      TEXT,                   -- YYYY-MM or label
    personal_hc INTEGER,
    source      TEXT DEFAULT 'auto',    -- auto / manual / seed
    date_applied TEXT
);

CREATE TABLE IF NOT EXISTS personal_adjustments (
    member     TEXT PRIMARY KEY,        -- the sailor the bonus belongs to
    adjustment INTEGER DEFAULT 0,       -- added to Rating after Helm+Boat+Crew
    reason     TEXT DEFAULT '',
    approved_by TEXT DEFAULT '',
    date       TEXT DEFAULT '',
    active     INTEGER DEFAULT 1
);

CREATE TABLE IF NOT EXISTS series (
    series_id  INTEGER PRIMARY KEY AUTOINCREMENT,
    name       TEXT,
    trophy     TEXT DEFAULT '',
    race_ids   TEXT DEFAULT '',         -- comma list
    discards   INTEGER DEFAULT 0,
    min_races  INTEGER DEFAULT 0,
    mode       TEXT DEFAULT 'standard',
    notes      TEXT DEFAULT ''
);

CREATE TABLE IF NOT EXISTS change_log (
    id       INTEGER PRIMARY KEY AUTOINCREMENT,
    ts       TEXT,
    kind     TEXT,
    entity   TEXT,
    detail   TEXT,
    old_val  TEXT,
    new_val  TEXT,
    operator TEXT DEFAULT ''
);

CREATE INDEX IF NOT EXISTS idx_results_race ON results(race_id);
CREATE INDEX IF NOT EXISTS idx_results_member ON results(member);
CREATE INDEX IF NOT EXISTS idx_hist_member ON handicap_history(member);
"""

# Tables mirrored to CSV after writes
MIRROR_TABLES = [
    "members", "boats", "crew", "trophies", "races", "results",
    "handicap_history", "personal_adjustments", "series", "change_log",
]


def connect() -> sqlite3.Connection:
    conn = sqlite3.connect(config.DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def _has_column(conn, table: str, column: str) -> bool:
    rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
    return any(r["name"] == column for r in rows)


def _migrate(conn) -> None:
    """Add columns introduced after a DB was first created. Idempotent: only
    ALTERs in a column when it is missing, so upgrading an existing store never
    needs a full rebuild."""
    additions = [
        ("trophies", "year", "INTEGER"),
        ("trophies", "discontinued", "INTEGER DEFAULT 0"),
    ]
    for table, col, decl in additions:
        if not _has_column(conn, table, col):
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {col} {decl}")


def init_db() -> None:
    conn = connect()
    conn.executescript(SCHEMA)
    _migrate(conn)
    # seed default settings if missing (core defaults + this build's extras)
    cur = conn.cursor()
    for table in (config.DEFAULT_SETTINGS, getattr(config, "EXTRA_SETTINGS", {})):
        for k, v in table.items():
            cur.execute("INSERT OR IGNORE INTO settings(key, value) VALUES (?, ?)", (k, v))
    conn.commit()
    conn.close()
    # config/settings.csv is the human-editable home for all tunables (handicap
    # rules, award/series rules, club info, e-mail toggles). Hand-edits there win
    # at startup; then we rewrite it so it always reflects the live settings.
    try:
        import_settings_from_config()
    except Exception:
        pass
    try:
        export_settings_to_config()
    except Exception:
        pass


def export_settings_to_config() -> str:
    """Write every setting to config/settings.csv (human-editable mirror)."""
    conn = connect()
    rows = conn.execute("SELECT key, value FROM settings ORDER BY key").fetchall()
    conn.close()
    os.makedirs(config.CONFIG_DIR, exist_ok=True)
    with open(config.SETTINGS_FILE, "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["key", "value"])
        for r in rows:
            w.writerow([r["key"], r["value"]])
    return config.SETTINGS_FILE


def import_settings_from_config() -> int:
    """Load config/settings.csv into the settings table (hand-edits). Returns the
    number of keys applied. Silently does nothing if the file is absent."""
    if not os.path.exists(config.SETTINGS_FILE):
        return 0
    applied = 0
    conn = connect()
    with open(config.SETTINGS_FILE, newline="", encoding="utf-8-sig") as fh:
        r = csv.reader(fh)
        next(r, None)
        for row in r:
            if len(row) < 2 or not row[0].strip():
                continue
            conn.execute(
                "INSERT INTO settings(key, value) VALUES (?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                (row[0].strip(), row[1]))
            applied += 1
    conn.commit()
    conn.close()
    return applied


def backup() -> str | None:
    """Timestamped copy of the .db before risky writes. Trims to max_backups."""
    if not os.path.exists(config.DB_PATH):
        return None
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    dest = os.path.join(config.BACKUP_DIR, f"telltale_{ts}.db")
    shutil.copy2(config.DB_PATH, dest)
    _trim_backups()
    return dest


def _trim_backups() -> None:
    try:
        max_n = int(get_setting("max_backups", "50"))
    except Exception:
        max_n = 50
    files = sorted(
        (f for f in os.listdir(config.BACKUP_DIR) if f.startswith("telltale_") and f.endswith(".db")),
    )
    while len(files) > max_n:
        os.remove(os.path.join(config.BACKUP_DIR, files.pop(0)))


def get_setting(key: str, default: str | None = None) -> str | None:
    conn = connect()
    row = conn.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
    conn.close()
    return row["value"] if row else default


def set_setting(key: str, value: str) -> None:
    conn = connect()
    conn.execute(
        "INSERT INTO settings(key, value) VALUES (?, ?) "
        "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
        (key, str(value)),
    )
    conn.commit()
    conn.close()
    try:                       # keep the human-editable config/settings.csv current
        export_settings_to_config()
    except Exception:
        pass


def log_change(kind: str, entity: str, detail: str = "",
               old_val="", new_val="", operator: str = "") -> None:
    conn = connect()
    conn.execute(
        "INSERT INTO change_log(ts, kind, entity, detail, old_val, new_val, operator) "
        "VALUES (?,?,?,?,?,?,?)",
        (datetime.now().isoformat(timespec="seconds"), kind, entity, detail,
         str(old_val), str(new_val), operator),
    )
    conn.commit()
    conn.close()


def mirror_to_csv(tables: list[str] | None = None) -> None:
    """Dump tables to data/csv/<table>.csv. Cheap at this data scale."""
    tables = tables or MIRROR_TABLES
    conn = connect()
    for t in tables:
        try:
            rows = conn.execute(f"SELECT * FROM {t}").fetchall()
        except sqlite3.OperationalError:
            continue
        cols = [d[0] for d in conn.execute(f"SELECT * FROM {t} LIMIT 0").description]
        path = os.path.join(config.CSV_DIR, f"{t}.csv")
        with open(path, "w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(cols)
            for r in rows:
                w.writerow([r[c] for c in cols])
    conn.close()


# ---------------------------------------------------------------------------
# Dense, timestamped backups + reload-from-backup  (v2 feature build)
# ---------------------------------------------------------------------------
def snapshot_csv() -> str:
    """Refresh the live CSV mirror AND drop a timestamped, dense snapshot of
    every table into backups/csv/<ts>/.

    The snapshot is a self-contained, human-readable, easily-parseable copy of
    all data (one CSV per table) plus a single combined `all_data.csv` with a
    leading `__table__` column, so the whole database can be reconstructed from
    a fresh install even if the .db file is lost. Returns the snapshot dir.
    """
    mirror_to_csv()  # keep the "current mirror" (data/csv/) up to date
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    snap = os.path.join(config.CSV_SNAPSHOT_DIR, ts)
    os.makedirs(snap, exist_ok=True)
    conn = connect()
    combined_rows = []
    for t in MIRROR_TABLES:
        try:
            cols = [d[0] for d in conn.execute(f"SELECT * FROM {t} LIMIT 0").description]
            rows = conn.execute(f"SELECT * FROM {t}").fetchall()
        except sqlite3.OperationalError:
            continue
        with open(os.path.join(snap, f"{t}.csv"), "w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(cols)
            for r in rows:
                w.writerow([r[c] for c in cols])
        for r in rows:
            combined_rows.append([t] + [str(r[c]) for c in cols] + ["|".join(cols)])
    conn.close()
    # dense single-file dump: __table__, then values, then the column order
    with open(os.path.join(snap, "all_data.csv"), "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["__table__", "values...", "__columns__(last cell)"])
        for row in combined_rows:
            w.writerow(row)
    _trim_csv_snapshots()
    return snap


def _trim_csv_snapshots() -> None:
    try:
        max_n = int(get_setting("max_backups", "50"))
    except Exception:
        max_n = 50
    dirs = sorted(d for d in os.listdir(config.CSV_SNAPSHOT_DIR)
                  if os.path.isdir(os.path.join(config.CSV_SNAPSHOT_DIR, d)))
    while len(dirs) > max_n:
        shutil.rmtree(os.path.join(config.CSV_SNAPSHOT_DIR, dirs.pop(0)),
                      ignore_errors=True)


def list_db_backups() -> list[str]:
    return sorted(f for f in os.listdir(config.BACKUP_DIR)
                  if f.startswith("telltale_") and f.endswith(".db"))


def list_csv_snapshots() -> list[str]:
    return sorted(d for d in os.listdir(config.CSV_SNAPSHOT_DIR)
                  if os.path.isdir(os.path.join(config.CSV_SNAPSHOT_DIR, d)))


def restore_from_db(backup_filename: str) -> None:
    """Replace the live database with a chosen .db backup (after backing up)."""
    src = os.path.join(config.BACKUP_DIR, backup_filename)
    if not os.path.exists(src):
        raise FileNotFoundError(src)
    backup()  # safety copy of the current state first
    shutil.copy2(src, config.DB_PATH)
    mirror_to_csv()


def restore_from_csv(source_dir: str | None = None) -> dict:
    """Rebuild every table in the SQLite DB from a folder of per-table CSVs.

    Use after a fresh install (only the human-readable mirror survived) or to
    roll back to a timestamped CSV snapshot. `source_dir` defaults to the live
    mirror (data/csv/); pass a snapshot dir name (under backups/csv/) or an
    absolute path to restore an older one. Returns {table: rowcount}.
    """
    if source_dir is None:
        src = config.CSV_DIR
    elif os.path.isabs(source_dir):
        src = source_dir
    else:
        cand = os.path.join(config.CSV_SNAPSHOT_DIR, source_dir)
        src = cand if os.path.isdir(cand) else source_dir
    if not os.path.isdir(src):
        raise FileNotFoundError(src)
    backup()
    init_db()
    conn = connect()
    counts: dict[str, int] = {}
    for t in MIRROR_TABLES:
        path = os.path.join(src, f"{t}.csv")
        if not os.path.exists(path):
            continue
        with open(path, newline="", encoding="utf-8-sig") as f:
            reader = csv.reader(f)
            header = next(reader, None)
            if not header:
                continue
            conn.execute(f"DELETE FROM {t}")
            placeholders = ",".join("?" * len(header))
            collist = ",".join(header)
            n = 0
            for row in reader:
                if len(row) != len(header):
                    continue
                vals = [(None if v == "" else v) for v in row]
                try:
                    conn.execute(
                        f"INSERT INTO {t} ({collist}) VALUES ({placeholders})", vals)
                    n += 1
                except sqlite3.IntegrityError:
                    conn.execute(
                        f"INSERT OR REPLACE INTO {t} ({collist}) VALUES ({placeholders})",
                        vals)
                    n += 1
            counts[t] = n
    conn.commit()
    conn.close()
    mirror_to_csv()
    return counts
