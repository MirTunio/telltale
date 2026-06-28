# Telltale web UI

A small, local web interface for Telltale. It runs **alongside** the command-line
app and uses the same database, race logs and config - so the CLI keeps working
exactly as before, and anything you do in one shows up in the other.

It uses only the Python standard library (no Flask, no pip installs), so it runs
on the same Python the CLI uses.

## Launch

From the project root:

```
python telltale_webui/serve.py
```

That starts a local server on http://127.0.0.1:8765 and opens it in your browser.
Options:

```
python telltale_webui/serve.py 8080            # use a different port
python telltale_webui/serve.py 8080 --no-browser
python -m telltale_webui.serve                 # equivalent
```

On Windows you can double-click `run_web.bat` (in the project root); on
macOS/Linux run `python telltale_webui/serve.py`. Press `Ctrl+C` in the
terminal to stop it.

## What you can do

- **Dashboard** - club, member/race counts, the next trophy, recent results and reports.
- **Handicaps** - the live handicap list (frequent racers or all members) with
  trend arrows and consistency stars, plus a button to render the PNG.
- **HC history** - generate the 12-month handicap-history chart.
- **Races / Race view** - browse every scored race; open one to see the results
  table and its result image, or regenerate the image.
- **Score a race** - enter a race (date, trophy, mode, wind, entries) and it is
  scored, saved, written to `raw/races/`, and a result image is produced in
  `race_results/` - identical to scoring it in the CLI.
- **Reports** - handicap list, handicap history, honours board, and awards /
  season summary by period. Reports are written to `outputs/`.
- **Settings** - edit handicap/award/race rules and club info. Changes are saved
  to the database and mirrored to `config/settings.csv` (which you can also edit
  by hand).

## Notes

- The score form only accepts **existing** helms (it snaps a typed name to the
  closest known member). To add a brand-new member, boat or crew, use the CLI -
  this keeps the roster clean.
- It binds to `127.0.0.1` (your machine only). It is a club-admin tool, not a
  public website; don't expose it to the internet as-is.
- Architecture: `serve.py` (launcher) -> `server.py` (routing + actions) ->
  `pages.py` (HTML) -> `core/` (the same engine the CLI uses).
