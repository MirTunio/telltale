#!/usr/bin/env python3
"""
Telltale  -  Classic Sailing Race Scoring & Handicap Management
==========================================================
Base-100 corrected-time scoring, monthly +/-2 personal-handicap updates,
trophy-aware scoring, low-point series,
the monohull/multihull split, awards, fun facts, and WhatsApp-ready PNG/PDF
results written to the outputs/ folder.

Dual storage: SQLite (data/telltale.db) + a CSV mirror (data/csv/) on every write.

Run:  python telltale.py
"""
from __future__ import annotations

import os
import sys
import csv
import subprocess
from datetime import date, datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from core import config, db
from core import repository as repo
from core import report, handicap, series, refdata, awards, funfacts, mailer
from core import wind_api
from core import series_progressive as series_prog
from core import raceio
from core import trophies as trophies_mod
from core.scoring import (score_race, NON_FINISH_CODES,
                          MODE_STANDARD, MODE_BOAT_ONLY, MODE_ONE_DESIGN)
from core.names import find_matches, display

ABOUT_TEXT = config.ABOUT_TEXT
from core.timeutil import parse_clock, format_elapsed, normalize_finish

GOLD = "\033[38;5;178m"
PURP = "\033[38;5;141m"
RED = "\033[38;5;203m"
GREEN = "\033[38;5;114m"
DIM = "\033[2m"
BOLD = "\033[1m"
RST = "\033[0m"

MODE_LABELS = {MODE_STANDARD: "Standard (boat + personal + crew)",
               MODE_BOAT_ONLY: "Boat handicaps only",
               MODE_ONE_DESIGN: "One-design (scored on elapsed time)"}


def _wrap_text(s: str, width: int = 72) -> list:
    """Wrap a paragraph to `width` columns for tidy console output."""
    import textwrap
    return textwrap.wrap(s or "", width) or [""]


# --------------------------------------------------------------------------- screen
def _ansi() -> bool:
    return sys.stdout.isatty() and os.environ.get("TELLTALE_NOANSI") != "1"


def clear():
    os.system("cls" if os.name == "nt" else "clear")


def hms(seconds) -> str:
    if seconds is None:
        return ""
    s = int(round(seconds))
    return f"{s // 3600}:{(s % 3600) // 60:02d}:{s % 60:02d}"


def warn_red(msg: str):
    """Visible non-fatal warning (used when a forced/ad-hoc update or publish
    cannot complete because of missing data / configuration)."""
    if _ansi():
        print(f"  {RED}{BOLD}\u26a0  {msg}{RST}")
    else:
        print(f"  !! {msg}")


def ok_green(msg: str):
    print(f"  {GREEN}\u2713 {msg}{RST}" if _ansi() else f"  - {msg}")


# line-counting I/O so a finished entry can be collapsed to one confirmation line
_LC = 0


def _reset_lc():
    global _LC
    _LC = 0


def _out(text=""):
    global _LC
    print(text)
    _LC += 1 + text.count("\n")


def _in(prompt):
    global _LC
    val = input(prompt)
    _LC += 1
    return val.strip()


def _erase(n):
    if _ansi() and n > 0:
        sys.stdout.write(("\033[A\033[2K") * n)
        sys.stdout.flush()


def _outpath(name: str, ext: str) -> str:
    """Timestamped path inside outputs/ for user reports/queries:
    YYYYMMDD_HHMMSS_<name>.<ext>."""
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    safe = "".join(c if c.isalnum() or c in "-_" else "_" for c in name)
    return os.path.join(config.OUTPUTS_DIR, f"{ts}_{safe}.{ext}")


def _race_result_path(rid: int, name: str, ext: str = "png") -> str:
    """Path for a computed race result inside race_results/, prefixed by race
    number then timestamp:  NNNN_YYYYMMDD_HHMMSS_<name>.<ext>."""
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    safe = "".join(c if c.isalnum() or c in "-_" else "_" for c in (name or "race"))
    return os.path.join(config.RACE_RESULTS_DIR, f"{int(rid):04d}_{ts}_{safe}.{ext}")


def banner():
    fn = "banner_color.txt" if _ansi() else "banner.txt"
    p = os.path.join(config.BANNER_DIR, fn)
    if os.path.exists(p):
        with open(p, encoding="utf-8") as fh:
            print("\n" + fh.read().rstrip("\n"))
    club = (db.get_setting("club_name", "EXAMPLE SAILING CLUB") or "EXAMPLE SAILING CLUB")
    title = "  ".join(club)
    g, r = (GOLD, RST) if _ansi() else ("", "")
    print()
    print(f"  {g}{BOLD if _ansi() else ''}{title}{r}")
    print(f"  Race Scoring System")
    print("  " + "-" * max(len(title), 40))


# A compact burgee shown on the home screen each time the user returns to it.
# Uses the same block glyphs as the full splash so it renders wherever that does.
_MINI_BURGEE = ["""
       [38;5;178m█[0m[38;5;178m█[0m[38;5;178m█[0m                                                
       [38;5;178m█[0m[38;5;178m█[0m[38;5;178m█[0m[38;5;178m█[0m[38;5;178m█[0m                                              
       [38;5;178m█[0m[38;5;178m█[0m[38;5;55m█[0m[38;5;55m█[0m[38;5;178m█[0m[38;5;178m█[0m[38;5;178m█[0m[38;5;178m█[0m[38;5;178m█[0m[38;5;178m█[0m[38;5;178m█[0m                                        
       [38;5;178m█[0m[38;5;178m█[0m[38;5;55m█[0m[38;5;55m█[0m[38;5;178m█[0m[38;5;55m█[0m[38;5;55m█[0m[38;5;55m█[0m[38;5;55m█[0m[38;5;55m█[0m[38;5;55m█[0m[38;5;55m█[0m[38;5;178m█[0m[38;5;178m█[0m[38;5;178m█[0m[38;5;178m█[0m[38;5;178m█[0m                                  
       [38;5;178m█[0m[38;5;178m█[0m[38;5;55m█[0m[38;5;55m█[0m[38;5;178m█[0m[38;5;55m█[0m[38;5;55m█[0m[38;5;55m█[0m[38;5;55m█[0m[38;5;178m█[0m[38;5;178m█[0m[38;5;178m█[0m[38;5;178m█[0m[38;5;178m█[0m[38;5;178m█[0m[38;5;178m█[0m[38;5;178m█[0m[38;5;178m█[0m[38;5;178m█[0m[38;5;178m█[0m[38;5;178m█[0m[38;5;178m█[0m[38;5;178m█[0m[38;5;178m█[0m                           
       [38;5;178m█[0m[38;5;178m█[0m[38;5;55m█[0m[38;5;55m█[0m[38;5;178m█[0m[38;5;55m█[0m[38;5;55m█[0m[38;5;55m█[0m[38;5;55m█[0m[38;5;55m█[0m[38;5;178m█[0m[38;5;178m█[0m[38;5;178m█[0m[38;5;178m█[0m[38;5;178m█[0m[38;5;178m█[0m[38;5;178m█[0m[38;5;178m█[0m[38;5;178m█[0m[38;5;178m█[0m[38;5;55m█[0m[38;5;55m█[0m[38;5;55m█[0m[38;5;55m█[0m[38;5;178m█[0m[38;5;178m█[0m[38;5;178m█[0m[38;5;178m█[0m[38;5;178m█[0m[38;5;178m█[0m[38;5;178m█[0m                    
       [38;5;178m█[0m[38;5;178m█[0m[38;5;55m█[0m[38;5;55m█[0m[38;5;178m█[0m[38;5;55m█[0m[38;5;55m█[0m[38;5;55m█[0m[38;5;55m█[0m[38;5;55m█[0m[38;5;55m█[0m[38;5;55m█[0m[38;5;178m█[0m[38;5;178m█[0m[38;5;178m█[0m[38;5;178m█[0m[38;5;178m█[0m[38;5;178m█[0m[38;5;178m█[0m[38;5;178m█[0m[38;5;178m█[0m[38;5;178m█[0m[38;5;55m█[0m[38;5;55m█[0m[38;5;55m█[0m[38;5;55m█[0m[38;5;55m█[0m[38;5;55m█[0m[38;5;55m█[0m[38;5;55m█[0m[38;5;178m█[0m[38;5;178m█[0m[38;5;178m█[0m[38;5;178m█[0m[38;5;178m█[0m[38;5;178m█[0m[38;5;178m█[0m[38;5;178m█[0m             
       [38;5;178m█[0m[38;5;178m█[0m[38;5;55m█[0m[38;5;55m█[0m[38;5;178m█[0m[38;5;55m█[0m[38;5;55m█[0m[38;5;55m█[0m[38;5;55m█[0m[38;5;55m█[0m[38;5;55m█[0m[38;5;55m█[0m[38;5;55m█[0m[38;5;178m█[0m[38;5;178m█[0m[38;5;178m█[0m[38;5;178m█[0m[38;5;178m█[0m[38;5;178m█[0m[38;5;178m█[0m[38;5;178m█[0m[38;5;178m█[0m[38;5;178m█[0m[38;5;178m█[0m[38;5;55m█[0m[38;5;55m█[0m[38;5;55m█[0m[38;5;55m█[0m[38;5;55m█[0m[38;5;55m█[0m[38;5;55m█[0m[38;5;55m█[0m[38;5;55m█[0m[38;5;55m█[0m[38;5;55m█[0m[38;5;55m█[0m[38;5;55m█[0m[38;5;178m█[0m[38;5;178m█[0m[38;5;178m█[0m[38;5;178m█[0m[38;5;178m█[0m[38;5;178m█[0m        
       [38;5;178m█[0m[38;5;178m█[0m[38;5;55m█[0m[38;5;55m█[0m[38;5;178m█[0m[38;5;55m█[0m[38;5;55m█[0m[38;5;55m█[0m[38;5;55m█[0m[38;5;55m█[0m[38;5;55m█[0m[38;5;55m█[0m[38;5;55m█[0m[38;5;178m█[0m[38;5;178m█[0m[38;5;178m█[0m[38;5;55m█[0m[38;5;55m█[0m[38;5;55m█[0m[38;5;55m█[0m[38;5;55m█[0m[38;5;55m█[0m[38;5;55m█[0m[38;5;178m█[0m[38;5;178m█[0m[38;5;55m█[0m[38;5;55m█[0m[38;5;55m█[0m[38;5;55m█[0m[38;5;55m█[0m[38;5;55m█[0m[38;5;55m█[0m[38;5;55m█[0m[38;5;55m█[0m[38;5;55m█[0m[38;5;55m█[0m[38;5;178m█[0m[38;5;178m█[0m[38;5;178m█[0m[38;5;178m█[0m[38;5;178m█[0m          
       [38;5;178m█[0m[38;5;178m█[0m[38;5;55m█[0m[38;5;55m█[0m[38;5;178m█[0m[38;5;55m█[0m[38;5;55m█[0m[38;5;55m█[0m[38;5;55m█[0m[38;5;178m█[0m[38;5;178m█[0m[38;5;178m█[0m[38;5;178m█[0m[38;5;178m█[0m[38;5;178m█[0m[38;5;178m█[0m[38;5;178m█[0m[38;5;178m█[0m[38;5;178m█[0m[38;5;178m█[0m[38;5;178m█[0m[38;5;178m█[0m[38;5;178m█[0m[38;5;178m█[0m[38;5;178m█[0m[38;5;55m█[0m[38;5;55m█[0m[38;5;55m█[0m[38;5;178m█[0m[38;5;178m█[0m[38;5;178m█[0m[38;5;178m█[0m[38;5;178m█[0m[38;5;178m█[0m[38;5;178m█[0m                
       [38;5;178m█[0m[38;5;178m█[0m[38;5;55m█[0m[38;5;55m█[0m[38;5;178m█[0m[38;5;55m█[0m[38;5;55m█[0m[38;5;55m█[0m[38;5;55m█[0m[38;5;178m█[0m[38;5;178m█[0m[38;5;178m█[0m[38;5;178m█[0m[38;5;178m█[0m[38;5;178m█[0m[38;5;178m█[0m[38;5;178m█[0m[38;5;178m█[0m[38;5;178m█[0m[38;5;178m█[0m[38;5;178m█[0m[38;5;178m█[0m[38;5;178m█[0m[38;5;178m█[0m[38;5;178m█[0m[38;5;178m█[0m[38;5;178m█[0m[38;5;178m█[0m[38;5;178m█[0m                      
       [38;5;178m█[0m[38;5;178m█[0m[38;5;55m█[0m[38;5;55m█[0m[38;5;178m█[0m[38;5;55m█[0m[38;5;55m█[0m[38;5;55m█[0m[38;5;55m█[0m[38;5;55m█[0m[38;5;55m█[0m[38;5;55m█[0m[38;5;55m█[0m[38;5;55m█[0m[38;5;55m█[0m[38;5;55m█[0m[38;5;178m█[0m[38;5;178m█[0m[38;5;178m█[0m[38;5;178m█[0m[38;5;178m█[0m[38;5;178m█[0m[38;5;178m█[0m                            
       [38;5;178m█[0m[38;5;178m█[0m[38;5;55m█[0m[38;5;55m█[0m[38;5;178m█[0m[38;5;55m█[0m[38;5;55m█[0m[38;5;55m█[0m[38;5;55m█[0m[38;5;178m█[0m[38;5;178m█[0m[38;5;178m█[0m[38;5;178m█[0m[38;5;178m█[0m[38;5;178m█[0m[38;5;178m█[0m[38;5;178m█[0m                                  
       [38;5;178m█[0m[38;5;178m█[0m[38;5;55m█[0m[38;5;55m█[0m[38;5;178m█[0m[38;5;178m█[0m[38;5;178m█[0m[38;5;178m█[0m[38;5;178m█[0m[38;5;178m█[0m[38;5;178m█[0m                                        
       [38;5;178m█[0m[38;5;178m█[0m[38;5;178m█[0m[38;5;178m█[0m[38;5;178m█[0m                                              
       [38;5;178m█[0m[38;5;178m█[0m[38;5;178m█[0m                                                
       [38;5;178m█[0m                                                  
"""
]


def mini_banner():
    """Smaller home-screen mark. The big splash banner only shows once, at
    launch; this lighter logo greets the user each time they come back to the
    main menu."""
    club = (db.get_setting("club_name", "EXAMPLE SAILING CLUB") or "EXAMPLE SAILING CLUB")
    g, p, b, r = (GOLD, PURP, BOLD, RST) if _ansi() else ("", "", "", "")
    print()
    for ln in _MINI_BURGEE:
        print(f"{g}{ln}{r}")
    print(f"  {g}{b}TELLTALE{r}   {p}{club}{r}")
    print("  " + f"{p}" + "-" * max(len(club) + 11, 40) + f"{r}")


def header(title: str):
    club = db.get_setting("club_name", "Telltale")
    print("=" * 64)
    print(f"  TELLTALE  \u2014  {club}")
    print(f"  {title}")
    print("=" * 64)


def ask(prompt: str, default: str = "") -> str:
    suffix = f" [{default}]" if default else ""
    val = input(f"  {prompt}{suffix}: ").strip()
    return val or default


def ask_prefill(prompt: str, prefill: str = "") -> str:
    """Like ask(), but pre-loads `prefill` into the editable input line so the
    previous value can be tweaked in place (the 'defaults typed out in the field'
    behaviour requested for editing). Uses readline where available; otherwise
    falls back to the [default] convention (Enter keeps the prefill)."""
    if prefill and _ansi():
        try:
            import readline

            def _hook():
                readline.insert_text(prefill)
                readline.redisplay()

            readline.set_pre_input_hook(_hook)
            try:
                return input(f"  {prompt}: ").strip()
            finally:
                readline.set_pre_input_hook()        # clear the hook
        except Exception:
            pass
    return ask(prompt, prefill)


def ask_yes(prompt: str, default_yes: bool = True) -> bool:
    d = "Y/n" if default_yes else "y/N"
    val = input(f"  {prompt} [{d}]: ").strip().lower()
    return default_yes if not val else val.startswith("y")


def ask_wind_speed(current: str = "") -> str:
    """Wind speed is mandatory (it drives the catamaran winter rating and the
    wind-themed records). Loop until a non-negative number is given; if it isn't
    known on the water, the duty officer (DOSC) records it. `current` pre-fills
    the value when editing. For a fresh entry we also try a free live-wind
    lookup for the club and pre-fill it as a suggestion (offline-safe)."""
    print("  Wind speed is required - check the day's log or ask the DOSC if unsure.")
    if not current:
        live = wind_api.live_wind_kt()
        if live is not None:
            current = f"{live:.0f}"
            _out(f"    {PURP if _ansi() else ''}Live now at the club ~{live:.0f} kt "
                 f"(Open-Meteo) - pre-filled; adjust to the DOSC's reading."
                 f"{RST if _ansi() else ''}")
    while True:
        val = ask_prefill("Wind speed (kt)", current) if current else ask("Wind speed (kt)")
        val = (val or "").strip()
        try:
            if float(val) >= 0:
                return val
        except ValueError:
            pass
        warn_red("  Please enter the wind speed in knots (e.g. 8). Ask the DOSC if unknown.")


def pause():
    input("\n  Press Enter to continue...")


def open_file(path: str):
    try:
        if os.name == "nt":
            os.startfile(path)            # type: ignore[attr-defined]
        elif sys.platform == "darwin":
            subprocess.run(["open", path], check=False)
        else:
            subprocess.run(["xdg-open", path], check=False)
    except Exception:
        pass


# --------------------------------------------------------------------------- time entry
def _fmt_digits(d: str) -> str:
    out = d[:2]
    if len(d) > 2:
        out += ":" + d[2:4]
    if len(d) > 4:
        out += ":" + d[4:6]
    return out


def _read_time_tty(prompt: str):
    """Raw-mode reader that auto-inserts ':' as HH:MM:SS is typed. Letters switch
    to result-code entry (DNF/DNS/...). Returns (digits, code)."""
    import termios
    import tty
    fd = sys.stdin.fileno()
    old = termios.tcgetattr(fd)
    digits, code = "", ""

    def render():
        body = code if code else _fmt_digits(digits)
        sys.stdout.write("\r\033[2K  " + prompt + body)
        sys.stdout.flush()

    try:
        tty.setraw(fd)
        render()
        while True:
            ch = sys.stdin.read(1)
            if ch in ("\r", "\n"):
                break
            if ch == "\x03":
                raise KeyboardInterrupt
            if ch in ("\x7f", "\b"):
                if code:
                    code = code[:-1]
                elif digits:
                    digits = digits[:-1]
                render()
                continue
            if ch.isdigit() and not code:
                if len(digits) < 6:
                    digits += ch
                render()
                continue
            if (ch.isalpha() or code) and not digits:
                code += ch.upper()
                render()
                continue
            # ignore ':' (auto-inserted) and anything else
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, old)
    sys.stdout.write("\n")
    return digits, code


def read_finish_time(prompt="Finish time (HH:MM:SS) or code (DNF/DNS/DSQ): "):
    """Return ('time','HH:MM:SS') or ('code','DNF'). Forces second resolution;
    pads single-digit parts (14:31:7 -> 14:31:07). Live auto-colon on a TTY,
    plain prompt otherwise. Blank is not accepted (a time or code is required)."""
    use_tty = _ansi()
    while True:
        if use_tty:
            try:
                digits, code = _read_time_tty("  " + prompt)
            except (ImportError, Exception):  # noqa: BLE001 - fall back to plain
                use_tty = False
                continue
            if code:
                if code in NON_FINISH_CODES:
                    global _LC
                    _LC += 1
                    return "code", code
                warn_red(f"'{code}' is not a known code ({', '.join(NON_FINISH_CODES)}).")
                continue
            norm, err = normalize_finish(_fmt_digits(digits))
            if norm:
                _LC += 1
                return "time", norm
            warn_red(f"{err}")
            continue
        raw = _in("  " + prompt)
        if raw.upper() in NON_FINISH_CODES:
            return "code", raw.upper()
        norm, err = normalize_finish(raw)
        if norm:
            return "time", norm
        _out(f"    {err} - enter HH:MM:SS (seconds required) or a code.")


# --------------------------------------------------------------------------- pickers
def _pick_numbered(prompt: str, options: list[str], default_index: int = 0,
                   allow_blank: bool = False) -> str | None:
    line = "   ".join(f"{i}.{opt}" for i, opt in enumerate(options, 1))
    _out("  " + line)
    dft = options[default_index] if 0 <= default_index < len(options) else ""
    while True:
        sel = _in(f"  {prompt}" + (f" [{default_index + 1}={dft}]" if dft else "")
                  + (" (blank=skip)" if allow_blank else "") + ": ")
        if not sel:
            if allow_blank:
                return None
            if dft:
                return dft
            continue
        if sel.isdigit() and 1 <= int(sel) <= len(options):
            return options[int(sel) - 1]
        up = sel.upper()
        for o in options:
            if o.upper() == up:
                return o
        _out(f"  (1-{len(options)} please)")


def pick_member(prompt: str = "Helm name") -> str | None:
    names = repo.member_names()
    while True:
        q = _in(f"  {prompt} (blank to finish): ")
        if not q:
            return None
        matches = find_matches(q, names, limit=6)
        if matches and display(q) == matches[0]:
            return matches[0]
        if matches:
            _out("    matches:")
            for i, m in enumerate(matches, 1):
                hc = repo.get_member(m)["personal_hc"]
                _out(f"      {i}. {m}  (HC {hc:+d})")
            _out("      n. add as NEW member")
            sel = _in("    choose #, 'n', or retype: ").lower()
            if sel.isdigit() and 1 <= int(sel) <= len(matches):
                return matches[int(sel) - 1]
            if sel == "n":
                return _add_member_quick(q)
            names = repo.member_names()
            continue
        _out(f"    No match for '{q}'.")
        if ask_yes("    Add as new member?", False):
            return _add_member_quick(q)


def _add_member_quick(name: str) -> str:
    name = display(name)
    novice = ask_yes(f"    Is {name} a complete novice (starts at "
                     f"+{db.get_setting('novice_initial_hc','5')})?", False)
    m = repo.add_member(name, novice=novice)
    _out(f"    Added {name} with personal HC {m['personal_hc']:+d}.")
    return name


def pick_dosc(prompt: str = "DOSC (duty officer)", current: str = "") -> str:
    """Pick the Duty Officer the SAME way helm names are chosen: type a few
    letters and confirm from the matching members. Differences from the helm
    picker: blank means 'none' (the DOSC is optional), the current value is the
    blank-default when editing, and a name that matches no member can still be
    kept as typed (the duty officer is not always a racing member)."""
    names = repo.member_names()
    suffix = f" [{current}]" if current else " (blank = none)"
    while True:
        q = input(f"  {prompt}{suffix}: ").strip()
        if not q:
            return current                      # keep current / none
        matches = find_matches(q, names, limit=6)
        if matches and display(q) == matches[0]:
            return matches[0]
        if matches:
            print("    matches:")
            for i, m in enumerate(matches, 1):
                print(f"      {i}. {m}")
            print(f'      0. use "{display(q)}" as typed (non-member officer)')
            sel = input("    choose #, 0 to keep as typed, or retype: ").strip().lower()
            if sel == "0":
                return display(q)
            if sel.isdigit() and 1 <= int(sel) <= len(matches):
                return matches[int(sel) - 1]
            continue                            # retype
        if ask_yes(f'    No member matches "{display(q)}". Use it as typed?', True):
            return display(q)


def pick_boat_for_helm(member: str, prefer_sail: str | None = None) -> dict:
    boats = repo.list_boats()
    # when editing, prefer the boat that was used last time; otherwise the
    # member's most-sailed class (its favourite) sorts first and is the default.
    fav = prefer_sail or (repo.get_member(member) or {}).get("default_boat", "")
    boats.sort(key=lambda b: (b["sail_no"] != fav, b["make"]))
    _out(f"  Boat class for {member}:")
    for i, b in enumerate(boats, 1):
        star = " *" if b["sail_no"] == fav else "  "
        _out(f"   {i:2d}.{star}{b['make']:22s} HC {b['boat_hc']:g}")
    while True:
        sel = _in(f"  choose # [{'1=' + boats[0]['make'] if boats else ''}]: ")
        if not sel and boats:
            return boats[0]
        if sel.isdigit() and 1 <= int(sel) <= len(boats):
            return boats[int(sel) - 1]
        _out(f"  (1-{len(boats)} please)")


def maybe_winter_rating(boat: dict, rdate: str, windspeed) -> dict:
    """Strongly steer a catamaran onto the wind-correct rating: the higher
    WINTER HC in light air (a fast cat is genuinely slower then, so it is the
    fair number) and the standard/default HC once it is breezy. The split
    follows the recorded wind vs the `winter_wind_threshold` setting (default
    12 kt), not the calendar. Works both ways - it will also pull a boat back
    off a winter rating if the breeze is up. The recommended choice is the
    default, so pressing Enter accepts it."""
    if not refdata.is_multihull(boat["sail_no"]):
        return boat
    month = int(rdate[5:7]) if len(rdate) >= 7 else None
    try:
        wind = float(windspeed)
    except (TypeError, ValueError):
        wind = None
    thr = float(db.get_setting("winter_wind_threshold", "12"))
    want_winter = refdata.should_suggest_winter(boat["sail_no"], month, wind, thr)

    on_winter = boat["sail_no"].upper().endswith("_WINTER")
    # already on the wind-correct rating -> nothing to do
    if want_winter == on_winter:
        return boat
    target_key = (refdata.winter_variant(boat["sail_no"]) if want_winter
                  else refdata.base_class(boat["sail_no"]))
    target = repo.get_boat(target_key)
    if not target or target["sail_no"] == boat["sail_no"]:
        return boat

    why = (f"{wind:g} kt recorded" if wind is not None else
           f"~{refdata.typical_wind(month)} kt typical for "
           f"{datetime(2000, month, 1).strftime('%B')}")
    if want_winter:
        head = f"Light air ({why}, below the {thr:g} kt threshold)"
        q = (f"Use the RECOMMENDED winter rating HC {target['boat_hc']:g} "
             f"(vs standard {boat['boat_hc']:g})?")
    else:
        head = f"Breeze ({why}, at/above the {thr:g} kt threshold)"
        q = (f"Use the RECOMMENDED standard rating HC {target['boat_hc']:g} "
             f"(vs winter {boat['boat_hc']:g})?")
    _out(f"    {PURP if _ansi() else ''}{head} - recommended rating for the "
         f"{target['make']} catamaran.{RST if _ansi() else ''}")
    if ask_yes("    " + q, True):
        return target
    return boat


def pick_crew(prefer_name: str | None = None) -> dict:
    crew = repo.list_crew()
    cats = [c for c in crew if c["name"] in refdata.CREW_CATEGORIES]
    named = [c for c in crew if c["name"] not in refdata.CREW_CATEGORIES]
    cats.sort(key=lambda c: refdata.CREW_CATEGORIES.index(c["name"]))
    named.sort(key=lambda c: c["name"])
    ordered = cats + named
    keep = None
    if prefer_name:
        keep = next((c for c in ordered if c["name"] == display(prefer_name)), None)
    _out("  Crew:")
    half = (len(ordered) + 1) // 2
    for i in range(half):
        left = ordered[i]
        cell = f"   {i+1:2d}. {left['name']:14s} {left['crew_hc']:+g}"
        j = i + half
        if j < len(ordered):
            right = ordered[j]
            cell += f"      {j+1:2d}. {right['name']:14s} {right['crew_hc']:+g}"
        _out(cell)
    hint = f"keep {keep['name']}" if keep else "NOCREW if single-handed"
    while True:
        sel = _in(f"  choose # ({hint}) [{'keep' if keep else '1'}]: ")
        if not sel:
            return keep or ordered[0]
        if sel.isdigit() and 1 <= int(sel) <= len(ordered):
            return ordered[int(sel) - 1]
        up = sel.upper()
        for c in ordered:
            if c["name"] == up:
                return c
        _out(f"  (1-{len(ordered)} please)")


def pick_trophy() -> dict | None:
    while True:
        q = ask("Trophy / race name (blank = none)")
        if not q:
            return None
        matches = trophies_mod.find_matches(q, limit=8)
        if not matches:
            print(f"    No trophy matches '{q}'. Using it as a plain race name.")
            return {"name": display(q), "mode": MODE_STANDARD, "ladies": False,
                    "explain": "Standard club handicap.", "custom": True,
                    "adv": 3, "crew_bonus": 2, "cap": 5, "note": ""}
        if len(matches) == 1 or matches[0].name.upper() == q.strip().upper():
            t = matches[0]
        else:
            print("    matches:")
            for i, m in enumerate(matches, 1):
                tag = (" [boat-only]" if m.mode == MODE_BOAT_ONLY else
                       " [one-design]" if m.mode == MODE_ONE_DESIGN else "")
                print(f"      {i}. {m.name}{tag}")
            sel = input("    choose # or retype: ").strip()
            if not (sel.isdigit() and 1 <= int(sel) <= len(matches)):
                continue
            t = matches[int(sel) - 1]
        print(f"    -> {t.name}")
        if getattr(t, "discontinued", False):
            print("       note: this trophy is marked discontinued (kept for history).")
        print(f"       scoring: {t.explain}")
        note = t.effective_note()
        if note:
            for line in _wrap_text(note, 72):
                print(f"       {line}")
        return {"name": t.name, "mode": t.mode, "ladies": t.ladies,
                "explain": t.explain, "custom": False,
                "adv": int(getattr(t, "ladies_adv", 3) or 0),
                "crew_bonus": int(getattr(t, "crew_lady_bonus", 2) or 0),
                "cap": int(getattr(t, "ladies_cap", 5) or 0),
                "note": note}


# --------------------------------------------------------------------------- score race
def _ladies_bonus(adv: int = 3, crew_bonus: int = 2, cap: int = 5) -> int:
    """Lady-helm handicap advantage. Defaults match the club's standard +3/+2
    (capped +5) but a trophy can override these via its config (task 7/8)."""
    if not ask_yes(f"    Lady helm (+{adv})?", False):
        return 0
    total = adv
    if crew_bonus and ask_yes(f"    Crew also a lady (+{crew_bonus} more)?", False):
        total = adv + crew_bonus
    if cap:
        total = min(total, cap)
    return total


def score_race_flow():
    clear(); header("Score a Race")
    meta = _gather_race_meta()
    if meta is None:                       # task 10: a due handicap update blocks scoring
        return
    adj_map = repo.personal_adj_map()
    print("\n  --- Enter boats (blank helm name to finish) ---\n")
    entries = []
    while True:
        _reset_lc()
        e = capture_entry(meta, adj_map, entered_members=[x["member"] for x in entries])
        if e is None:                       # blank helm name -> done entering
            break
        entries.append(e)
        _erase(_LC)
        _print_entry_line(len(entries), e)

    if not entries:
        print("\n  No entries - nothing to score."); pause(); return

    _finalise_and_save(meta, entries, adj_map)


# --------------------------------------------------------------------- meta gathering
def _gather_race_meta() -> dict:
    """Collect everything about a race except the boats. Returns a `meta` dict
    that the entry, scoring and (re-)editing code all share."""
    today = date.today().isoformat()
    rdate = ask("Race date (YYYY-MM-DD)", today)

    # task 10: fold in any completed prior month's handicap update before this
    # race is scored, so a new-month race uses up-to-date handicaps. Hard-timed:
    # only months past their last Sunday are applied.
    applied = repo.auto_update_before_race(rdate)
    for a in applied:
        ok_green(f"  Handicaps auto-updated for {a['period']} "
                 f"({a['applied']} changed) before scoring.")
    blockers = repo.updates_blocking_race(rdate)
    if blockers:
        warn_red("  Cannot score yet: the handicap update for "
                 + ", ".join(blockers) + " has not run.")
        print("  It becomes available on that month's last Sunday "
              "(Backup / Data / Settings can run it once due).")
        pause()
        return None

    troph = pick_trophy()
    name = troph["name"] if troph else ask("Race name", "CLUB RACE").upper()
    mode = troph["mode"] if troph else MODE_STANDARD
    ladies = bool(troph and troph["ladies"])
    if troph and not ask_yes(f"  Use recommended scoring ({MODE_LABELS[mode]})?", True):
        mode, ladies = _pick_mode(mode, ladies)

    dosc = pick_dosc()                       # duty officer, picked like a helm name
    wind = ask_wind_speed()                  # mandatory (ask the DOSC if unknown)
    wdirs = (db.get_setting("wind_directions", "N,NE,E,SE,S,SW,W,NW") or "").split(",")
    print()
    print("  Wind direction is required - ask the DOSC if unsure.")
    winddir = _pick_numbered("Wind direction", wdirs, allow_blank=False)

    num_starts, start_times = _gather_starts()
    return dict(date=rdate, name=name, mode=mode, ladies=ladies, dosc=dosc,
                wind=wind, winddir=winddir,
                num_starts=num_starts, start_times=start_times,
                ladies_adv=int(troph.get("adv", 3)) if troph else 3,
                crew_lady_bonus=int(troph.get("crew_bonus", 2)) if troph else 2,
                ladies_cap=int(troph.get("cap", 5)) if troph else 5,
                trophy_note=(troph.get("note", "") if troph else ""))


def _pick_mode(mode, ladies):
    """Choose a scoring mode (and, unless boat-only, whether the lady-helm
    +3/+2 advantage applies). Returns (mode, ladies)."""
    modes = [MODE_STANDARD, MODE_BOAT_ONLY, MODE_ONE_DESIGN]
    labels = [MODE_LABELS[m] for m in modes]
    picked = _pick_numbered("Scoring mode", labels, default_index=modes.index(mode))
    mode = modes[labels.index(picked)]
    if mode == MODE_BOAT_ONLY:
        return mode, False
    ladies = ask_yes("  Lady-helm +3/+2 advantage in this race?", ladies)
    return mode, ladies


def _gather_starts(default_n: int = 1, existing: dict | None = None):
    """Number of start groups and each group's start time. When `existing` is
    given (editing) the prior times are pre-filled and editable in place."""
    defaults = (db.get_setting("default_start_times", "13:30,13:35,13:40,13:45")
                or "").split(",")
    num_starts = int(ask("Number of start groups", str(default_n)) or str(default_n))
    num_starts = max(1, num_starts)
    start_times = {}
    for g in range(1, num_starts + 1):
        if existing and existing.get(g):
            dft = existing[g]
        else:
            dft = defaults[g - 1] if g - 1 < len(defaults) else ""
        if existing:
            raw = ask_prefill(f"Start time for group {g} (HH:MM:SS)", dft)
        else:
            raw = ask(f"Start time for group {g} (HH:MM:SS)", dft)
        norm, err = normalize_finish(raw, require_seconds=False)
        start_times[g] = norm or raw
    return num_starts, start_times


def _starts_str(meta) -> str:
    return ", ".join(f"g{g} {meta['start_times'].get(g, '') or '--'}"
                     for g in range(1, meta["num_starts"] + 1))


# --------------------------------------------------------------------- entry capture
def capture_entry(meta, adj_map, entered_members=None):
    """Collect ONE boat (initial entry, or 'Add' while editing). Returns the
    entry dict, or None if the helm name was left blank (the 'finished' / cancel
    signal). Uses the same pickers as before, so the type-ahead behaviour and
    the on-screen entry-collapse are unchanged."""
    mode = meta["mode"]
    rdate = meta["date"]
    wind = meta["wind"]
    ladies = meta["ladies"]
    already = entered_members if entered_members is not None else []

    member = pick_member()
    if member is None:
        return None
    if member in already:
        warn_red(f"{member} is already entered in this race.")
        if not ask_yes("    Enter another boat for the same helm anyway?", False):
            return capture_entry(meta, adj_map, entered_members=already)

    m = repo.get_member(member)
    per_h = float(m["personal_hc"]) if m else 0.0
    boat = pick_boat_for_helm(member)
    boat = maybe_winter_rating(boat, rdate, wind)
    boat_h = float(boat["boat_hc"])

    crew_name, crew_h = "NOCREW", 0.0
    if mode == MODE_STANDARD:
        c = pick_crew()
        crew_name, crew_h = c["name"], float(c["crew_hc"])

    bonus = 0
    if ladies and mode != MODE_BOAT_ONLY:
        bonus = _ladies_bonus(adv=int(meta.get("ladies_adv", 3)),
                              crew_bonus=int(meta.get("crew_lady_bonus", 2)),
                              cap=int(meta.get("ladies_cap", 5)))

    adj_h = adj_map.get(member, 0) if mode == MODE_STANDARD else 0

    grp = 1
    if meta["num_starts"] > 1:
        grp = int(_in(f"  Start group (1-{meta['num_starts']}) [1]: ") or "1")
        grp = max(1, min(meta["num_starts"], grp))
    stime = meta["start_times"].get(grp, "")

    kind, val = read_finish_time()
    code = val if kind == "code" else ""
    finish_time = val if kind == "time" else ""

    return dict(member=member, boat_sail_no=boat["sail_no"], boat_make=boat["make"],
                per_h=per_h + bonus, boat_h=boat_h, crew_h=crew_h, adj_h=adj_h,
                crew_name=crew_name, start_group=grp, start_time=stime,
                finish_time=finish_time, code=code)


def _print_entry_line(n, e):
    adj = e.get("adj_h") or 0
    extras = (f" adj{adj:+g}" if adj else "")
    tail = e.get("code") or e.get("finish_time") or "no time"
    print(f"  \u2713 {n}. {e['member']}  -  {e.get('boat_make', '')}  "
          f"-  crew {e.get('crew_name', '')}{extras}  -  {tail}")


# --------------------------------------------------------------------- score / save
def _finalise_and_save(meta, entries, adj_map):
    """Score, show the table, then Save / Edit / Discard. Editing loops back and
    re-scores so the table always reflects the current entries."""
    results = []
    while True:
        n_comp = len({e["member"] for e in entries})
        if n_comp < int(db.get_setting("min_competitors", "3")):
            warn_red(f"Only {n_comp} competitor(s) - the rules require a minimum of 3.")
        results = score_race(entries, mode=meta["mode"])
        _print_results_console(meta["name"], meta["date"], meta["mode"], results)

        choice = _pick_numbered("Save this race?", ["Save", "Edit", "Discard"],
                                default_index=0)
        if choice == "Edit":
            edit_race_interactive(meta, entries, adj_map)
            if not entries:
                print("\n  All entries removed - nothing to score."); pause(); return
            continue
        if choice == "Discard":
            if ask_yes("  Discard this race - are you sure?", False):
                print("  Discarded - nothing saved."); pause(); return
            continue
        break

    rid = _persist_race(meta, results)
    _render_and_publish_race(meta, results, rid)


def _persist_race(meta, results, race_id=None):
    """Write the race + results to the store. Pass race_id to overwrite an
    existing race (used when editing a saved race)."""
    race = dict(date=meta["date"], name=meta["name"], dosc=meta.get("dosc", ""),
                windspeed=float(meta["wind"]) if meta.get("wind") else 0,
                winddir=meta.get("winddir", ""), mode=meta["mode"],
                num_starts=meta["num_starts"],
                start_times=",".join(meta["start_times"].get(g, "")
                                     for g in range(1, meta["num_starts"] + 1)),
                venue=db.get_setting("venue", ""),
                notes=f"trophy={meta['name']}")
    if race_id is not None:
        race["race_id"] = race_id
    rid = repo.save_race(race, results)
    race["race_id"] = rid
    # keep the raw race log in step with the database (same all_races format)
    try:
        raw_path = raceio.write_race_file(race, results)
        print(f"  Raw log -> {os.path.relpath(raw_path, config.BASE_DIR)}")
    except Exception as exc:                       # never block a save on this
        warn_red(f"Saved to database, but the raw log could not be written: {exc}")
    return rid


def _render_and_publish_race(meta, results, rid):
    name, rdate, mode = meta["name"], meta["date"], meta["mode"]
    race = repo.get_race(rid)
    saved = repo.get_results(rid)
    members = [r["member"] for r in saved]
    returning = repo.returning_members(rdate, members)
    month_leader = awards.month_champion(rdate[:7]) if mode == MODE_STANDARD else None
    facts = funfacts.compute(race, saved, exclude_id=rid)
    adj_applied = {r["member"]: r.get("adj_h") for r in saved if r.get("adj_h")}

    out = _race_result_path(rid, name, "png")
    report.render_race_png(race, saved, out, db.get_setting("club_name"),
                           month_leader=month_leader, fun_facts=facts,
                           returning=returning, adjustments=adj_applied)
    ok_green(f"Saved as race #{rid}.")
    print(f"  PNG -> {out}")
    if month_leader:
        print(f"  {month_leader['label']} leader so far: {month_leader['member']}")
    if ask_yes("  Open results image now?", True):
        open_file(out)
    _publish(f"{name} - {rdate} results", f"{name} results attached.", [out])
    pause()


# --------------------------------------------------------------------- interactive editor
def _print_meta_summary(meta):
    g, r = (GOLD, RST) if _ansi() else ("", "")
    print(f"\n  {g}{meta['name']}{r}   {meta['date']}   "
          f"[{MODE_LABELS.get(meta['mode'], meta['mode'])}]"
          + ("  (ladies +3/+2)" if meta.get("ladies") else ""))
    bits = []
    if meta.get("dosc"):
        bits.append(f"DOSC {meta['dosc']}")
    if meta.get("wind"):
        bits.append(f"wind {meta['wind']}kt {meta.get('winddir', '')}".strip())
    if meta["num_starts"] > 1:
        bits.append(f"{meta['num_starts']} starts ({_starts_str(meta)})")
    if bits:
        print("  " + "    ".join(bits))


def _print_entries_table(entries, highlight=None):
    print(f"\n  {'#':>2} {'Helm':18s} {'Boat':16s} {'Crew':12s} "
          f"{'Start':>8} {'Finish/Code':>12}")
    print("  " + "-" * 74)
    for i, e in enumerate(entries):
        mark = ">" if highlight == i else " "
        fin = e.get("code") or e.get("finish_time") or "-"
        print(f" {mark}{i + 1:>2} {e['member'][:18]:18s} "
              f"{e.get('boat_make', '')[:16]:16s} {e.get('crew_name', '')[:12]:12s} "
              f"{(e.get('start_time') or '-'):>8} {fin:>12}")


def _pick_entry_index(entries, prompt):
    if not entries:
        print("  (no entries yet)"); return None
    raw = ask(f"{prompt} (blank = cancel)")
    if not raw:
        return None
    if raw.isdigit() and 1 <= int(raw) <= len(entries):
        return int(raw) - 1
    warn_red(f"Enter a number 1-{len(entries)}."); return None


def edit_race_interactive(meta, entries, adj_map):
    """The 'click a field to change it' editor. Pick any field and re-enter just
    that one; its current value is pre-filled in the text box. Edits meta and
    entries in place and returns when the user is done."""
    while True:
        _print_meta_summary(meta)
        fields = [
            f"Date            {meta['date']}",
            f"Race name       {meta['name']}",
            f"Scoring mode    {MODE_LABELS.get(meta['mode'], meta['mode'])}"
            + ("  +ladies" if meta.get("ladies") else ""),
            f"DOSC            {meta.get('dosc') or '(none)'}",
            f"Wind speed      {meta.get('wind') or '(none)'}",
            f"Wind direction  {meta.get('winddir') or '(none)'}",
            f"Start groups    {meta['num_starts']}  ({_starts_str(meta)})",
            f"Entries         {len(entries)} boat(s)",
            "Done editing",
        ]
        pick = _pick_numbered("Edit which field", fields, default_index=len(fields) - 1)

        if pick.startswith("Date"):
            meta["date"] = ask_prefill("Race date (YYYY-MM-DD)", meta["date"]) or meta["date"]
        elif pick.startswith("Race name"):
            meta["name"] = (ask_prefill("Race name", meta["name"]) or meta["name"]).upper()
        elif pick.startswith("Scoring"):
            meta["mode"], meta["ladies"] = _pick_mode(meta["mode"], meta.get("ladies", False))
        elif pick.startswith("DOSC"):
            meta["dosc"] = pick_dosc(current=meta.get("dosc", ""))
        elif pick.startswith("Wind speed"):
            meta["wind"] = ask_wind_speed(current=meta.get("wind", ""))
        elif pick.startswith("Wind direction"):
            wdirs = (db.get_setting("wind_directions", "N,NE,E,SE,S,SW,W,NW") or "").split(",")
            print("  Wind direction is required - ask the DOSC if unsure.")
            cur = meta.get("winddir", "")
            di = wdirs.index(cur) if cur in wdirs else 0
            meta["winddir"] = _pick_numbered("Wind direction", wdirs,
                                             default_index=di, allow_blank=False)
        elif pick.startswith("Start groups"):
            ns, st = _gather_starts(default_n=meta["num_starts"], existing=meta["start_times"])
            meta["num_starts"], meta["start_times"] = ns, st
            for e in entries:                      # re-clamp groups + refresh times
                grp = min(max(1, e.get("start_group", 1)), ns)
                e["start_group"] = grp
                e["start_time"] = st.get(grp, e.get("start_time", ""))
        elif pick.startswith("Entries"):
            _edit_entries(meta, entries, adj_map)
        else:
            return


def _edit_entries(meta, entries, adj_map):
    while True:
        _print_entries_table(entries)
        opts = ["Edit an entry", "Add an entry", "Remove an entry",
                "Re-run every entry (prefilled)", "Back"]
        pick = _pick_numbered("Entries", opts, default_index=len(opts) - 1)
        if pick == "Edit an entry":
            idx = _pick_entry_index(entries, "Edit which entry #")
            if idx is not None:
                if _edit_one_entry(meta, adj_map, entries, idx) == "REMOVE":
                    entries.pop(idx)
        elif pick == "Add an entry":
            new = capture_entry(meta, adj_map,
                                entered_members=[e["member"] for e in entries])
            if new:
                entries.append(new)
                _print_entry_line(len(entries), new)
        elif pick == "Remove an entry":
            idx = _pick_entry_index(entries, "Remove which entry #")
            if idx is not None and ask_yes(f"  Remove {entries[idx]['member']}?", False):
                entries.pop(idx)
        elif pick.startswith("Re-run"):
            for k in range(len(entries)):
                print(f"\n  --- boat {k + 1} of {len(entries)}: "
                      f"{entries[k]['member']} ---")
                entries[k] = _rerun_entry(meta, adj_map, entries[k])
        else:
            return


def _edit_finish_prefill(current_time, current_code):
    """Edit a finish time or non-finishing code in place (prefilled). Returns
    (finish_time, code) with exactly one populated (or both blank = no time)."""
    cur = current_code or current_time or ""
    codes = ", ".join(sorted(NON_FINISH_CODES))
    while True:
        raw = ask_prefill(f"Finish time (HH:MM:SS) or code; blank = no time", cur)
        if not raw:
            return "", ""
        up = raw.upper()
        if up in NON_FINISH_CODES:
            return "", up
        norm, err = normalize_finish(raw)
        if norm:
            return norm, ""
        warn_red(f"{err} - enter HH:MM:SS (seconds required) or a code ({codes}).")


def _rerun_entry(meta, adj_map, e):
    """Re-run the data-entry steps for one boat with the previous values
    pre-filled as editable defaults (the 'redo entry, prior values as defaults'
    behaviour). Returns a fresh entry dict; the helm is kept as-is."""
    mode = meta["mode"]
    member = e["member"]
    print(f"  Helm: {member}")
    m = repo.get_member(member)
    base = float(m["personal_hc"]) if m else 0.0
    bonus = max(0.0, float(e.get("per_h") or 0) - base)   # preserve any ladies bonus

    boat = pick_boat_for_helm(member, prefer_sail=e.get("boat_sail_no"))
    boat = maybe_winter_rating(boat, meta["date"], meta["wind"])

    crew_name, crew_h = e.get("crew_name", "NOCREW"), float(e.get("crew_h") or 0)
    if mode == MODE_STANDARD:
        c = pick_crew(prefer_name=e.get("crew_name"))
        crew_name, crew_h = c["name"], float(c["crew_hc"])

    adj_h = adj_map.get(member, 0) if mode == MODE_STANDARD else 0

    grp = e.get("start_group", 1)
    if meta["num_starts"] > 1:
        grp = int(ask_prefill(f"Start group (1-{meta['num_starts']})", str(grp)) or grp)
        grp = max(1, min(meta["num_starts"], grp))
    stime = meta["start_times"].get(grp, e.get("start_time", ""))

    finish_time, code = _edit_finish_prefill(e.get("finish_time", ""), e.get("code", ""))

    return dict(member=member, boat_sail_no=boat["sail_no"], boat_make=boat["make"],
                per_h=base + bonus, boat_h=float(boat["boat_hc"]), crew_h=crew_h,
                adj_h=adj_h, crew_name=crew_name, start_group=grp, start_time=stime,
                finish_time=finish_time, code=code)


def _edit_one_entry(meta, adj_map, entries, i, allow_remove=True):
    """Field-pick editor for a single boat (mutates entries[i] in place).
    Returns 'REMOVE' if the user chose to remove it, else None."""
    mode = meta["mode"]
    while True:
        e = entries[i]
        _print_entries_table(entries, highlight=i)
        raw = ["Finish time / code",
               "Boat",
               "Crew" if mode == MODE_STANDARD else None,
               f"Start group (now {e.get('start_group', 1)})" if meta["num_starts"] > 1 else None,
               "Re-enter this whole boat",
               "Remove this boat" if allow_remove else None,
               "Done with this boat"]
        opts = [o for o in raw if o]
        pick = _pick_numbered(f"Edit #{i + 1} ({e['member']})", opts,
                              default_index=len(opts) - 1)
        if pick.startswith("Finish"):
            e["finish_time"], e["code"] = _edit_finish_prefill(
                e.get("finish_time", ""), e.get("code", ""))
        elif pick == "Boat":
            b = pick_boat_for_helm(e["member"], prefer_sail=e.get("boat_sail_no"))
            b = maybe_winter_rating(b, meta["date"], meta["wind"])
            e["boat_sail_no"], e["boat_make"] = b["sail_no"], b["make"]
            e["boat_h"] = float(b["boat_hc"])
        elif pick == "Crew":
            c = pick_crew(prefer_name=e.get("crew_name"))
            e["crew_name"], e["crew_h"] = c["name"], float(c["crew_hc"])
        elif pick.startswith("Start group"):
            g = int(ask_prefill(f"Start group (1-{meta['num_starts']})",
                                str(e.get("start_group", 1))) or e.get("start_group", 1))
            g = max(1, min(meta["num_starts"], g))
            e["start_group"] = g
            e["start_time"] = meta["start_times"].get(g, e.get("start_time", ""))
        elif pick.startswith("Re-enter"):
            entries[i] = _rerun_entry(meta, adj_map, e)
        elif pick.startswith("Remove"):
            if ask_yes(f"  Remove {e['member']} from the race?", False):
                return "REMOVE"
        else:
            return None


def _print_results_console(name, rdate, mode, results):
    print(f"\n  {name}   {rdate}   [{MODE_LABELS.get(mode, mode)}]")
    print(f"  {'Pos':>3}  {'Helm':20s} {'Boat':16s} {'Net':>4} "
          f"{'Elapsed':>9} {'Corrected':>10} {'ToWin':>7}")
    print("  " + "-" * 78)
    for r in results:
        pos = r["position"] if r["status"] == "FIN" else r["code"]
        corr = hms(r["corrected_time"]) if r["corrected_time"] is not None else ""
        tw = r.get("to_win")
        tw_s = "" if tw is None else ("\u2014" if tw == 0 else f"{tw//60}:{tw%60:02d}")
        print(f"  {str(pos):>3}  {r['member'][:20]:20s} {r['boat_make'][:16]:16s} "
              f"{r['net_h']:>4g} {format_elapsed(r['elapsed']):>9} {corr:>10} {tw_s:>7}")


# --------------------------------------------------------------------------- publishing
def _publish(subject: str, body: str, files: list[str]):
    """Optional e-mail of the generated artifacts, governed by the auto_email
    setting (off | ask | auto). Warns (never crashes) if e-mail is unconfigured."""
    setting = (db.get_setting("auto_email", "ask") or "ask").lower()
    if setting == "off":
        return
    if setting == "ask":
        to = ", ".join(mailer.recipients()) or "(no recipients set)"
        if not ask_yes(f"  E-mail this to {to}?", False):
            return
    ready, reason = mailer.is_configured()
    if not ready:
        warn_red(f"E-mail not sent - {reason}")
        print("  (The image/PDF is saved in outputs/. Configure "
              "config/email_config.ini to enable e-mail.)")
        return
    sent, msg = mailer.send(subject, body, attachments=files)
    if sent:
        ok_green(f"E-mail {msg}")
    else:
        warn_red(f"E-mail not sent - {msg}")


# --------------------------------------------------------------------------- HC update
def handicap_update_flow():
    clear(); header("Monthly Handicap Update")
    marker = db.get_setting("hc_updated_through", "") or ""
    if marker:
        print(f"  Handicaps are currently updated through {marker}.")
    pend = repo.pending_update_months()
    if pend:
        print(f"  Months awaiting an update: {', '.join(pend)}")
    today = date.today()
    ym = ask("Update period (YYYY-MM)", today.strftime("%Y-%m"))

    if marker and ym <= marker:
        warn_red(f"{ym} has already been updated (through {marker}). "
                 f"Re-updating a closed month is not allowed.")
        pause(); return

    start, end = ym + "-01", ym + "-31"
    devs, rids = repo.gather_deviations(start, end)
    if not rids:
        warn_red(f"No standard-mode races found in {ym} - nothing to update.")
        pause(); return
    cap = int(db.get_setting("hc_cap", "2"))
    minr = int(db.get_setting("hc_min_races", "2"))
    ups = handicap.compute_updates(devs, repo.current_hc_map(), cap=cap, min_races=minr)
    changing = [u for u in ups if u.applied_change != 0]
    print(f"\n  Races in {ym}: {len(rids)}   Helms with results: {len(ups)}")
    print(f"  Rule: average deviation, capped at +/-{cap}, min {minr} races.\n")
    print(f"  {'Helm':22s} {'Old':>4} {'New':>4} {'Rcs':>4} {'AvgDev':>8}  Note")
    print("  " + "-" * 70)
    for u in ups:
        flag = "*" if u.applied_change != 0 else " "
        print(f" {flag}{u.member:22s} {u.old_hc:>4} {u.new_hc:>4} {u.races:>4} "
              f"{u.avg_deviation:>+8.2f}  {u.reason}")
    print(f"\n  {len(changing)} handicap(s) will change.")
    if ask_yes("  Apply this month's update?", bool(changing)):
        summary = repo.run_month_update(ym)
        ok_green(f"Applied {ym}. {summary['applied']} handicap(s) changed. "
                 f"History + CSV updated; updated-through set to {ym}.")
        champ = awards.month_champion(ym)
        if champ:
            print(f"\n  {GOLD if _ansi() else ''}\U0001f3c6 Champion of "
                  f"{champ['label']}: {champ['member']}{RST if _ansi() else ''} "
                  f"(net {champ['net']} from {champ['sailed']} races).")
    else:
        print("  No changes written.")
    pause()


# --------------------------------------------------------------------------- data manager
def data_manager_flow():
    while True:
        clear(); header("Members, Boats, Crew & Trophies")
        print("""
    1. List members            6. Add / edit a boat class
    2. Add member              7. Mark member Active/Inactive
    3. List boat classes       8. List crew (+ HCs)
    4. List trophies           9. Edit a crew handicap
    5. Edit a personal HC     10. Personal adjustments (Johnie rule)
   11. Reapply boat HCs from reference file (boat_hc.csv, no re-seed)
    0. Back
        """)
        c = input("  Choice: ").strip()
        if c == "0":
            return
        elif c == "1":
            ms = repo.list_members()
            print(f"\n  {len(ms)} members:")
            for m in ms:
                print(f"    {m['name']:26s} HC {m['personal_hc']:+4d}  {m['status']:8s}"
                      f"  last {m['last_raced'] or '-'}")
            pause()
        elif c == "2":
            name = ask("Name")
            if name:
                _add_member_quick(name)
            pause()
        elif c == "3":
            for b in repo.list_boats():
                tag = "  [catamaran]" if refdata.is_multihull(b["sail_no"]) else ""
                print(f"    {b['sail_no']:26s} {b['make']:22s} HC {b['boat_hc']:g}{tag}")
            pause()
        elif c == "4":
            ts = repo.list_trophies()
            live = [t for t in ts if not t["discontinued"]]
            gone = [t for t in ts if t["discontinued"]]
            print(f"\n  {len(live)} active trophies"
                  + (f", {len(gone)} discontinued" if gone else "") + ":")
            for t in ts:
                tag = (" [boat-only]" if t["mode"] == "boat_only" else
                       " [one-design]" if t["mode"] == "one_design" else "")
                lad = " (+3/+2 ladies)" if t["ladies"] else ""
                yr = f"  {t['year']}" if t.get("year") else "      "
                disc = f"  {RED if _ansi() else ''}[discontinued]{RST if _ansi() else ''}" \
                       if t["discontinued"] else ""
                print(f"   {yr}  {t['name']:34s}{tag}{lad}{disc}")
            pause()
        elif c == "5":
            name = pick_member("Member")
            if name:
                m = repo.get_member(name)
                new = ask(f"New personal HC for {name}", str(m["personal_hc"]))
                repo.set_member_hc(name, int(float(new)), source="manual")
                print("  Updated (logged as manual override).")
            pause()
        elif c == "6":
            sail = ask("Class key (e.g. CLUB WAYFARER_VINTAGE)").upper()
            if sail:
                ex = repo.get_boat(sail)
                make = ask("Friendly name", ex["make"] if ex else
                           refdata.class_display(sail))
                bh = ask("Boat HC (base 100)", str(ex["boat_hc"]) if ex else "110")
                repo.add_boat(sail, make=make, boat_hc=bh)
                print("  Boat class saved.")
            pause()
        elif c == "7":
            name = pick_member("Member")
            if name:
                m = repo.get_member(name)
                newst = "Inactive" if m["status"] == "Active" else "Active"
                repo.set_member_status(name, newst)
                print(f"  {name} -> {newst}")
            pause()
        elif c == "8":
            for c2 in repo.list_crew():
                cat = "  (category)" if c2["name"] in refdata.CREW_CATEGORIES else ""
                print(f"    {c2['name']:16s} HC {c2['crew_hc']:+g}{cat}")
            print("\n  (crew handicaps are fixed - not changed by the monthly update)")
            pause()
        elif c == "9":
            name = ask("Crew name").upper()
            if name:
                hc = ask("Crew HC", "0")
                repo.add_crew(name, float(hc))
                print("  Crew handicap saved (manual).")
            pause()
        elif c == "10":
            _adjustments_flow()
        elif c == "11":
            changed = repo.apply_reference_boat_hcs()
            if not changed:
                print("\n  Boat HCs already match reference/boat_hc.csv - nothing to change.")
            else:
                print(f"\n  Updated {len(changed)} boat HC(s) from reference "
                      f"(database backed up first):")
                for cls, old, new in changed:
                    print(f"    {refdata.class_display(cls):24s} {old:g}  ->  {new:g}")
            pause()


def _adjustments_flow():
    clear(); header("Personal Adjustments  (the \"Johnie rule\")")
    print("  A transparent, logged time allowance added AFTER Helm+Boat+Crew.")
    print("  It affects corrected time only - it is excluded from the monthly")
    print("  handicap update, so it never distorts a sailor's skill rating.\n")
    rows = repo.list_adjustments()
    if rows:
        for a in rows:
            act = "" if a["active"] else "  (inactive)"
            print(f"    {a['member']:26s} {a['adjustment']:+g}".ljust(36) +
                  f"   {a['reason'][:36]}{act}")
    else:
        print("    (none yet)")
    print()
    if not ask_yes("  Add / edit an adjustment?", False):
        return
    name = pick_member("Sailor")
    if not name:
        return
    cur = repo.get_adjustment(name)
    val = ask(f"Adjustment for {name} (e.g. +3, 0 to clear advantage)",
              str(cur["adjustment"]) if cur else "0")
    reason = ask("Reason (logged)", cur["reason"] if cur else "")
    try:
        repo.set_adjustment(name, int(float(val)), reason=reason)
        ok_green(f"Saved: {name} {int(float(val)):+d}.")
    except ValueError:
        warn_red("Not a number.")
    pause()


# --------------------------------------------------------------------------- reports
def reports_flow():
    while True:
        clear(); header("Reports")
        print("""
    1. Handicap list  (frequent + all, PNG)      6. Awards (month/season/year)
    2. Race archive (list all races)             7. Head-to-head record
    3. Re-generate / edit a saved race           8. Honours board (PNG + CSV)
    4. Trophy calendar                           9. Season summary (PNG)
    5. Next trophy (announcement)               10. Handicap history (12-mo chart)
                                                  0. Back
        """)
        c = input("  Choice: ").strip()
        if c == "0":
            return
        elif c == "1":
            _handicap_lists()
        elif c == "2":
            for r in repo.list_races():
                print(f"    #{r['race_id']:>4}  {r['date'] or '----------':10s}  "
                      f"{r['name'] or '(unnamed)':26s} [{r['mode']}]")
            pause()
        elif c == "3":
            _regen_race()
        elif c == "4":
            _trophy_calendar()
        elif c == "5":
            _announce_next_trophy(verbose=True); pause()
        elif c == "6":
            _awards_report()
        elif c == "7":
            _head_to_head_report()
        elif c == "8":
            _honours_board_report()
        elif c == "9":
            _season_summary_report()
        elif c == "10":
            _hc_history_report()


def _hc_rows(members, consistency):
    rows = []
    for m in members:
        nm = m["name"]
        c = consistency.get(nm, {})
        adj = repo.get_adjustment(nm)
        rows.append(dict(name=nm, hc=int(m["personal_hc"]),
                         last_raced=m.get("last_raced", ""), status=m.get("status", ""),
                         races=c.get("races", 0), stars=c.get("stars", 0),
                         trend=repo.hc_trend(nm),
                         adj=(adj["adjustment"] if adj else 0), returning=False))
    return rows


def _handicap_lists():
    consistency = awards.consistency_table()
    members = repo.list_members()
    # frequent = active, raced within the inactive window, by handicap
    inactive = int(db.get_setting("inactive_months", "6"))
    anchor = max((m["last_raced"] for m in members if m["last_raced"]), default="")
    freq = []
    for m in members:
        if m["status"] != "Active" or not m["last_raced"]:
            continue
        ay, am = int(anchor[:4]), int(anchor[5:7])
        ly, lm = int(m["last_raced"][:4]), int(m["last_raced"][5:7])
        if (ay - ly) * 12 + (am - lm) <= inactive:
            freq.append(m)
    freq_rows = _hc_rows(freq, consistency)
    freq_rows.sort(key=lambda r: (r["hc"], r["name"]))
    all_rows = _hc_rows(members, consistency)
    all_rows.sort(key=lambda r: r["name"])

    p1 = _outpath("handicap_frequent", "png")
    report.render_handicap_list("HANDICAP LIST \u2014 FREQUENT RACERS", freq_rows, p1,
                                db.get_setting("club_name"))
    p2 = _outpath("handicap_all", "png")
    report.render_handicap_list("HANDICAP LIST \u2014 ALL MEMBERS (A\u2013Z)", all_rows, p2,
                                db.get_setting("club_name"))
    ok_green(f"Frequent racers ({len(freq_rows)}): {p1}")
    ok_green(f"All members ({len(all_rows)}): {p2}")
    if ask_yes("  Open the frequent-racers list?", True):
        open_file(p1)
    _publish("Handicap list", "Handicap lists attached.", [p1, p2])
    pause()


def _hc_history_report():
    """Q7: personal-handicap history over the past year. A line chart for the
    frequent racers (PNG) plus a full member x month CSV."""
    clear(); header("Handicap History")
    raw = ask("How many months back", "12")
    months = int(raw) if raw.isdigit() and int(raw) > 0 else 12
    periods, series = repo.hc_history_series(months=months)
    if not periods:
        warn_red("No race history yet - nothing to chart."); pause(); return

    # frequent racers = Active and raced within the inactive window (same rule as
    # the handicap list), sorted by current handicap; cap the lines for legibility
    inactive = int(db.get_setting("inactive_months", "6"))
    members = repo.list_members()
    anchor = max((m["last_raced"] for m in members if m["last_raced"]), default="")
    freq_names = set()
    if anchor:
        ay, am = int(anchor[:4]), int(anchor[5:7])
        for m in members:
            lr = m["last_raced"]
            if m["status"] == "Active" and lr:
                ly, lm = int(lr[:4]), int(lr[5:7])
                if (ay - ly) * 12 + (am - lm) <= inactive:
                    freq_names.add(m["name"])
    chart = [s for s in series if s["name"] in freq_names]
    chart.sort(key=lambda s: (s["current"], s["name"]))
    cap = 22
    truncated = len(chart) > cap
    if truncated:
        chart = chart[:cap]

    p_png = _outpath("handicap_history_frequent", "png")
    sub = (f"Frequent racers \u2014 {periods[0]} to {periods[-1]}"
           + ("  (showing strongest 22)" if truncated else ""))
    report.render_hc_history("HANDICAP HISTORY", chart, periods, p_png,
                             db.get_setting("club_name"), subtitle=sub)

    # task 11: formatted table (months oldest->newest, Current, Name; best on top)
    p_tbl = _outpath("handicap_history_table", "png")
    report.render_hc_history_table(periods, chart, p_tbl,
                                   db.get_setting("club_name"),
                                   subtitle=f"Frequent racers \u2014 {periods[0]} to {periods[-1]}")

    # full CSV: every member, one column per month
    p_csv = _outpath("handicap_history_all", "csv")
    with open(p_csv, "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["Member"] + periods + ["Current", "Status"])
        for s in sorted(series, key=lambda s: s["name"]):
            w.writerow([s["name"]] + ["" if v is None else v for v in s["points"]]
                       + [s["current"], s.get("status", "")])

    ok_green(f"Chart ({len(chart)} sailors): {p_png}")
    ok_green(f"Table ({len(chart)} sailors): {p_tbl}")
    ok_green(f"Full history CSV ({len(series)} members): {p_csv}")
    if ask_yes("  Open the chart now?", True):
        open_file(p_png)
    _publish("Handicap history", "Handicap history chart, table + CSV attached.",
             [p_png, p_tbl, p_csv])
    pause()


def _render_saved_race_png(rid, name_suffix="_regen"):
    """Render the results PNG for an already-saved race. No prompts, no pause;
    returns the output path."""
    race = repo.get_race(rid)
    saved = repo.get_results(rid)
    members = [r["member"] for r in saved]
    returning = repo.returning_members(race["date"], members)
    ml = awards.month_champion(race["date"][:7]) if race["mode"] == "standard" else None
    facts = funfacts.compute(race, saved, exclude_id=rid)
    adj_applied = {r["member"]: r.get("adj_h") for r in saved if r.get("adj_h")}
    out = _race_result_path(rid, f"{race.get('name') or 'race'}{name_suffix}", "png")
    report.render_race_png(race, saved, out, db.get_setting("club_name"),
                           month_leader=ml, fun_facts=facts, returning=returning,
                           adjustments=adj_applied)
    return out


def _race_to_meta_entries(rid):
    """Rebuild an editable (meta, entries) pair from a saved race so the same
    interactive editor used while scoring can edit a stored race."""
    race = repo.get_race(rid)
    saved = repo.get_results(rid)
    st = {}
    for i, p in enumerate((race.get("start_times") or "").split(","), 1):
        st[i] = p
    ladies = bool(getattr(trophies_mod.match_trophy(race.get("name", "")), "ladies", False))
    meta = dict(date=race.get("date", "") or "", name=race.get("name", "") or "",
                mode=race.get("mode", "standard") or "standard", ladies=ladies,
                dosc=race.get("dosc", "") or "",
                wind=("" if not race.get("windspeed") else f"{race['windspeed']:g}"),
                winddir=race.get("winddir", "") or "",
                num_starts=int(race.get("num_starts", 1) or 1),
                start_times=st or {1: ""})
    entries = []
    for r in saved:
        entries.append(dict(
            member=r["member"], boat_sail_no=r.get("boat_sail_no", "") or "",
            boat_make=r.get("boat_make", "") or "", per_h=float(r.get("per_h") or 0),
            boat_h=float(r.get("boat_h") or 0), crew_h=float(r.get("crew_h") or 0),
            adj_h=float(r.get("adj_h") or 0), crew_name=r.get("crew_name", "NOCREW") or "NOCREW",
            start_group=int(r.get("start_group", 1) or 1),
            start_time=r.get("start_time", "") or "",
            finish_time=r.get("finish_time", "") or "", code=r.get("code", "") or ""))
    return meta, entries


def _edit_saved_race(rid):
    """Load a saved race, edit it with the interactive editor, re-score and (on
    confirmation) overwrite it under the same race number, then regenerate its PNG."""
    meta, entries = _race_to_meta_entries(rid)
    adj_map = repo.personal_adj_map()
    print(f"\n  Editing saved race #{rid}: {meta['name']}  {meta['date']}")
    edit_race_interactive(meta, entries, adj_map)
    if not entries:
        warn_red("All entries were removed - the saved race was left unchanged."); return None
    results = score_race(entries, mode=meta["mode"])
    _print_results_console(meta["name"], meta["date"], meta["mode"], results)
    if not ask_yes("  Save these changes over the existing race?", True):
        print("  No changes saved."); return None
    _persist_race(meta, results, race_id=rid)
    ok_green(f"Race #{rid} updated (re-scored).")
    out = _render_saved_race_png(rid)
    print(f"  PNG -> {out}")
    if ask_yes("  Open the updated image now?", True):
        open_file(out)
    return out


def _regen_race():
    rid = ask("Race # to regenerate or edit")
    if not rid.isdigit():
        pause(); return
    rid = int(rid)
    race = repo.get_race(rid)
    if not race:
        warn_red("No such race."); pause(); return
    print(f"\n  #{rid}  {race.get('date', '')}  {race.get('name', '')}  "
          f"[{race.get('mode', '')}]")
    action = _pick_numbered("Action", ["Regenerate PNG only",
                                       "Edit the race, then regenerate"],
                            default_index=0)
    if action.startswith("Edit"):
        _edit_saved_race(rid); pause(); return
    out = _render_saved_race_png(rid)
    ok_green(f"Written: {out}")
    open_file(out)
    pause()


def _trophy_calendar():
    clear(); header("Trophy Calendar")
    today = date.today()
    # upcoming_trophies() understands both "nth Sunday of <month>" and fixed
    # "DD Month" specs, de-dups, and returns soonest-first with the matched
    # trophy object. (The old hand-rolled _nth_sunday loop assumed a different
    # calendar shape and crashed on the current {trophy, when} rows.)
    events = trophies_mod.upcoming_trophies(today, limit=24)
    if not events:
        warn_red("No trophy calendar found (reference/trophies.csv)."); pause(); return
    print(f"\n  Upcoming trophies (computed dates), soonest first:\n")
    cur_month = None
    for ev in events:
        d, name = ev["date"], ev["name_raw"]
        mlabel = d.strftime("%B %Y")
        if mlabel != cur_month:
            cur_month = mlabel
            print(f"  {GOLD if _ansi() else ''}{mlabel}{RST if _ansi() else ''}")
        t = ev.get("trophy") or trophies_mod.match_trophy(name)
        tag = ""
        if t:
            tag = (" [boat-only]" if t.mode == MODE_BOAT_ONLY else
                   " [one-design]" if t.mode == MODE_ONE_DESIGN else "")
        print(f"     {d.strftime('%a %d %b')}   {name}{tag}")
    n_disc = sum(1 for t in trophies_mod.TROPHIES if t.discontinued)
    print(f"\n  Full A\u2013Z trophy register: {len(trophies_mod.TROPHIES)} trophies "
          f"({len(trophies_mod.TROPHIES) - n_disc} active, {n_disc} discontinued).")
    if ask_yes("  Show the full register?", False):
        for t0 in sorted(trophies_mod.TROPHIES, key=lambda x: x.name):
            t = trophies_mod._apply_config(t0)     # reflect editable trophies.csv
            tag = (" [boat-only]" if t.mode == MODE_BOAT_ONLY else
                   " [one-design]" if t.mode == MODE_ONE_DESIGN else "")
            extra = []
            if getattr(t, "crew_only", False):
                extra.append("crew-scored")
            if getattr(t, "tindal", False):
                extra.append("tindals")
            if getattr(t, "ladies", False):
                extra.append(f"ladies +{getattr(t,'ladies_adv',3)}/+{getattr(t,'crew_lady_bonus',2)}")
            tags = tag + ("  {" + ", ".join(extra) + "}" if extra else "")
            yr = f"{t.year}" if t.year else "    "
            when = f"  - {t.when}" if getattr(t, "when", "") else ""
            disc = (f"  {RED if _ansi() else ''}[discontinued]{RST if _ansi() else ''}"
                    if t.discontinued else "")
            print(f"    {yr}  {t.name:34s}{tags}{when}{disc}")
            note = t.effective_note()
            if note:
                for line in _wrap_text(note, 70):
                    print(f"            {DIM if _ansi() else ''}{line}{RST if _ansi() else ''}")
    pause()


def _pick_period(kind_prompt=True):
    """Return ('month'|'season'|'year'|'all', kwargs) from the operator."""
    opt = _pick_numbered("Period", ["Month", "Season", "Year", "All-time"],
                         default_index=2)
    if opt == "Month":
        ym = ask("Month (YYYY-MM)", date.today().strftime("%Y-%m"))
        return "month", {"ym": ym}
    if opt == "Season":
        yr = int(ask("Year", str(date.today().year)) or date.today().year)
        season = _pick_numbered("Season", list(config.SEASONS.keys()))
        return "season", {"year": yr, "season": season}
    if opt == "Year":
        yr = int(ask("Year", str(date.today().year)) or date.today().year)
        return "year", {"year": yr}
    return "all", {}


def _awards_report():
    clear(); header("Awards")
    kind, kw = _pick_period()
    aw = awards.compute(kind, **kw)
    print(f"\n  {BOLD if _ansi() else ''}{aw['label']}{RST if _ansi() else ''}  "
          f"({aw['races']} races, qualify with {aw['min_to_qualify']}+ races)\n")
    if not aw["categories"]:
        warn_red("Not enough racing in this period for awards."); pause(); return
    for c in aw["categories"]:
        print(f"    {GOLD if _ansi() else ''}{c['award']:22s}{RST if _ansi() else ''} "
              f"{c['member']:24s} {c['detail']}")
    print(f"\n  Top of overall standings:")
    for s in aw["overall"][:8]:
        print(f"    {s['rank']:>2}. {s['member']:24s} net {s['net']:>4}  "
              f"({s['sailed']} races, {s['wins']} win(s))")
    if ask_yes("\n  Export a season-summary PNG?", False):
        out = _outpath(f"summary_{aw['label']}", "png")
        report.render_season_summary(aw, out, db.get_setting("club_name"))
        ok_green(f"Written: {out}"); open_file(out)
    pause()


def _head_to_head_report():
    clear(); header("Head-to-Head")
    a = pick_member("First sailor")
    if not a:
        return
    b = pick_member("Second sailor")
    if not b:
        return
    h = awards.head_to_head(a, b)
    print(f"\n  {h['a']}  vs  {h['b']}")
    print(f"  Met in {h['meetings']} race(s) both finished.")
    print(f"  {h['a']}: {h['a_wins']} wins    {h['b']}: {h['b_wins']} wins")
    if h["detail"]:
        print("\n  Most recent meetings:")
        for d in h["detail"][-8:]:
            print(f"    {d['date']}  {d['race'][:24]:24s}  "
                  f"{h['a']} {d['a_pos']} - {d['b_pos']} {h['b']}  "
                  f"-> {d['winner']}")
    pause()


def _honours_board_report():
    clear(); header("Honours Board")
    years, matrix, long_rows = repo.honours_data()
    if not matrix:
        warn_red("No trophy results to build an honours board."); pause(); return
    png = _outpath("honours_board", "png")
    report.render_honours_board(years, matrix, png, db.get_setting("club_name"))
    csv_path = _outpath("honours_board", "csv")
    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["Trophy", "Year", "Winner", "Date", "Boat"])
        for r in long_rows:
            w.writerow([r["trophy"], r["year"], r["winner"], r["date"], r["boat"]])
    ok_green(f"PNG: {png}")
    ok_green(f"CSV: {csv_path}  ({len(long_rows)} trophy-years)")
    if ask_yes("  Open the honours board?", True):
        open_file(png)
    _publish("Honours board", "Honours board attached.", [png, csv_path])
    pause()


def _season_summary_report():
    clear(); header("Season Summary")
    kind, kw = _pick_period()
    aw = awards.compute(kind, **kw)
    if not aw["categories"]:
        warn_red("Not enough racing in this period."); pause(); return
    out = _outpath(f"summary_{aw['label']}", "png")
    report.render_season_summary(aw, out, db.get_setting("club_name"))
    ok_green(f"Written: {out}")
    if ask_yes("  Open it?", True):
        open_file(out)
    _publish(f"{aw['label']} season summary", "Season summary attached.", [out])
    pause()


# --------------------------------------------------------------------------- series
def series_flow():
    clear(); header("Series / Trophy Scoring")
    recent = repo.list_races()
    recent = sorted(recent, key=lambda r: (r["date"], r["race_id"]))[-12:]   # task 6: last 12
    if recent:
        print("  Most recent 12 races:")
        for r in recent:
            print(f"    #{r['race_id']:>4}  {r['date'] or '----------':10s}  "
                  f"{r['name'] or '(unnamed)':26s} [{r['mode']}]")
        print()
    print("  Enter the race numbers in the series (comma-separated), or 'b' to go back.")
    raw = ask("Race numbers", "")
    if raw.strip().lower() in ("b", "back", "q"):     # task 6: back option
        return
    try:
        rids = [int(x) for x in raw.replace(" ", "").split(",") if x]
    except ValueError:
        warn_red("Invalid list."); pause(); return
    if not rids:
        return
    sname = ask("Series / trophy name", "SERIES").upper()
    # auto-default discards/min from the trophy rules if recognised (task 7)
    t = trophies_mod.match_trophy(sname)
    def_disc = str(getattr(t, "discards", 0) or 0)
    def_min = str(getattr(t, "min_races", 0) or 0)
    discards = int(ask("Number of discards", def_disc) or "0")
    minr = int(ask("Minimum races to qualify", def_min) or "0")

    # task 12: progressive handicap scheme
    print("\n  Handicap scheme for this series:")
    print("    [n] Normal - use each race's saved club handicap (default)")
    print("    [a] Progressive +/-1 per race, everyone starts at 0 (Commodore-style)")
    print("    [b] Progressive NHC-style, everyone starts at base 100")
    scheme = (ask("Scheme", "n") or "n").strip().lower()[:1]
    if scheme not in ("n", "a", "b"):
        scheme = "n"
    # task 12: provisional vs final
    final = ask_yes("  Is the series complete (Final)?", False)
    provisional = not final

    club = db.get_setting("club_name")
    if scheme in ("a", "b"):
        out = series_prog.score_progressive(rids, scheme)
        standings = series.score_series(out["race_results"], discards, minr)
        print(f"\n  {sname}  -  {series_prog.SCHEME_LABEL[scheme]}  -  "
              f"{'FINAL' if final else 'PROVISIONAL'}\n")
        print(f"  {'Rank':>4} {'Helm':22s} {'Nett':>5} {'Total':>6} {'Sailed':>7}")
        print("  " + "-" * 50)
        for s in standings:
            print(f"  {s['rank']:>4} {s['member']:22s} {s['nett']:>5} "
                  f"{s['total']:>6} {s['sailed']:>7}")
        png = _outpath(f"series_{sname}_{scheme}", "png")
        report.render_progressive_series(
            sname, standings, out["per_race"], png, club,
            scheme_label=series_prog.SCHEME_LABEL[scheme], provisional=provisional)
        ok_green(f"PNG (standings + per-race HC digest): {png}")
        if ask_yes("  Open the PNG?", True):
            open_file(png)
        _publish(f"{sname} series ({'final' if final else 'provisional'})",
                 "Progressive series standings + per-race handicap digest attached.", [png])
        pause()
        return

    # ---- normal fixed-handicap series (existing behaviour) ----
    standings, labels = series.compute_series_from_db(rids, discards, minr)
    mono = series.compute_hull_series_from_db(rids, "mono", discards, minr)
    multi = series.compute_hull_series_from_db(rids, "multi", discards, minr)

    print(f"\n  {sname}  -  {len(rids)} races, {discards} discard(s)  -  "
          f"{'FINAL' if final else 'PROVISIONAL'}\n")
    print(f"  {'Rank':>4} {'Helm':22s} {'Nett':>5} {'Total':>6} {'Sailed':>7}")
    print("  " + "-" * 50)
    for s in standings:
        print(f"  {s['rank']:>4} {s['member']:22s} {s['nett']:>5} "
              f"{s['total']:>6} {s['sailed']:>7}")

    sdict = {"name": sname, "discards": discards,
             "status": "FINAL" if final else "PROVISIONAL"}
    png = _outpath(f"series_{sname}", "png")
    report.render_series_png(sdict, standings, labels, png, club,
                             mono=mono, multi=multi)
    pages = []
    for rid in rids:
        race = repo.get_race(rid)
        if not race:
            continue
        rs = repo.get_results(rid)
        pg = os.path.join(config.OUTPUTS_DIR, f"_seriespage_{rid}.png")
        report.render_race_png(race, rs, pg, club,
                               returning=repo.returning_members(
                                   race["date"], [x["member"] for x in rs]))
        pages.append(pg)
    pdf = _outpath(f"series_{sname}", "pdf")
    report.render_series_pdf(sdict, standings, labels, pages, pdf, club,
                             mono=mono, multi=multi)
    for pg in pages:
        try:
            os.remove(pg)
        except OSError:
            pass
    ok_green(f"PNG: {png}")
    ok_green(f"PDF (standings + {len(pages)} race pages): {pdf}")
    if ask_yes("  Open the standings PNG?", True):
        open_file(png)
    _publish(f"{sname} series ({'final' if final else 'provisional'})",
             "Series standings + race pages attached.", [png, pdf])
    pause()


# --------------------------------------------------------------------------- admin
def admin_flow():
    while True:
        clear(); header("Backup / Data / Settings")
        print("""
    1. Take a manual backup (.db)
    2. CSV snapshot (timestamped, full data dump)
    3. Reload from a backup  [restore .db or rebuild from CSV]
    4. Rebuild from reference data  [WARNING: replaces all data]
    5. Settings
    6. Roll back the last handicap update
    7. About Telltale
    0. Back
        """)
        c = input("  Choice: ").strip()
        if c == "0":
            return
        elif c == "1":
            ok_green(f"Backup: {db.backup()}"); pause()
        elif c == "2":
            snap = db.snapshot_csv()
            ok_green(f"CSV snapshot written: {snap}")
            print("  (Per-table CSVs + a combined all_data.csv; current mirror "
                  "in data/csv/ also refreshed.)")
            pause()
        elif c == "3":
            _reload_flow()
        elif c == "4":
            print("\n  This wipes members/boats/crew/races and rebuilds from the")
            print("  reference lists + race archive, re-walking the handicaps.")
            if ask_yes("  Proceed?", False):
                from core.seed import seed
                print("\n", seed()); pause()
        elif c == "5":
            _settings_flow()
        elif c == "6":
            _rollback_flow()
        elif c == "7":
            _about_flow()


def _rollback_flow():
    clear(); header("Roll Back Last Handicap Update")
    period = repo.last_update_period()
    if not period:
        warn_red("No monthly handicap update on record to roll back."); pause(); return
    print(f"\n  The most recent monthly handicap update was for: {period}")
    print("  Rolling back restores every affected helm's personal handicap to its")
    print("  value before that month and moves the 'updated through' marker back.")
    print("  A backup is taken first.")
    if not ask_yes(f"\n  Roll back the {period} update?", False):
        return
    res = repo.rollback_last_update()
    if res.get("ok"):
        ok_green(f"Rolled back {res['period']}: restored {res['restored']} helm(s).")
        ok_green(f"'Updated through' marker is now: {res['marker'] or '(none)'}")
    else:
        warn_red(res.get("msg", "Rollback failed."))
    pause()


def _about_flow():
    clear(); header("About Telltale")
    print(f"""
  {ABOUT_TEXT}
""")
    pause()


def _reload_flow():
    clear(); header("Reload from Backup")
    print("""
    1. Restore from a .db backup file
    2. Rebuild the database from a CSV snapshot
    3. Rebuild the database from the current CSV mirror (fresh install)
    0. Cancel
    """)
    c = input("  Choice: ").strip()
    if c == "1":
        backups = db.list_db_backups()
        if not backups:
            warn_red("No .db backups found."); pause(); return
        for i, b in enumerate(backups[-15:], 1):
            print(f"    {i}. {b}")
        sel = ask("Restore which # (most recent listed last)")
        recent = backups[-15:]
        if sel.isdigit() and 1 <= int(sel) <= len(recent):
            db.restore_from_db(recent[int(sel) - 1])
            ok_green(f"Restored from {recent[int(sel)-1]} (a safety backup was taken first).")
        pause()
    elif c == "2":
        snaps = db.list_csv_snapshots()
        if not snaps:
            warn_red("No CSV snapshots found (Admin -> CSV snapshot)."); pause(); return
        for i, s in enumerate(snaps[-15:], 1):
            print(f"    {i}. {s}")
        sel = ask("Rebuild from which snapshot #")
        recent = snaps[-15:]
        if sel.isdigit() and 1 <= int(sel) <= len(recent):
            counts = db.restore_from_csv(recent[int(sel) - 1])
            ok_green(f"Rebuilt from {recent[int(sel)-1]}: "
                     f"{sum(counts.values())} rows across {len(counts)} tables.")
        pause()
    elif c == "3":
        if ask_yes("  Rebuild the database from data/csv/ (current mirror)?", False):
            counts = db.restore_from_csv()
            ok_green(f"Rebuilt from CSV mirror: {sum(counts.values())} rows.")
        pause()


def _settings_flow():
    keys = (list(config.DEFAULT_SETTINGS.keys()) +
            list(config.EXTRA_SETTINGS.keys()))
    # de-dup while preserving order
    seen, ordered = set(), []
    for k in keys:
        if k not in seen:
            seen.add(k); ordered.append(k)
    print()
    for i, k in enumerate(ordered, 1):
        print(f"    {i:2d}. {k} = {db.get_setting(k)}")
    sel = input("  Edit which # (blank to cancel): ").strip()
    if sel.isdigit() and 1 <= int(sel) <= len(ordered):
        k = ordered[int(sel) - 1]
        v = ask(f"New value for {k}", db.get_setting(k) or "")
        db.set_setting(k, v)
        ok_green("Saved.")
    pause()


# --------------------------------------------------------------------------- next trophy
def _announce_next_trophy(verbose=False):
    nt = trophies_mod.next_trophy(date.today())
    if not nt:
        if verbose:
            print("\n  No upcoming trophies on the calendar.")
        return
    when = nt["date"].strftime("%a %d %b %Y")
    label = nt["trophy"].name if nt["trophy"] else nt["name_raw"]
    if verbose:
        print(f"\n  NEXT TROPHY  -  {label}")
        print(f"  Date:    {when}  ({nt['days_away']} days away)")
        if nt["trophy"]:
            print(f"  Scoring: {nt['trophy'].explain}")
    else:
        g, r = (GOLD, RST) if _ansi() else ("", "")
        print(f"  {g}Next trophy:{r} {label}  -  {when}  ({nt['days_away']} days)")


# --------------------------------------------------------------------------- startup update
def _startup_forced_update():
    """Task 4: on startup, walk forward and apply any monthly handicap updates
    that are due for completed months. Missing-data / errors are flagged in RED
    and the program continues normally (task note b)."""
    try:
        pend = repo.pending_update_months()
        if not pend:
            return
        print()
        print(f"  Applying overdue monthly handicap update(s): {', '.join(pend)}")
        results = repo.run_forced_updates()
        for s in results:
            if s.get("blocked"):
                continue
            champ = awards.month_champion(s["period"])
            cl = f"  champion: {champ['member']}" if champ else ""
            ok_green(f"{s['period']}: {s['applied']} handicap change(s) "
                     f"from {s['races']} race(s).{cl}")
        print()
    except Exception as exc:  # noqa: BLE001 - never block startup
        warn_red(f"Startup handicap update could not complete: {exc}")
        warn_red("Continuing in normal operation - run Monthly Handicap Update "
                 "manually when the data is available.")


# --------------------------------------------------------------------------- main
def main_menu():
    db.init_db()
    if not repo.list_races():
        clear(); banner()
        print()
        if ask_yes("  No data yet. Build from the reference lists + race archive?", True):
            from core.seed import seed
            print("\n", seed()); pause()

    _startup_forced_update()

    first = True
    while True:
        clear()
        if first:
            banner(); first = False
        else:
            mini_banner()
        print()
        _announce_next_trophy(verbose=False)
        print("""
    1. Score a Race
    2. Monthly Handicap Update
    3. Members, Boats, Crew & Trophies
    4. Reports
    5. Series / Trophy Scoring
    6. Backup / Data / Settings
    0. Exit
        """)
        c = input("  Choice: ").strip()
        if c == "0":
            print("\n  Fair winds.\n"); break
        elif c == "1":
            score_race_flow()
        elif c == "2":
            handicap_update_flow()
        elif c == "3":
            data_manager_flow()
        elif c == "4":
            reports_flow()
        elif c == "5":
            series_flow()
        elif c == "6":
            admin_flow()


if __name__ == "__main__":
    try:
        main_menu()
    except (KeyboardInterrupt, EOFError):
        print("\n  Fair winds.\n")
