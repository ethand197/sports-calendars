#!/usr/bin/env python3
"""Build public/spurs.ics from ESPN's Spurs team schedule (standard library only)."""
import json
import sys
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

TEAM_ID = "24"  # San Antonio Spurs on ESPN
URL = f"https://site.api.espn.com/apis/site/v2/sports/basketball/nba/teams/{TEAM_ID}/schedule"
GAME_HOURS = 2.5


def parse_dt(s):
    return datetime.fromisoformat(s.replace("Z", "+00:00")).astimezone(timezone.utc)


def fetch(url):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.load(r)


def game(ev):
    comp = ev["competitions"][0]
    teams = {c.get("homeAway"): c for c in comp.get("competitors", [])}
    spurs_home = teams.get("home", {}).get("id") == TEAM_ID
    us = teams["home" if spurs_home else "away"]
    them = teams["away" if spurs_home else "home"]
    opp = them.get("team", {}).get("shortDisplayName", "TBD")
    title = f"Spurs vs. {opp}" if spurs_home else f"Spurs @ {opp}"
    if comp.get("status", {}).get("type", {}).get("completed"):
        ours = us.get("score", {}).get("displayValue", "")
        theirs = them.get("score", {}).get("displayValue", "")
        result = "W" if us.get("winner") else "L"
        title += f" ({result} {ours}-{theirs})"
    elif not ev.get("timeValid", True):
        title += " (time TBD)"
    venue = comp.get("venue") or {}
    addr = venue.get("address") or {}
    location = ", ".join(p for p in [venue.get("fullName"), addr.get("city"), addr.get("state")] if p)
    tv = [b.get("media", {}).get("shortName") for b in comp.get("broadcasts", [])]
    notes = [n.get("headline") for n in comp.get("notes", []) if n.get("headline")]
    lines = notes + ([f"TV: {', '.join(t for t in tv if t)}"] if any(tv) else [])
    return {"id": ev["id"], "title": title, "start": parse_dt(ev["date"]),
            "location": location, "lines": lines}


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


def build_ics(games):
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out = ["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//spurs-ics//EN", "CALSCALE:GREGORIAN",
           "METHOD:PUBLISH", "X-WR-CALNAME:Spurs", "REFRESH-INTERVAL;VALUE=DURATION:PT12H"]
    for g in games:
        link = f"https://www.espn.com/nba/game/_/gameId/{g['id']}"
        end = g["start"] + timedelta(hours=GAME_HOURS)
        out += ["BEGIN:VEVENT", f"UID:spurs-{g['id']}@spurs-ics", f"DTSTAMP:{stamp}",
                f"DTSTART:{g['start']:%Y%m%dT%H%M%SZ}", f"DTEND:{end:%Y%m%dT%H%M%SZ}",
                f"SUMMARY:{esc(g['title'])}", f"LOCATION:{esc(g['location'])}",
                f"DESCRIPTION:{esc(chr(10).join(g['lines'] + ['', link]))}",
                f"URL:{link}", "END:VEVENT"]
    out.append("END:VCALENDAR")
    return "\r\n".join(fold(l) for l in out) + "\r\n"


def main():
    out_path = Path(sys.argv[1] if len(sys.argv) > 1 else "public/spurs.ics")
    games = {}
    for url in [URL, f"{URL}?seasontype=3"]:  # regular season, then playoffs if any
        try:
            for ev in fetch(url).get("events", []):
                games[ev["id"]] = game(ev)
        except (urllib.error.HTTPError, KeyError, ValueError) as e:
            print(f"skipped {url} ({e})")
    if not games:
        sys.exit("ESPN returned no Spurs games - not publishing an empty calendar.")
    games = sorted(games.values(), key=lambda g: g["start"])
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(build_ics(games), encoding="utf-8", newline="")
    print(f"Wrote {len(games)} games to {out_path}")


if __name__ == "__main__":
    main()
