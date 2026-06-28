"""
pages.py  -  Server-side HTML for the Telltale web UI.

Pure presentation: every number comes from the same core modules the CLI uses
(core.repository / scoring / report / trophies), so the web UI and CLI can never
disagree. No third-party dependencies.
"""
from __future__ import annotations

import html
import os
from datetime import date

from core import config, repository as repo, awards
from core import trophies as trophies_mod
from core.scoring import MODE_STANDARD, MODE_BOAT_ONLY, MODE_ONE_DESIGN

MODE_LABELS = {
    MODE_STANDARD: "Standard (boat + personal + crew)",
    MODE_BOAT_ONLY: "Boat handicap only",
    MODE_ONE_DESIGN: "One-design / level",
}


def e(s) -> str:
    return html.escape("" if s is None else str(s))


def _hms(seconds) -> str:
    if seconds in (None, ""):
        return ""
    s = int(round(float(seconds)))
    return f"{s // 3600}:{(s % 3600) // 60:02d}:{s % 60:02d}"


# --------------------------------------------------------------------------- layout
def layout(title: str, body: str, active: str = "") -> str:
    club = e(repo.db.get_setting("club_name") or "Sailing Club") \
        if hasattr(repo, "db") else "Sailing Club"
    nav_items = [
        ("/", "Dashboard"), ("/handicaps", "Handicaps"), ("/history", "HC history"),
        ("/races", "Races"), ("/score", "Score a race"), ("/series", "Series"),
        ("/trophies", "Trophies"), ("/reports", "Reports"), ("/settings", "Settings"),
        ("/about", "About"),
    ]
    nav = "".join(
        f'<a class="{"on" if href == active else ""}" href="{href}">{e(label)}</a>'
        for href, label in nav_items)
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{e(title)} - Telltale</title>
<link rel="icon" href="/favicon.ico" sizes="any">
<link rel="stylesheet" href="/static/style.css">
</head><body>
<header><img class="logo" src="/static/logo.png" alt="Telltale">
<div class="head-main"><div class="brand">Telltale <span>{club}</span></div>
<nav>{nav}</nav></div></header>
<main>{body}</main>
<footer>Telltale race scoring - the CLI remains fully available. This web UI uses the same engine.</footer>
</body></html>"""


# --------------------------------------------------------------------------- helpers
def _trend_html(t: str) -> str:
    if t == "\u2193":   # HC fell -> improving
        return '<span class="trend up" title="improving (handicap fell)">&#9650;</span>'
    if t == "\u2191":   # HC rose -> easing
        return '<span class="trend down" title="easing (handicap rose)">&#9660;</span>'
    if t == "\u2192":
        return '<span class="trend flat" title="steady">&#8211;</span>'
    return ""


def _stars_html(n: int) -> str:
    n = int(n or 0)
    return ('<span class="stars">' + "&#9733;" * n + '<span class="hollow">'
            + "&#9734;" * (3 - n) + "</span></span>") if n else \
        '<span class="stars hollow">&#9734;&#9734;&#9734;</span>'


def _active_set():
    members = repo.list_members()
    anchor = max((m["last_raced"] for m in members if m["last_raced"]), default="")
    inactive = int(repo.db.get_setting("inactive_months", "6"))
    out = set()
    if anchor:
        ay, am = int(anchor[:4]), int(anchor[5:7])
        for m in members:
            lr = m["last_raced"]
            if m["status"] == "Active" and lr:
                ly, lm = int(lr[:4]), int(lr[5:7])
                if (ay - ly) * 12 + (am - lm) <= inactive:
                    out.add(m["name"])
    return out


def _latest_race_img(rid: int) -> str:
    """Newest race_results image for this race (NNNN_*.png), or ''."""
    prefix = f"{int(rid):04d}_"
    try:
        fs = [f for f in os.listdir(config.RACE_RESULTS_DIR)
              if f.startswith(prefix) and f.lower().endswith(".png")]
    except OSError:
        return ""
    return sorted(fs)[-1] if fs else ""
def dashboard() -> str:
    races = repo.list_races()
    members = repo.list_members()
    n_active = len(_active_set())
    # list_races() is ascending by (date, race_id); the genuinely latest race is
    # the max by sail date then entry order, so newly added races always show.
    latest = max(races, key=lambda r: (r["date"], r["race_id"])) if races else None
    nt = trophies_mod.next_trophy(date.today())
    nt_html = ""
    if nt:
        when = nt["date"].strftime("%a %d %b %Y")
        label = nt["trophy"].name if nt["trophy"] else nt["name_raw"]
        nt_html = (f'<div class="card"><h3>Next trophy</h3>'
                   f'<p class="big">{e(label)}</p><p>{e(when)} '
                   f'({nt["days_away"]} days away)</p></div>')
    last_html = ""
    if latest:
        last_html = (f'<div class="card"><h3>Most recent race</h3>'
                     f'<p class="big">#{latest["race_id"]} {e(latest["name"] or "")}</p>'
                     f'<p>{e(latest["date"])} - <a href="/race?id={latest["race_id"]}">view result</a></p></div>')

    # recent generated artefacts
    def _recent(dirpath, n=6):
        try:
            fs = [f for f in os.listdir(dirpath)
                  if not f.startswith(".") and f.lower().endswith((".png", ".csv", ".pdf"))]
        except OSError:
            return []
        fs.sort(reverse=True)
        return fs[:n]
    rr = "".join(f'<li><a href="/file?d=race_results&f={e(f)}">{e(f)}</a></li>'
                 for f in _recent(config.RACE_RESULTS_DIR))
    out = "".join(f'<li><a href="/file?d=outputs&f={e(f)}">{e(f)}</a></li>'
                  for f in _recent(config.OUTPUTS_DIR))

    # task 10: if a completed month's handicap update is due, warn on the homepage
    pending = repo.pending_update_months()
    pend_html = ""
    if pending:
        pend_html = (
            '<div class="banner warn"><b>Handicap update due.</b> '
            'The monthly update for ' + e(", ".join(pending)) + ' has not run yet. '
            'It is applied automatically before you score the first race of a new '
            'month, or you can run it now.'
            '<form method="post" action="/run-updates" style="display:inline;margin-left:.6em">'
            '<button class="btn" type="submit">Run update now</button></form></div>')

    body = f"""
<h1>Dashboard</h1>
{pend_html}
<div class="cards">
  <div class="card"><h3>Members</h3><p class="big">{len(members)}</p><p>{n_active} active</p></div>
  <div class="card"><h3>Races scored</h3><p class="big">{len(races)}</p>
     <p>{e(races[0]["date"]) if races else "-"} &rarr; {e(races[-1]["date"]) if races else "-"}</p></div>
  {nt_html}
  {last_html}
</div>
<div class="cols">
  <section><h3>Latest race results</h3><ul class="files">{rr or "<li>(none yet)</li>"}</ul></section>
  <section><h3>Latest reports</h3><ul class="files">{out or "<li>(none yet)</li>"}</ul></section>
</div>
<p><a class="btn" href="/score">Score a race</a> <a class="btn ghost" href="/handicaps">View handicaps</a></p>
"""
    return layout("Dashboard", body, "/")


# --------------------------------------------------------------------------- handicaps
def handicaps(scope: str = "frequent", note: str = "") -> str:
    members = repo.list_members()
    cons = awards.consistency_table(12)
    active = _active_set()
    if scope == "all":
        rows = sorted(members, key=lambda m: m["name"])
        title = "All members (A-Z)"
    else:
        rows = sorted((m for m in members if m["name"] in active),
                      key=lambda m: (int(m["personal_hc"]), m["name"]))
        title = "Frequent racers"

    trs = []
    for m in rows:
        nm = m["name"]
        c = cons.get(nm, {})
        adj = repo.get_adjustment(nm)
        adj_s = f'{adj["adjustment"]:+g}' if adj and adj["adjustment"] else ""
        trs.append(
            f'<tr><td class="l">{e(nm)}</td><td class="num">{int(m["personal_hc"]):+d}</td>'
            f'<td class="num">{adj_s}</td><td class="c">{_trend_html(repo.hc_trend(nm))}</td>'
            f'<td class="c">{_stars_html(c.get("stars", 0))}</td>'
            f'<td class="num">{c.get("races", 0)}</td><td>{e(m["status"])}</td>'
            f'<td>{e(m["last_raced"] or "-")}</td></tr>')
    toggle = (f'<a class="btn ghost{" on" if scope=="frequent" else ""}" href="/handicaps?scope=frequent">Frequent</a> '
              f'<a class="btn ghost{" on" if scope=="all" else ""}" href="/handicaps?scope=all">All members</a>')
    note_html = f'<p class="ok">{e(note)}</p>' if note else ""
    body = f"""
<h1>Handicap list <small>{e(title)}</small></h1>
{note_html}
<p>{toggle}
   <form method="post" action="/reports" style="display:inline">
     <input type="hidden" name="kind" value="handicap">
     <button class="btn" type="submit">Generate PNG (frequent + all)</button>
   </form>
   <a class="btn ghost" href="/history">HC history chart</a></p>
<table class="grid">
<thead><tr><th class="l">Helm</th><th>HC</th><th>Adj</th><th>Trend</th><th>Consistency</th>
<th>Races(12m)</th><th>Status</th><th>Last raced</th></tr></thead>
<tbody>{"".join(trs)}</tbody></table>
<p class="legend"><span class="trend up">&#9650;</span> improving &nbsp;
<span class="trend down">&#9660;</span> easing &nbsp;
<span class="trend flat">&#8211;</span> steady &nbsp; | &nbsp;
<span class="stars">&#9733;</span> consistency &nbsp; | &nbsp; lower HC = stronger</p>
"""
    return layout("Handicaps", body, "/handicaps")


# --------------------------------------------------------------------------- HC history
def history(img_rel: str = "", periods=None) -> str:
    img = ""
    if img_rel:
        img = (f'<p><img class="chart" src="/file?d=outputs&f={e(img_rel)}" '
               f'alt="handicap history chart"></p>')
    # task 11: tabular history (months oldest->newest, Current, Name; best on top)
    per, series_rows = repo.hc_history_series(months=12)
    active = _active_set()
    table = _hc_table_html(per, [s for s in series_rows if s["name"] in active])
    body = f"""
<h1>Handicap history</h1>
<p>Personal handicap over the last 12 months for the frequent racers. Lower handicap
   = stronger, so a rising line is improving.</p>
<form method="post" action="/reports">
  <input type="hidden" name="kind" value="history">
  <label>Months back <input type="number" name="months" value="12" min="3" max="36" style="width:5em"></label>
  <button class="btn" type="submit">Generate chart</button>
</form>
{img}
<h2>History table</h2>
<p class="muted">Months run oldest&rarr;newest, then the current handicap, then the
   sailor. Sorted with the lowest (strongest) handicap on top.</p>
<form method="post" action="/reports" style="margin-bottom:.6em">
  <input type="hidden" name="kind" value="history_table">
  <input type="hidden" name="months" value="12">
  <button class="btn ghost" type="submit">Download table as PNG</button>
</form>
{table}
"""
    return layout("HC history", body, "/history")


# --------------------------------------------------------------------------- races
def races() -> str:
    rs = repo.list_races()
    trs = "".join(
        f'<tr><td class="num">{r["race_id"]}</td><td>{e(r["date"] or "-")}</td>'
        f'<td class="l">{e(r["name"] or "(unnamed)")}</td><td>{e(r["mode"])}</td>'
        f'<td><a href="/race?id={r["race_id"]}">view</a></td></tr>' for r in rs)
    body = f"""
<h1>Races <small>{len(rs)} scored</small></h1>
<table class="grid"><thead><tr><th>#</th><th>Date</th><th class="l">Race</th>
<th>Mode</th><th></th></tr></thead><tbody>{trs}</tbody></table>
"""
    return layout("Races", body, "/races")


def race_view(rid: int, img_rel: str = "", msg: str = "") -> str:
    race = repo.get_race(rid)
    if not race:
        return layout("Race", "<h1>Race not found</h1>", "/races")
    if not img_rel:
        img_rel = _latest_race_img(rid)
    banner = f'<div class="banner">{e(msg)}</div>' if msg else ""
    results = sorted(repo.get_results(rid),
                     key=lambda r: (r["position"] is None, r["position"] or 0))
    trs = []
    for r in results:
        pos = r["position"] if r["position"] is not None else (r.get("code") or "-")
        trs.append(
            f'<tr><td class="num">{e(pos)}</td><td class="l">{e(r["member"])}</td>'
            f'<td>{e(r.get("boat_make") or r.get("boat_sail_no"))}</td>'
            f'<td>{e(r.get("crew_name") or "")}</td>'
            f'<td class="num">{e(r.get("net_h"))}</td>'
            f'<td class="num">{_hms(r.get("elapsed"))}</td>'
            f'<td class="num">{_hms(r.get("corrected_time"))}</td>'
            f'<td class="num">{e(r.get("deviation")) if r.get("deviation") is not None else ""}</td>'
            f'<td>{e(r.get("code") or "")}</td></tr>')
    img = (f'<p><img class="result" src="/file?d=race_results&f={e(img_rel)}"></p>'
           if img_rel else "")
    info = []
    if race.get("dosc"): info.append(f'DOSC {e(race["dosc"])}')
    if race.get("windspeed"): info.append(f'wind {e(race["windspeed"])}kt {e(race.get("winddir") or "")}')
    body = f"""
<h1>#{race["race_id"]} {e(race["name"] or "")} <small>{e(race["date"])} - {e(MODE_LABELS.get(race["mode"], race["mode"]))}</small></h1>
{banner}
<p>{" &middot; ".join(info)}</p>
<p><form method="post" action="/regen" style="display:inline">
   <input type="hidden" name="id" value="{race["race_id"]}">
   <button class="btn" type="submit">Regenerate result image</button></form>
   <a class="btn ghost" href="/races">&larr; all races</a></p>
{img}
<table class="grid"><thead><tr><th>Pos</th><th class="l">Helm</th><th>Boat</th><th>Crew</th>
<th>Net</th><th>Elapsed</th><th>Corrected</th><th>Dev</th><th>Code</th></tr></thead>
<tbody>{"".join(trs)}</tbody></table>
<p class="muted">To edit a saved race, use the CLI (Reports &rarr; 3 &rarr; Edit).</p>
"""
    return layout(f"Race #{rid}", body, "/races")


# --------------------------------------------------------------------------- score form
def score_form(msg: str = "", values: dict | None = None) -> str:
    members = repo.member_names()
    boats = repo.list_boats()
    crew = repo.list_crew()
    member_opts = "".join(f'<option value="{e(m)}">' for m in members)
    boat_opts = "".join(
        f'<option value="{e(b["sail_no"])}">{e(b["make"])} (HC {int(round(float(b["boat_hc"])))})</option>'
        for b in boats)
    crew_opts = "".join(
        f'<option value="{e(c["name"])}">{e(c["name"])} ({int(round(float(c["crew_hc"]))):+d})</option>'
        for c in crew)
    trophy_opts = "".join(f'<option value="{e(t.name)}">'
                          for t in trophies_mod.TROPHIES if not t.discontinued)
    wdirs = (repo.db.get_setting("wind_directions", "N,NE,E,SE,S,SW,W,NW") or "").split(",")
    wdir_opts = "".join(f'<option value="{e(w)}">{e(w)}</option>' for w in wdirs)
    default_start = (repo.db.get_setting("default_start_times", "13:30") or "13:30").split(",")[0]
    today = date.today().isoformat()
    mode_opts = "".join(f'<option value="{k}">{e(v)}</option>' for k, v in MODE_LABELS.items())
    msg_html = f'<p class="ok">{e(msg)}</p>' if msg else ""

    # one entry row template rendered server-side; JS clones it
    def row(i):
        return f"""<tr class="entry">
  <td><input list="members" name="helm" placeholder="helm name"></td>
  <td><select name="boat"><option value="">- class -</option>{boat_opts}</select></td>
  <td><select name="crew">{crew_opts}</select></td>
  <td><input name="start" value="{e(default_start)}" size="8"></td>
  <td><input name="finish" placeholder="HH:MM:SS / DNF"></td>
  <td><button type="button" class="del" onclick="delRow(this)">&times;</button></td>
</tr>"""
    rows = "".join(row(i) for i in range(6))

    body = f"""
<h1>Score a race</h1>
{msg_html}
<form method="post" action="/score" id="scoreform">
<div class="formgrid">
  <label>Date <input type="date" name="date" value="{today}"></label>
  <label>Race / trophy <input list="trophies" name="name" placeholder="e.g. OORD CUP"></label>
  <label>Scoring mode <select name="mode">{mode_opts}</select></label>
  <label>DOSC <input list="members" name="dosc" placeholder="duty officer (optional)"></label>
  <label>Wind (kt) <input type="number" id="windinput" name="wind" min="0" step="0.1" size="4" required><span id="windhint" class="muted" style="margin-left:.4em"></span></label>
  <label>Wind dir <select name="winddir" required><option value="" disabled selected>- pick -</option>{wdir_opts}</select></label>
  <label class="check"><input type="checkbox" name="ladies" value="1"> Ladies advantage (+3 helm)</label>
</div>
<p class="muted">Wind speed and direction are required - check the day's log or ask the DOSC if unsure. When the club is online, the current wind is pre-filled as a suggestion.</p>
<h3>Entries <button type="button" class="btn ghost" onclick="addRow()">+ add boat</button></h3>
<table class="grid entries"><thead><tr><th class="l">Helm</th><th>Class</th><th>Crew</th>
<th>Start</th><th>Finish / code</th><th></th></tr></thead>
<tbody id="entries">{rows}</tbody></table>
<p><button class="btn" type="submit">Score &amp; save</button>
   <span class="muted">Blank rows are ignored. A boat with a code (DNF/DNS/DSQ/&hellip;) and no finish time is a non-finisher.</span></p>
</form>
<datalist id="members">{member_opts}</datalist>
<datalist id="trophies">{trophy_opts}</datalist>
<script>
function addRow(){{
  var t=document.querySelector('tr.entry'); var c=t.cloneNode(true);
  c.querySelectorAll('input').forEach(function(i){{ if(i.name!=='start') i.value=''; }});
  document.getElementById('entries').appendChild(c);
}}
function delRow(b){{ var r=b.closest('tr'); if(document.querySelectorAll('tr.entry').length>1) r.remove(); }}
(function(){{
  var inp=document.getElementById('windinput'), hint=document.getElementById('windhint');
  if(!inp) return;
  var url="https://api.open-meteo.com/v1/forecast?latitude={config.VENUE_LAT:.4f}"
        +"&longitude={config.VENUE_LON:.4f}&current=wind_speed_10m&wind_speed_unit=kn";
  fetch(url).then(function(r){{ return r.json(); }}).then(function(d){{
    var kt = d && d.current && d.current.wind_speed_10m;
    if(kt==null || isNaN(kt)) return;
    kt = Math.round(kt);
    if(!inp.value) inp.value = kt;          // pre-fill suggestion; the DOSC can change it
    inp.placeholder = "\u2248"+kt+" kt";
    if(hint) hint.textContent = "live \u2248"+kt+" kt (Open-Meteo) - adjust to the DOSC's reading";
  }}).catch(function(){{ /* offline: silently leave the field for the DOSC */ }});
}})();
</script>
"""
    return layout("Score a race", body, "/score")


# --------------------------------------------------------------------------- reports
def reports_page(note: str = "", link: str = "") -> str:
    link_html = ""
    if link:
        link_html = f'<p class="ok">Generated: <a href="{e(link)}">{e(link.split("f=")[-1])}</a></p>'
    note_html = f'<p class="ok">{e(note)}</p>' if note else ""

    def b(kind, label, extra=""):
        return (f'<form method="post" action="/reports"><input type="hidden" name="kind" value="{kind}">'
                f'{extra}<button class="btn" type="submit">{e(label)}</button></form>')
    period_in = '<input name="period" placeholder="YYYY-MM / YYYY / season" size="12">'
    body = f"""
<h1>Reports</h1>
{note_html}{link_html}
<div class="reportgrid">
  {b("handicap", "Handicap list (frequent + all)")}
  {b("history", "Handicap history chart", '<input type="hidden" name="months" value="12">')}
  {b("honours", "Honours board (PNG + CSV)")}
  {b("awards", "Awards", period_in)}
  {b("season", "Season summary", '<input name="period" placeholder="season e.g. 2025-Spring" size="14">')}
</div>
<p class="muted">Reports are written to outputs/ (timestamped). Race result images live in race_results/.</p>
"""
    return layout("Reports", body, "/reports")


# --------------------------------------------------------------------------- settings
_SETTING_HELP = {
    "club_name": "Club name on every report",
    "venue": "Default venue",
    "hc_cap": "Max personal-HC change per monthly update",
    "hc_min_races": "Races in a month needed to qualify for an update",
    "min_competitors": "Minimum boats for a valid race (warning only)",
    "inactive_months": "Months without a race before a sailor is Inactive",
    "winter_wind_threshold": "Wind (kt) below which the WINTER catamaran HC is recommended (and at/above which the standard HC is)",
    "award_min_month": "Best-N results scored in a month",
    "award_season_per_month": "Per-month multiplier for season qualification",
    "award_min_year": "Best-N results scored over a year",
    "default_start_times": "Comma-separated default start times",
    "auto_email": "off | ask | auto",
}


def settings_page(note: str = "") -> str:
    conn = repo.db.connect()
    rows = conn.execute("SELECT key, value FROM settings ORDER BY key").fetchall()
    conn.close()
    note_html = f'<p class="ok">{e(note)}</p>' if note else ""
    trs = "".join(
        f'<tr><td class="l"><code>{e(r["key"])}</code></td>'
        f'<td><input name="s_{e(r["key"])}" value="{e(r["value"])}"></td>'
        f'<td class="muted">{e(_SETTING_HELP.get(r["key"], ""))}</td></tr>'
        for r in rows)
    last_period = repo.last_update_period()
    rollback_html = (
        '<h2>Handicap update</h2>'
        '<p class="muted">Roll back the most recent monthly handicap update if it was '
        'run in error. Each affected sailor\u2019s handicap is restored to its prior '
        'value and the &ldquo;updated through&rdquo; marker steps back one month. '
        '(The handicap walk-forward has its own algorithm and is not affected.)</p>'
        + (f'<form method="post" action="/rollback" '
           f'onsubmit="return confirm(\'Roll back the {e(last_period)} handicap update? '
           f'This restores every affected handicap to its previous value.\');">'
           f'<button class="btn ghost" type="submit">Roll back the {e(last_period)} update</button>'
           f'</form>'
           if last_period else
           '<p class="muted">No monthly update has been applied yet.</p>'))
    email_note = (
        '<p class="note">Tip: <code>email_recipients</code> may be a list &mdash; '
        'separate addresses with commas (or semicolons) and every address receives '
        'the results. <code>email_from</code> defaults to '
        '<code>results@example.org</code>. See '
        '<code>config/email_config.ini</code> for SMTP setup.</p>')
    body = f"""
<h1>Settings</h1>
{note_html}
<p class="muted">These are mirrored to <code>config/settings.csv</code> (hand-editable).
Handicap, award and race rules all live here.</p>
{email_note}
<form method="post" action="/settings">
<table class="grid"><thead><tr><th class="l">Key</th><th>Value</th><th>What it does</th></tr></thead>
<tbody>{trs}</tbody></table>
<p><button class="btn" type="submit">Save settings</button>
   <a class="btn ghost" href="/settings?reload=1">Reload from config/settings.csv</a></p>
</form>
{rollback_html}
"""
    return layout("Settings", body, "/settings")


# --------------------------------------------------------------------------- about (task 4)
def about_page() -> str:
    lines = config.ABOUT_TEXT.split("\n")
    body = f"""
<h1>About</h1>
<div class="about-card">
  <img src="/static/wordmark.png" alt="Telltale">
  <h2>{e(lines[0])}</h2>
  <p>{"<br>".join(e(l) for l in lines[1:])}</p>
</div>
"""
    return layout("About", body, "/about")


# --------------------------------------------------------------------------- trophies (task 8)
def trophies_page() -> str:
    today = date.today()
    upcoming = trophies_mod.upcoming_trophies(today, limit=14)
    up_rows = "".join(
        f'<tr><td>{e(u["date"].strftime("%a %d %b %Y"))}</td>'
        f'<td>{e(u["trophy"].name if u["trophy"] else u["name_raw"])}</td>'
        f'<td>{e(u["when"])}</td><td>{u["days_away"]}d</td></tr>'
        for u in upcoming)
    up_html = (f'<div class="scroll"><table class="grid"><thead><tr>'
               f'<th>Date</th><th>Trophy</th><th>When (year-less)</th><th>In</th>'
               f'</tr></thead><tbody>{up_rows}</tbody></table></div>'
               if up_rows else "<p>No dated trophies on the calendar.</p>")

    # full register with rules + history note
    rows = []
    for t in sorted(trophies_mod.TROPHIES, key=lambda x: x.name):
        tt = trophies_mod.match_trophy(t.name) or t
        tags = []
        if tt.mode != "standard":
            tags.append(MODE_LABELS.get(tt.mode, tt.mode))
        if getattr(tt, "tindal", False):
            tags.append("tindals")
        if getattr(tt, "crew_only", False):
            tags.append("crew")
        if getattr(tt, "ladies_adv", 0):
            tags.append(f"ladies +{tt.ladies_adv}/+{tt.crew_lady_bonus} cap +{tt.ladies_cap}")
        if getattr(tt, "series_races", 0):
            tags.append(f"series {tt.series_races}, {tt.discards} discard(s)")
        if tt.discontinued:
            tags.append("discontinued")
        tag_html = " ".join(f'<span class="tag">{e(x)}</span>' for x in tags)
        note = tt.effective_note()
        when = getattr(tt, "when", "") or ""
        rows.append(
            f'<tr><td><b>{e(tt.name)}</b>{(" " + tag_html) if tag_html else ""}'
            f'{("<br><span class=note>" + e(note) + "</span>") if note else ""}</td>'
            f'<td>{e(when)}</td></tr>')
    reg = (f'<div class="scroll"><table class="grid"><thead><tr><th>Trophy</th>'
           f'<th>When</th></tr></thead><tbody>{"".join(rows)}</tbody></table></div>')

    body = f"""
<h1>Trophies</h1>
<p>Scoring rules, the year-less calendar and the historical notes all come from
<code>config/reference/trophies.csv</code> &mdash; edit that file to change them.</p>
<h3>Upcoming on the calendar</h3>
{up_html}
<h3>Full register</h3>
{reg}
"""
    return layout("Trophies", body, "/trophies")


# --------------------------------------------------------------------------- series (task 6, 12)
def series_page(msg: str = "", link: str = "") -> str:
    races = sorted(repo.list_races(), key=lambda r: (r["date"], r["race_id"]))[-12:]
    opts = "".join(
        f'<label class="check"><input type="checkbox" name="rid" value="{r["race_id"]}"> '
        f'#{r["race_id"]} {e(r["date"])} {e(r["name"] or "")}</label>'
        for r in reversed(races))
    note = f'<div class="banner">{e(msg)} ' + (
        f'<a class="btn" href="{e(link)}">Open result</a>' if link else "") + "</div>" if msg else ""
    body = f"""
<h1>Series scoring</h1>
{note}
<p>Pick the races (the most recent 12 are listed), choose a handicap scheme and
whether the series is provisional or final. The progressive schemes reproduce the
Commodore-style output: a points-per-race table plus a per-race handicap digest.</p>
<form method="post" action="/series">
  <div class="check-grid">{opts}</div>
  <label>Series / trophy name <input name="name" value="SERIES" required></label>
  <label>Scheme
    <select name="scheme">
      <option value="n">Normal &mdash; saved club handicap</option>
      <option value="a">Progressive &plusmn;1 per race (from 0)</option>
      <option value="b">Progressive NHC-style (base 100)</option>
    </select>
  </label>
  <label>Discards <input name="discards" type="number" value="0" min="0" style="width:6em"></label>
  <label class="check"><input type="checkbox" name="final"> Series is complete (Final)</label>
  <p><button class="btn" type="submit">Score series</button></p>
</form>
"""
    return layout("Series", body, "/series")


# --------------------------------------------------------------------------- HC history table (task 11)
def _hc_table_html(periods, series) -> str:
    if not periods:
        return "<p>No handicap history yet.</p>"
    rows_data = sorted(series, key=lambda r: (r.get("current") if r.get("current") is not None else 9999,
                                              r.get("name", "")))
    def lbl(p):
        try:
            y, m = p.split("-"); return f"{['','Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec'][int(m)]} {y[2:]}"
        except Exception:
            return p
    head = "".join(f"<th>{e(lbl(p))}</th>" for p in periods)
    body = []
    for i, r in enumerate(rows_data, 1):
        pts = list(r.get("points") or [])
        cells = []
        for j in range(len(periods)):
            v = pts[j] if j < len(pts) else None
            cells.append(f"<td>{(f'{v:+d}' if isinstance(v, int) else '·')}</td>")
        cur = r.get("current")
        body.append(f'<tr><td>{i}</td>{"".join(cells)}'
                    f'<td><b>{(f"{cur:+d}" if isinstance(cur, int) else "·")}</b></td>'
                    f'<td>{e(r.get("name",""))}</td></tr>')
    return (f'<div class="scroll"><table class="grid"><thead><tr><th>#</th>{head}'
            f'<th>Current</th><th>Name</th></tr></thead><tbody>'
            f'{"".join(body)}</tbody></table></div>')
