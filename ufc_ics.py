#!/usr/bin/env python3
"""Build public/ufc.ics from ESPN's UFC scoreboard (standard library only)."""
import json
import re
import sys
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

URL = "https://site.api.espn.com/apis/site/v2/sports/mma/ufc/scoreboard"
LOCAL = ZoneInfo("America/Chicago")  # times shown in event descriptions
EVENT_HOURS = 6                      # length of each calendar block
KEEP_PAST_DAYS = 14                  # keep recent cards for two weeks


def parse_dt(s):
    return datetime.fromisoformat(s.replace("Z", "+00:00")).astimezone(timezone.utc)


def fetch():
    req = urllib.request.Request(URL, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.load(r)


def card_details(ev):
    """Venue, start-time blocks and bout list for a fully published card."""
    comps = ev.get("competitions", [])
    venue = (comps[0].get("venue") or {}) if comps else {}
    addr = venue.get("address") or {}
    location = ", ".join(p for p in [venue.get("fullName"), addr.get("city"),
                                     addr.get("state") or addr.get("country")] if p)
    lines = []
    times = sorted({parse_dt(c["date"]) for c in comps if c.get("date")})
    labels = ["Main card", "Prelims", "Early prelims"]
    for label, t in zip(labels, reversed(times)):
        lines.append(f"{label}: {t.astimezone(LOCAL):%a %b %-d, %-I:%M %p %Z}")
    lines.append("")
    for c in reversed(comps):  # ESPN lists earliest bout first; main event is last
        names = [x.get("athlete", {}).get("displayName", "TBA") for x in c.get("competitors", [])]
        weight = (c.get("type") or {}).get("abbreviation", "")
        if len(names) == 2:
            lines.append(f"{names[0]} vs. {names[1]}" + (f" ({weight})" if weight else ""))
    return location, lines


def collect(data):
    now = datetime.now(timezone.utc)
    events = {}
    # 1) The season calendar: every announced card, name + date only
    for league in data.get("leagues", []):
        for entry in league.get("calendar", []):
            ref = (entry.get("event") or {}).get("$ref", "")
            m = re.search(r"/events/(\d+)", ref)
            if not m or "startDate" not in entry:
                continue
            events[m.group(1)] = {"id": m.group(1), "name": entry.get("label", "UFC event"),
                                  "start": parse_dt(entry["startDate"]), "location": "",
                                  "lines": ["Fight card details appear here closer to the event."]}
    # 2) The next card in full detail: real start time, venue, bouts
    for ev in data.get("events", []):
        location, lines = card_details(ev)
        events[ev["id"]] = {"id": ev["id"], "name": ev.get("name", "UFC event"),
                            "start": parse_dt(ev["date"]), "location": location, "lines": lines}
    keep = [e for e in events.values() if e["start"] > now - timedelta(days=KEEP_PAST_DAYS)]
    return sorted(keep, key=lambda e: e["start"])


def esc(t):
    return t.replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,").replace("\n", "\\n")


def fold(line):
    out, buf = [], ""
    for ch in line:
        if len((buf + ch).encode()) > 74:
            out.append(buf)
            buf = " " + ch
        else:
            buf += ch
    return "\r\n".join(out + [buf])


def build_ics(events):
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out = ["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//ufc-ics//EN", "CALSCALE:GREGORIAN",
           "METHOD:PUBLISH", "X-WR-CALNAME:UFC", "REFRESH-INTERVAL;VALUE=DURATION:PT12H"]
    for e in events:
        link = f"https://www.espn.com/mma/fightcenter/_/id/{e['id']}/league/ufc"
        desc = "\n".join(e["lines"] + ["", link])
        end = e["start"] + timedelta(hours=EVENT_HOURS)
        out += ["BEGIN:VEVENT", f"UID:ufc-{e['id']}@ufc-ics", f"DTSTAMP:{stamp}",
                f"DTSTART:{e['start']:%Y%m%dT%H%M%SZ}", f"DTEND:{end:%Y%m%dT%H%M%SZ}",
                f"SUMMARY:{esc(e['name'])}", f"LOCATION:{esc(e['location'])}",
                f"DESCRIPTION:{esc(desc)}", f"URL:{link}", "END:VEVENT"]
    out.append("END:VCALENDAR")
    return "\r\n".join(fold(l) for l in out) + "\r\n"


def main():
    out_path = Path(sys.argv[1] if len(sys.argv) > 1 else "public/ufc.ics")
    events = collect(fetch())
    if not events:
        sys.exit("ESPN returned no upcoming events - not publishing an empty calendar.")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(build_ics(events), encoding="utf-8", newline="")
    print(f"Wrote {len(events)} events to {out_path}")
    for e in events:
        print(f"  {e['start'].astimezone(LOCAL):%Y-%m-%d %I:%M %p}  {e['name']}")


if __name__ == "__main__":
    main()
