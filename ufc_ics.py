#!/usr/bin/env python3
"""Build an iCalendar (.ics) feed of upcoming UFC events from ESPN's public data.

Uses only the Python standard library. Usage:
    python ufc_ics.py public/ufc.ics
"""
import hashlib
import json
import sys
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


def collect_events():
    now = datetime.now(timezone.utc)
    start = (now - timedelta(days=LOOKBACK_DAYS)).strftime("%Y%m%d")
    end = (now + timedelta(days=LOOKAHEAD_DAYS)).strftime("%Y%m%d")
    data = fetch(f"{BASE}?dates={start}-{end}&limit=500")

    events = {}
    for ev in data.get("events", []):
        try:
            events[ev["id"]] = {
                "uid": ev["id"],
                "name": ev.get("name") or ev.get("shortName") or "UFC event",
                "start": parse_dt(ev["date"]),
                "location": location(ev),
                "fights": fight_lines(ev),
                "link": f"https://www.espn.com/mma/fightcenter/_/id/{ev['id']}/league/ufc",
            }
        except (KeyError, ValueError):
            continue

    # The league calendar often lists further-out events that the range query misses
    seen = {(e["name"], e["start"].date()) for e in events.values()}
    for league in data.get("leagues", []):
        for entry in league.get("calendar", []):
            if not isinstance(entry, dict) or "startDate" not in entry:
                continue
            try:
                when = parse_dt(entry["startDate"])
            except ValueError:
                continue
            name = entry.get("label") or "UFC event"
            if when < now - timedelta(days=LOOKBACK_DAYS) or (name, when.date()) in seen:
                continue
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
    for ch in line:
        if len((buf + ch).encode()) > 74:
            out.append(buf)
            buf = " " + ch
        else:
            buf += ch
    out.append(buf)
    return "\r\n".join(out)


def build_ics(events):
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    lines = [
        "BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//ufc-ics//EN",
        "CALSCALE:GREGORIAN", "METHOD:PUBLISH",
        "X-WR-CALNAME:UFC", "X-WR-CALDESC:Upcoming UFC events (auto-updated)",
        "REFRESH-INTERVAL;VALUE=DURATION:PT12H", "X-PUBLISHED-TTL:PT12H",
    ]
    for e in events:
        desc = "\n".join(e["fights"]) if e["fights"] else "Card TBA"
        if e["link"]:
            desc += f"\n\n{e['link']}"
        end = e["start"] + timedelta(hours=EVENT_HOURS)
        lines += [
            "BEGIN:VEVENT",
            f"UID:ufc-{e['uid']}@ufc-ics",
            f"DTSTAMP:{stamp}",
            f"DTSTART:{e['start']:%Y%m%dT%H%M%SZ}",
            f"DTEND:{end:%Y%m%dT%H%M%SZ}",
            f"SUMMARY:{esc(e['name'])}",
            f"LOCATION:{esc(e['location'])}",
            f"DESCRIPTION:{esc(desc)}",
            "END:VEVENT",
        ]
    lines.append("END:VCALENDAR")
    return "\r\n".join(fold(l) for l in lines) + "\r\n"


def main():
    out = Path(sys.argv[1] if len(sys.argv) > 1 else "public/ufc.ics")
    events = collect_events()
    if not events:
        # Fail loudly rather than publishing an empty calendar over a good one
        sys.exit("No events returned from ESPN; leaving the existing feed alone.")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(build_ics(events), encoding="utf-8", newline="")
    print(f"Wrote {len(events)} events to {out}")
    for e in events:
        print(f"  {e['start']:%Y-%m-%d %H:%M}Z  {e['name']}")


if __name__ == "__main__":
    main()
