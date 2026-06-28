"""
timeutil.py  -  Time parsing and elapsed-time helpers.

Many clubs use staggered starts (start groups 1-4), each with its own
start time. Elapsed time for a boat = its finish time minus the start time of the
group it started in.

All times are wall-clock strings:
    start times  : "HH:MM"      e.g. "13:30"
    finish times : "HH:MM:SS"   e.g. "14:44:12"   (seconds optional)

Pure functions, no I/O - safe to reuse from a web back-end later.
"""
from __future__ import annotations

SECONDS_PER_DAY = 86400


def parse_clock(text: str) -> int | None:
    """Parse 'HH:MM' or 'HH:MM:SS' into seconds-since-midnight.

    Returns None for blank/unparseable input (used for DNF / no-finish).
    """
    if text is None:
        return None
    text = str(text).strip()
    if not text or text in {":", "::"}:
        return None
    parts = text.split(":")
    try:
        nums = [int(p) for p in parts if p != ""]
    except ValueError:
        return None
    if not nums:
        return None
    h = nums[0]
    m = nums[1] if len(nums) > 1 else 0
    s = nums[2] if len(nums) > 2 else 0
    if not (0 <= h < 24 and 0 <= m < 60 and 0 <= s < 60):
        return None
    return h * 3600 + m * 60 + s


def format_clock(seconds: int, with_seconds: bool = True) -> str:
    """Inverse of parse_clock: seconds-since-midnight -> 'HH:MM[:SS]'."""
    seconds = int(seconds) % SECONDS_PER_DAY
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    return f"{h:02d}:{m:02d}:{s:02d}" if with_seconds else f"{h:02d}:{m:02d}"


def elapsed_seconds(start_text: str, finish_text: str) -> int | None:
    """Elapsed time in seconds between a start and a finish wall-clock time.

    Adds a full day if the finish appears earlier than the start (race ran
    past midnight - rare, but handled). Returns None if either time is blank.
    """
    start = parse_clock(start_text)
    finish = parse_clock(finish_text)
    if start is None or finish is None:
        return None
    diff = finish - start
    if diff < 0:
        diff += SECONDS_PER_DAY
    return diff


def format_elapsed(seconds: int | None) -> str:
    """Human elapsed display 'H:MM:SS' (no leading zero on hours)."""
    if seconds is None:
        return ""
    seconds = int(seconds)
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    return f"{h}:{m:02d}:{s:02d}"


def normalize_finish(text: str, require_seconds: bool = True) -> tuple[str | None, str | None]:
    """Validate and normalise a finish-time entry to 'HH:MM:SS'.

    Pads single-digit parts ('14:31:7' -> '14:31:07'), validates ranges, and
    (when require_seconds) rejects an entry that has no seconds component.

    Returns (normalised, error). Exactly one is non-None:
      ('14:31:07', None)   on success
      (None, 'reason')     if the entry is unusable
    """
    if text is None:
        return None, "no time entered"
    raw = str(text).strip()
    if not raw:
        return None, "no time entered"
    parts = raw.split(":")
    if len(parts) < 2:
        return None, "use HH:MM:SS"
    if len(parts) > 3:
        return None, "too many ':' parts"
    if require_seconds and (len(parts) < 3 or parts[2].strip() == ""):
        return None, "seconds required (HH:MM:SS)"
    nums = []
    for p in parts:
        p = p.strip()
        if p == "":
            p = "0"
        if not p.isdigit():
            return None, f"'{p}' is not a number"
        nums.append(int(p))
    while len(nums) < 3:
        nums.append(0)
    h, m, s = nums[0], nums[1], nums[2]
    if not (0 <= h < 24):
        return None, f"hour {h} out of range"
    if not (0 <= m < 60):
        return None, f"minute {m} out of range"
    if not (0 <= s < 60):
        return None, f"second {s} out of range"
    return f"{h:02d}:{m:02d}:{s:02d}", None
