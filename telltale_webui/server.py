"""
server.py  -  Minimal stdlib HTTP server for the Telltale web UI.

No third-party dependencies (works on the same Python 3.9 the CLI uses). It is a
thin layer: every computation goes through the existing core modules and even
reuses the CLI's own render helpers, so the web UI and CLI produce identical
results. The CLI remains fully usable and unaffected.
"""
from __future__ import annotations

import os
import sys
import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs

# make the project importable (this file lives in telltale_webui/)
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from core import config, db, repository as repo, awards            # noqa: E402
from core import report, raceio                                     # noqa: E402
from core import trophies as trophies_mod                           # noqa: E402
from core import scoring                                            # noqa: E402
from core import series                                             # noqa: E402
from core import series_progressive as series_prog                  # noqa: E402
from core.scoring import NON_FINISH_CODES                           # noqa: E402
from core.names import find_matches, canonical, display             # noqa: E402
from core.timeutil import normalize_finish                          # noqa: E402
import telltale                                                     # noqa: E402  (reuse render helpers)
from telltale_webui import pages                                    # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
STATIC_DIR = os.path.join(HERE, "static")
_CT = {".png": "image/png", ".csv": "text/csv", ".pdf": "application/pdf",
       ".txt": "text/plain", ".css": "text/css", ".ico": "image/x-icon",
       ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".gif": "image/gif",
       ".svg": "image/svg+xml", ".webp": "image/webp", ".js": "text/javascript"}
_FILE_DIRS = {"outputs": config.OUTPUTS_DIR, "race_results": config.RACE_RESULTS_DIR,
              "docs": config.DOCS_DIR, "config": config.CONFIG_DIR}


# --------------------------------------------------------------------------- helpers
def _resolve_member(h: str):
    """Snap a typed helm name to a known member; None if unknown (we don't create
    members from the web - add them in the CLI first)."""
    h = (h or "").strip()
    if not h:
        return None
    names = repo.member_names()
    if display(h) in names:
        return display(h)
    m = find_matches(h, names, limit=1)
    if m and canonical(m[0]) == canonical(h):
        return m[0]
    return None


def _score_race(form: dict):
    """Build entries from the form, score, save, write the raw log and render the
    result image (via the CLI helper). Returns (race_id, None) or (None, error)."""
    g = lambda k, d="": (form.get(k, [d]) or [d])[0].strip()
    date_, name = g("date"), g("name").upper()
    mode = g("mode", "standard") or "standard"
    ladies = g("ladies") == "1"
    dosc, wind, winddir = g("dosc"), g("wind"), g("winddir")

    # wind speed + direction are mandatory (drive the catamaran winter rating and
    # the wind records); the DOSC records them on the day.
    try:
        if wind == "" or float(wind) < 0:
            raise ValueError
    except ValueError:
        return (None, "Wind speed (kt) is required - check the log or ask the DOSC.", [])
    if not winddir:
        return (None, "Wind direction is required - check the log or ask the DOSC.", [])

    # task 10: before scoring the first race of a new month, fold in every
    # completed prior month's handicap update automatically (hard-timed: only
    # months past their last Sunday are applied). Then refuse to score if any
    # prior completed month is still outstanding.
    applied = repo.auto_update_before_race(date_)
    blockers = repo.updates_blocking_race(date_)
    if blockers:
        return (None,
                "Cannot score yet: the handicap update for "
                + ", ".join(blockers)
                + " has not run. It becomes available on that month's last Sunday.",
                [])
    applied_msg = ""
    if applied:
        bits = ", ".join(f"{a['period']} ({a['applied']} changed)" for a in applied)
        applied_msg = "Handicaps auto-updated for " + bits + " before scoring."

    helms = form.get("helm", [])
    boats = form.get("boat", [])
    crews = form.get("crew", [])
    starts = form.get("start", [])
    finishes = form.get("finish", [])

    boat_by = {b["sail_no"]: b for b in repo.list_boats()}
    crew_by = {c["name"]: c for c in repo.list_crew()}
    adj_map = repo.personal_adj_map()

    entries, unknown = [], []
    for i, h in enumerate(helms):
        if not (h or "").strip():
            continue
        who = _resolve_member(h)
        if not who:
            unknown.append(h.strip())
            continue
        m = repo.get_member(who)
        per = float(m["personal_hc"]) if m else 0.0
        if ladies and mode != "boat_only":
            per += 3
        cls = (boats[i] if i < len(boats) else "").strip()
        b = boat_by.get(cls)
        boat_h = float(b["boat_hc"]) if b else 0.0
        boat_make = b["make"] if b else cls
        cn = (crews[i] if i < len(crews) else "NOCREW").strip() or "NOCREW"
        cobj = crew_by.get(cn)
        crew_h = float(cobj["crew_hc"]) if (cobj and mode == "standard") else 0.0
        if mode != "standard":
            cn = "NOCREW"
        st = (starts[i] if i < len(starts) else "").strip()
        nst, _ = normalize_finish(st, require_seconds=False)
        st = nst or st
        fin_raw = (finishes[i] if i < len(finishes) else "").strip()
        code, finish = "", ""
        if fin_raw.upper() in NON_FINISH_CODES:
            code = fin_raw.upper()
        elif fin_raw:
            nf, _err = normalize_finish(fin_raw)
            if nf:
                finish = nf
            else:
                return None, f"Could not read finish time '{fin_raw}' for {who} - use HH:MM:SS or a code.", []
        entries.append(dict(
            member=who, boat_sail_no=cls, boat_make=boat_make, per_h=per,
            boat_h=boat_h, crew_h=crew_h,
            adj_h=adj_map.get(who, 0) if mode == "standard" else 0,
            crew_name=cn, start_time=st, finish_time=finish, code=code, start_group=1))

    if unknown:
        return None, ("Unknown helm(s): " + ", ".join(unknown)
                      + ". Add them in the CLI first, or check the spelling."), []
    if not entries:
        return None, "No entries were provided.", []

    distinct = sorted({en["start_time"] for en in entries if en["start_time"]})
    grp = {s: i + 1 for i, s in enumerate(distinct)}
    for en in entries:
        en["start_group"] = grp.get(en["start_time"], 1)

    results = scoring.score_race(entries, mode=mode)
    race = dict(date=date_, name=name or "CLUB RACE", dosc=dosc,
                windspeed=float(wind) if wind else 0, winddir=winddir, mode=mode,
                num_starts=max(1, len(distinct)),
                start_times=",".join(distinct),
                venue=db.get_setting("venue", ""),
                notes=f"trophy={name or 'CLUB RACE'}")
    rid = repo.save_race(race, results)
    race["race_id"] = rid
    try:
        raceio.write_race_file(race, results)
    except Exception:
        pass
    try:
        telltale._render_saved_race_png(rid, name_suffix="")   # writes to race_results/
    except Exception:
        pass
    return rid, None, applied_msg


def _gen_report(form: dict):
    """Generate a report PNG/CSV into outputs/. Returns (rel_filename, note)."""
    kind = (form.get("kind", [""]) or [""])[0]
    club = db.get_setting("club_name")
    if kind == "handicap":
        cons = awards.consistency_table(12)
        members = repo.list_members()
        active = pages._active_set()

        def rows_for(ms):
            out = []
            for m in ms:
                nm = m["name"]; c = cons.get(nm, {}); adj = repo.get_adjustment(nm)
                out.append(dict(name=nm, hc=int(m["personal_hc"]),
                                last_raced=m.get("last_raced", ""), status=m.get("status", ""),
                                races=c.get("races", 0), stars=c.get("stars", 0),
                                trend=repo.hc_trend(nm),
                                adj=(adj["adjustment"] if adj else 0), returning=False))
            return out
        freq = sorted(rows_for([m for m in members if m["name"] in active]),
                      key=lambda r: (r["hc"], r["name"]))
        p1 = telltale._outpath("handicap_frequent", "png")
        report.render_handicap_list("HANDICAP LIST \u2014 FREQUENT RACERS", freq, p1, club)
        p2 = telltale._outpath("handicap_all", "png")
        report.render_handicap_list("HANDICAP LIST \u2014 ALL MEMBERS (A\u2013Z)",
                                    sorted(rows_for(members), key=lambda r: r["name"]), p2, club)
        return os.path.basename(p1), "Handicap lists generated (frequent + all)."
    if kind == "history":
        months = int((form.get("months", ["12"]) or ["12"])[0] or 12)
        periods, series = repo.hc_history_series(months=months)
        if not periods:
            return "", "No race history yet."
        active = pages._active_set()
        chart = sorted([s for s in series if s["name"] in active],
                       key=lambda s: (s["current"], s["name"]))[:22]
        p = telltale._outpath("handicap_history_frequent", "png")
        report.render_hc_history("HANDICAP HISTORY", chart, periods, p, club,
                                 subtitle=f"Frequent racers \u2014 {periods[0]} to {periods[-1]}")
        return os.path.basename(p), "Handicap history chart generated."
    if kind == "history_table":
        months = int((form.get("months", ["12"]) or ["12"])[0] or 12)
        periods, series_rows = repo.hc_history_series(months=months)
        if not periods:
            return "", "No race history yet."
        active = pages._active_set()
        rows = sorted([s for s in series_rows if s["name"] in active],
                      key=lambda s: (s["current"] if s["current"] is not None else 9999, s["name"]))
        p = telltale._outpath("handicap_history_table", "png")
        report.render_hc_history_table(periods, rows, p, club,
                                       subtitle=f"Frequent racers \u2014 {periods[0]} to {periods[-1]}")
        return os.path.basename(p), "Handicap history table generated."
    if kind == "honours":
        years, matrix, _long = repo.honours_data()
        if not matrix:
            return "", "No trophy results to build an honours board."
        p = telltale._outpath("honours_board", "png")
        report.render_honours_board(years, matrix, p, club)
        return os.path.basename(p), "Honours board generated."
    if kind in ("awards", "season"):
        period = (form.get("period", [""]) or [""])[0].strip()
        try:
            if not period or period.lower() == "all":
                aw = awards.compute("all")
            elif len(period) == 4 and period.isdigit():
                aw = awards.compute("year", year=int(period))
            elif "-" in period and any(c.isalpha() for c in period):
                aw = awards.compute("season", season=period)
            else:
                aw = awards.compute("month", ym=period)
        except Exception as exc:
            return "", f"Could not compute awards for '{period}': {exc}"
        if not aw.get("categories"):
            return "", "Not enough racing in that period."
        p = telltale._outpath(f"summary_{aw['label']}", "png")
        report.render_season_summary(aw, p, club)
        return os.path.basename(p), f"Summary generated: {aw['label']}."
    return "", "Unknown report."


def _score_series(form: dict):
    """Score a series from the web form. Mirrors the CLI series_flow: supports the
    normal saved-handicap scheme and the two progressive schemes (task 12).
    Returns (primary_filename, note)."""
    rids = []
    for x in form.get("rid", []):
        try:
            rids.append(int(x))
        except (TypeError, ValueError):
            pass
    if not rids:
        return "", "Pick at least one race for the series."
    name = ((form.get("name", ["SERIES"]) or ["SERIES"])[0] or "SERIES").strip().upper()
    scheme = ((form.get("scheme", ["n"]) or ["n"])[0] or "n").strip().lower()[:1]
    if scheme not in ("n", "a", "b"):
        scheme = "n"
    try:
        discards = int((form.get("discards", ["0"]) or ["0"])[0] or 0)
    except ValueError:
        discards = 0
    final = "final" in form
    provisional = not final
    club = db.get_setting("club_name")
    # auto-default the qualifying threshold from the trophy rules (task 7)
    t = trophies_mod.match_trophy(name)
    minr = int(getattr(t, "min_races", 0) or 0)

    if scheme in ("a", "b"):
        out = series_prog.score_progressive(rids, scheme)
        standings = series.score_series(out["race_results"], discards, minr)
        png = telltale._outpath(f"series_{name}_{scheme}", "png")
        report.render_progressive_series(
            name, standings, out["per_race"], png, club,
            scheme_label=series_prog.SCHEME_LABEL[scheme], provisional=provisional)
        return (os.path.basename(png),
                f"{name} \u2014 {series_prog.SCHEME_LABEL[scheme]} \u2014 "
                f"{'FINAL' if final else 'PROVISIONAL'}. Standings + per-race handicap digest.")

    # ---- normal fixed-handicap series ----
    standings, labels = series.compute_series_from_db(rids, discards, minr)
    mono = series.compute_hull_series_from_db(rids, "mono", discards, minr)
    multi = series.compute_hull_series_from_db(rids, "multi", discards, minr)
    sdict = {"name": name, "discards": discards,
             "status": "FINAL" if final else "PROVISIONAL"}
    png = telltale._outpath(f"series_{name}", "png")
    report.render_series_png(sdict, standings, labels, png, club, mono=mono, multi=multi)
    pages_pngs = []
    for rid in rids:
        race = repo.get_race(rid)
        if not race:
            continue
        rs = repo.get_results(rid)
        pg = os.path.join(config.OUTPUTS_DIR, f"_seriespage_{rid}.png")
        report.render_race_png(race, rs, pg, club,
                               returning=repo.returning_members(
                                   race["date"], [x["member"] for x in rs]))
        pages_pngs.append(pg)
    pdf = telltale._outpath(f"series_{name}", "pdf")
    report.render_series_pdf(sdict, standings, labels, pages_pngs, pdf, club,
                             mono=mono, multi=multi)
    for pg in pages_pngs:
        try:
            os.remove(pg)
        except OSError:
            pass
    return (os.path.basename(png),
            f"{name} \u2014 {len(rids)} races, {discards} discard(s) \u2014 "
            f"{'FINAL' if final else 'PROVISIONAL'}. PDF also written: {os.path.basename(pdf)}.")


# --------------------------------------------------------------------------- HTTP handler
class Handler(BaseHTTPRequestHandler):
    server_version = "Telltale/1.0"

    def log_message(self, fmt, *args):       # keep the console quiet
        pass

    def _send(self, body: str, status: int = 200, ctype: str = "text/html; charset=utf-8"):
        data = body.encode("utf-8") if isinstance(body, str) else body
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _redirect(self, location: str):
        self.send_response(303)
        self.send_header("Location", location)
        self.end_headers()

    # ---- GET ----
    def do_GET(self):
        u = urlparse(self.path)
        q = parse_qs(u.query)
        path = u.path
        try:
            if path == "/" or path == "":
                return self._send(pages.dashboard())
            if path == "/handicaps":
                return self._send(pages.handicaps(scope=q.get("scope", ["frequent"])[0]))
            if path == "/history":
                return self._send(pages.history(img_rel=q.get("img", [""])[0]))
            if path == "/races":
                return self._send(pages.races())
            if path == "/race":
                rid = int(q.get("id", ["0"])[0] or 0)
                return self._send(pages.race_view(rid, img_rel=q.get("img", [""])[0],
                                                  msg=q.get("msg", [""])[0]))
            if path == "/score":
                return self._send(pages.score_form(msg=q.get("msg", [""])[0]))
            if path == "/reports":
                return self._send(pages.reports_page(note=q.get("note", [""])[0],
                                                     link=q.get("link", [""])[0]))
            if path == "/settings":
                note = ""
                if q.get("reload"):
                    n = db.import_settings_from_config()
                    note = f"Reloaded {n} settings from config/settings.csv."
                elif q.get("saved"):
                    note = "Settings saved (mirrored to config/settings.csv)."
                elif q.get("rolled"):
                    note = q.get("rolled", [""])[0]
                return self._send(pages.settings_page(note=note))
            if path.startswith("/static/"):
                return self._send_static(path[len("/static/"):])
            if path == "/favicon.ico":
                return self._send_file(os.path.join(STATIC_DIR, "favicon.ico"), ".ico")
            if path == "/about":
                return self._send(pages.about_page())
            if path == "/trophies":
                return self._send(pages.trophies_page())
            if path == "/series":
                return self._send(pages.series_page(msg=q.get("msg", [""])[0],
                                                    link=q.get("link", [""])[0]))
            if path == "/file":
                return self._serve_artifact(q)
            return self._send("<h1>404</h1>", 404)
        except Exception as exc:  # noqa: BLE001
            return self._send(pages.layout("Error",
                              f"<h1>Something went wrong</h1><pre>{pages.e(exc)}</pre>"), 500)

    # ---- POST ----
    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        raw = self.rfile.read(length).decode("utf-8") if length else ""
        form = parse_qs(raw, keep_blank_values=True)
        path = urlparse(self.path).path
        try:
            if path == "/score":
                rid, err, applied_msg = _score_race(form)
                from urllib.parse import quote
                if err:
                    return self._redirect("/score?msg=" + quote(err))
                if applied_msg:
                    return self._redirect(f"/race?id={rid}&msg=" + quote(applied_msg))
                return self._redirect(f"/race?id={rid}")
            if path == "/series":
                fn, note = _score_series(form)
                from urllib.parse import quote
                link = f"/file?d=outputs&f={quote(fn)}" if fn else ""
                return self._redirect(f"/series?msg={quote(note)}&link={quote(link)}")
            if path == "/run-updates":
                repo.run_forced_updates()
                return self._redirect("/")
            if path == "/rollback":
                res = repo.rollback_last_update()
                from urllib.parse import quote
                msg = (f"Rolled back the {res['period']} handicap update "
                       f"({res['restored']} sailors restored)."
                       if res.get("ok") else
                       res.get("msg", "Nothing to roll back."))
                return self._redirect("/settings?rolled=" + quote(msg))
            if path == "/regen":
                rid = int((form.get("id", ["0"]) or ["0"])[0] or 0)
                try:
                    telltale._render_saved_race_png(rid)
                except Exception:
                    pass
                return self._redirect(f"/race?id={rid}")
            if path == "/reports":
                fn, note = _gen_report(form)
                from urllib.parse import quote
                link = f"/file?d=outputs&f={quote(fn)}" if fn else ""
                # send the user back to the most relevant page
                kind = (form.get("kind", [""]) or [""])[0]
                if kind in ("history", "history_table") and fn:
                    return self._redirect(f"/history?img={quote(fn)}")
                return self._redirect(f"/reports?note={quote(note)}&link={quote(link)}")
            if path == "/settings":
                for k, vals in form.items():
                    if k.startswith("s_") and vals:
                        db.set_setting(k[2:], vals[0])
                return self._redirect("/settings?saved=1")
            return self._send("<h1>404</h1>", 404)
        except Exception as exc:  # noqa: BLE001
            return self._send(pages.layout("Error",
                              f"<h1>Something went wrong</h1><pre>{pages.e(exc)}</pre>"), 500)

    # ---- static / artefact serving ----
    def _send_static(self, rel: str):
        """Serve a file from the static/ folder (style.css, logos, favicon...).
        Path components are stripped so only files directly in static/ are
        reachable."""
        name = os.path.basename(rel)
        if not name:
            return self._send("<h1>404</h1>", 404)
        path = os.path.realpath(os.path.join(STATIC_DIR, name))
        if not path.startswith(os.path.realpath(STATIC_DIR) + os.sep):
            return self._send("<h1>403</h1>", 403)
        return self._send_file(path, os.path.splitext(name)[1].lower())

    def _send_file(self, path: str, ext: str):
        if not os.path.isfile(path):
            return self._send("<h1>404</h1>", 404)
        with open(path, "rb") as fh:
            data = fh.read()
        return self._send(data, 200, _CT.get(ext, "application/octet-stream"))

    def _serve_artifact(self, q):
        d = q.get("d", [""])[0]
        f = os.path.basename(q.get("f", [""])[0])     # strip any path components
        base = _FILE_DIRS.get(d)
        if not base or not f:
            return self._send("<h1>404</h1>", 404)
        path = os.path.realpath(os.path.join(base, f))
        if not path.startswith(os.path.realpath(base) + os.sep):
            return self._send("<h1>403</h1>", 403)
        return self._send_file(path, os.path.splitext(f)[1].lower())


def run(host: str = "127.0.0.1", port: int = 8765, open_browser: bool = True):
    db.init_db()
    httpd = ThreadingHTTPServer((host, port), Handler)
    url = f"http://{host}:{port}/"
    print(f"\n  Telltale web UI running at  {url}")
    print("  (the CLI is unaffected - run  python telltale.py  any time)")
    print("  Press Ctrl+C to stop.\n")
    if open_browser:
        threading.Timer(0.6, lambda: webbrowser.open(url)).start()
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\n  Stopped.")
        httpd.server_close()
