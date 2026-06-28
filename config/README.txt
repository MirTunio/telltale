TELLTALE - config/
===================

This folder holds ALL hand-editable configuration. You can edit anything here by
hand (then restart the app, or use the CLI/Web "reload" actions), or change it
from the CLI and the web UI - changes are mirrored back here automatically.

settings.csv
    Every tunable, as key,value. This is the human-editable home for:
      - club_name, venue
      - handicap rules:  hc_cap, hc_min_races, novice_initial_hc, member_initial_hc,
                         inactive_months, winter_wind_threshold
      - race rules:      min_competitors, default_start_times, wind_directions
      - award / series rules:  award_min_month, award_season_per_month, award_min_year
      - e-mail:          auto_email, email_recipients, whatsapp_number
      - bookkeeping:     hc_updated_through, max_backups
    The running app reads these into the database at startup (hand-edits here win),
    and rewrites this file whenever a setting changes. The database under data/ is
    the live copy; this file is the readable source you can edit and keep in git.

email_config.ini
    SMTP server / credentials for the optional results e-mail. Ships DISABLED
    (the [smtp] block is commented out). Uncomment it and fill in your provider's
    host/port/username/password to enable e-mail. The "From" address is set by
    "from_addr"; "email_recipients" (in settings.csv) is a comma-separated LIST.
    Do NOT commit a real password to a public repository.

reference/                (the seed source - NOT the live handicaps)
    helm_hc.csv           starting personal handicaps (where the walk begins)
    boat_hc.csv           one handicap per boat class / sub-class
    crew_hc.csv           fixed crew list incl. categories (never auto-updated)
    trophies.csv          MASTER trophy register (editable). One row per trophy:
                          When (year-less calendar rule, e.g. "3rd Sunday of
                          October" or "14 August"), Mode, ladies advantage
                          (LadiesAdv/CrewLadyBonus/LadiesCap), Tindal, CrewOnly,
                          SeriesRaces/Discards/MinRaces, and a Note. Edit this to
                          change a trophy's rules or its calendar date - it is
                          re-read automatically when the file's timestamp changes.
    trophy_calendar.csv   simple season schedule, kept as a fallback only
    helm_hc_prev_derived.csv   the previous starting sheet, kept for audit/rollback
    These are the INPUTS to a rebuild ("Rebuild from reference data" / python -m
    core.seed). The LIVE, up-to-the-minute handicaps live in the database and are
    mirrored to data/csv/members.csv - edit those via the app, not here.

Where everything else lives
    raw/races/  source race logs (one CSV per race; this is what seed replays)
    data/       the live store: telltale.db, csv/ mirror, backups/
    race_results/   computed race-result images (NNNN_YYYYMMDD_HHMMSS_*.png)
    outputs/    user-generated reports & queries (timestamped)
    docs/, assets/   documentation and bundled fonts
