"""
names.py  -  Name canonicalisation and fuzzy lookup.

Real-world rosters are full of variants: "DAVID TAYLOR" vs "DAVID D. TAYLOR",
and title prefixes like "DR JANE SMITH" / "CAPT A. KHAN". This module gives the
operator type-ahead matching so they confirm a name instead of typing it, and
catches typos at entry time (no race is ever scored against an unknown name).
"""
from __future__ import annotations

import difflib
import re

# Honorifics / club prefixes seen in the data, stripped for matching only.
PREFIXES = {
    "JSM", "VH", "DR", "MR", "MRS", "MS", "MISS", "CAPT", "CDR", "LT",
    "COL", "MAJ", "BRIG", "GEN", "PROF", "ENGR", "SYED", "HAJI",
}


def canonical(name: str) -> str:
    """Normalised key for matching: upper, no punctuation, no prefixes, single spaces."""
    if not name:
        return ""
    s = name.upper().strip()
    s = re.sub(r"[.\-,]", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    words = [w for w in s.split(" ") if w not in PREFIXES]
    return " ".join(words)


def display(name: str) -> str:
    """Tidy a name for storage/display: upper, single-spaced, trimmed."""
    return re.sub(r"\s+", " ", (name or "").upper().strip())


def find_matches(query: str, known_names: list[str], limit: int = 5,
                 cutoff: float = 0.5) -> list[str]:
    """Return known display names ranked by similarity to query.

    Prefers prefix/substring hits, then falls back to fuzzy ratio.
    """
    q = canonical(query)
    if not q:
        return []
    canon_map: dict[str, list[str]] = {}
    for n in known_names:
        canon_map.setdefault(canonical(n), []).append(n)

    # 1. exact canonical hit
    if q in canon_map:
        return canon_map[q][:limit]

    scored: list[tuple[float, str]] = []
    for ckey, originals in canon_map.items():
        if not ckey:
            continue
        if ckey.startswith(q) or q in ckey:
            score = 0.95
        else:
            score = difflib.SequenceMatcher(None, q, ckey).ratio()
            # token overlap bonus (handles middle initials / word order)
            qt, ct = set(q.split()), set(ckey.split())
            if qt and ct:
                score = max(score, len(qt & ct) / len(qt | ct))
        if score >= cutoff:
            scored.append((score, originals[0]))
    scored.sort(key=lambda x: (-x[0], x[1]))
    out, seen = [], set()
    for _, name in scored:
        if name not in seen:
            out.append(name)
            seen.add(name)
        if len(out) >= limit:
            break
    return out
