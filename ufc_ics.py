#!/usr/bin/env python3
"""Build an iCalendar (.ics) feed of upcoming UFC events from ESPN's public data.

Uses only the Python standard library. Usage:
    python ufc_ics.py public/ufc.ics
"""
import hashlib
import json
import sys
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

BASE = "https://site.api.espn.com/apis/site/v2/sports/mma/ufc/scoreboard"
LOOKBACK_DAYS = 14      # keep recent events so they don't vanish the day after
LOOKAHEAD_DAYS = 365
EVENT_HOURS = 6         # prelims through main card


def fetch(url):
    req = urllib.request.Request(url, headers={"User-Agent": "ufc-ics/1.0"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.load(r)


def parse_dt(s):
    # ESPN uses forms like "2026-11-14T23:00Z"
    s = s.replace("Z", "+00:00")
    if len(s) == 22:  # 2026-11-14T23:00+00:00 (no seconds)
        s = s[:16] + ":00" + s[16:]
    return datetime.fromisoformat(s).astimezone(timezone.utc)


def fight_lines(event):
    lines = []
    for comp in event.get("competitions", []):
        names = [c.get("athlete", {}).get("displayName", "TBA")
                 for c in comp.get("competitors", [])]
        if len(names) == 2:
            lines.append(f"{names[0]} vs. {names[1]}")
    # ESPN tends to list prelims first; reverse so the main event is on top
    return list(reversed(lines))


def location(event):
    for comp in event.get("competitions", []):
        venue = comp.get("venue") or {}
        addr = venue.get("address") or {}
        parts = [venue.get("fullName"), addr.get("city"), addr.get("state") or addr.get("country")]
        parts = [p for p in parts if p]
        if parts:
            return ", ".join(parts)
    return ""


def fetch_all(now):
    """Try several ways of asking ESPN; keep whatever works and merge it."""
    start = (now - timedelta(days=LOOKBACK_DAYS)).strftime("%Y%m%d")
    end = (now + timedelta(days=LOOKAHEAD_DAYS)).strftime("%Y%m%d")
    urls = [
        BASE,                                  # current/next card + season calendar
        f"{BASE}?dates={now.year}",            # whole current year
        f"{BASE}?dates={now.year + 1}",        # whole next year
        f"{BASE}?dates={start}-{end}",         # explicit date range
    ]
    results = []
    for url in urls:
        try:
            results.append(fetch(url))
            print(f"OK       {url}")
        except (urllib.error.HTTPError, urllib.error.URLError, ValueError) as e:
            print(f"skipped  {url}  ({e})")
    return results


def collect_events():
    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(days=LOOKBACK_DAYS)
    responses = fetch_all(now)

    events = {}
    for data in responses:
        for ev in data.get("events", []):
            try:
                when = parse_dt(ev["date"])
                if when < cutoff:
                    continue
                events[ev["id"]] = {
                    "uid": ev["id"],
                    "name": ev.get("name") or ev.get("shortName") or "UFC event",
                    "start": when,
                    "location": location(ev),
                    "fights": fight_lines(ev),
                    "link": f"https://www.espn.com/mma/fightcenter/_/id/{ev['id']}/league/ufc",
                }
            except (KeyError, ValueError):
                continue

    # The league calendar often lists further-out events the other queries miss
    seen = {(e["name"], e["start"].date()) for e in events.values()}
    for data in responses:
        for league in data.get("leagues", []):
            for entry in league.get("calendar", []):
                if not isinstance(entry, dict) or "startDate" not in entry:
                    continue
                try:
                    when = parse_dt(entry["startDate"])
                except ValueError:
                    continue
                name = entry.get("label") or "UFC event"
                if when < cutoff or (name, when.date()) in seen:
                    continue
                seen.add((name, when.date()))
                uid = f"cal-{when:%Y%m%d}-{hashlib.md5(name.encode()).hexdigest()[:8]}"
                events[uid] = {"uid": uid, "name": name, "start": when,
                               "location": "", "fights": [], "link": ""}
    return sorted(events.values(), key=lambda e: e["start"])


def esc(text):
    return (text.replace("\\", "\\\\").replace(";", "\\;")
                .replace(",", "\\,").replace("\n", "\\n"))


def fold(line):
    # RFC 5545: lines no longer than 75 octets, continuations start with a space
    out, buf = [], ""
    for
