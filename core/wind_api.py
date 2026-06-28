"""
wind_api.py  -  Optional *live* wind-speed suggestion from a free, key-less API.

This only ever pre-fills a suggestion on the (mandatory) wind-speed prompt to
save the DOSC a guess; the on-water reading the DOSC enters is always the value
that gets stored. Every call is wrapped so that being offline - or any hiccup
from the service - silently yields no suggestion and never blocks or crashes
race entry.

Source: Open-Meteo (https://open-meteo.com) - free for non-commercial use and
requires no API key. We ask for the current 10 m wind directly in knots.
"""
from __future__ import annotations

import json
import urllib.request

from . import config

_TIMEOUT = 3.0  # seconds - short, so offline use is not noticeably slowed


def live_wind_kt(lat: float | None = None, lon: float | None = None) -> float | None:
    """Current 10 m wind speed in knots at the venue, or ``None`` if it could
    not be fetched for any reason. Safe to call unconditionally."""
    lat = config.VENUE_LAT if lat is None else lat
    lon = config.VENUE_LON if lon is None else lon
    url = ("https://api.open-meteo.com/v1/forecast"
           f"?latitude={lat:.4f}&longitude={lon:.4f}"
           "&current=wind_speed_10m&wind_speed_unit=kn")
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Telltale"})
        with urllib.request.urlopen(req, timeout=_TIMEOUT) as resp:
            data = json.load(resp)
        kt = float(data["current"]["wind_speed_10m"])
    except Exception:
        return None
    if kt < 0 or kt > 120:          # obviously bad reading -> no suggestion
        return None
    return kt
