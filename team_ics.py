#!/usr/bin/env python3
"""Build one calendar feed per team from ESPN team schedules (standard library only).

To add a team, add one line to TEAMS. Usage: python team_ics.py public
"""
import json
import sys
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

# feed name: (calendar name, sport, league, ESPN team id, game length in hours)
TEAMS = {
    "spurs":   ("Spurs",   "basketball", "nba", "24", 2.5),
    "packers": ("Packers", "football",   "nfl", "9",  3.5),
}


def parse_dt(s):
    return datetime.fromisoformat(s.replace("Z", "+00:00")).astimezone(timezone.utc)


def fetch(url):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.load(r)


def game(ev, team_id, short):
    comp = ev["competitions"][0]
    sides = {c.get("homeAway"): c for c in comp.get("competitors", [])}
    home = sides.get("home", {}).get("id") == team_id
    us = sides["home" if home else "away"]
    them = sides["away" if home else "home"]
    opp = them.get("team", {}).get("shortDisplayName", "TBD")
    title = f"{short} vs. {opp}" if home else f"{short} @ {opp}"
    if comp.get("status", {}).get("type", {}).get("completed"):
        ours = us.get("score", {}).get("displayValue", "")
        theirs = them.get("score", {}).get("displayValue", "")
        title += f" ({'W' if us.get('winner') else 'L'} {ours}-{theirs})"
    elif not ev.get("timeValid", True):
        title += " (time TBD)"
    venue = comp.get("venue") or {}
    addr = venue.get("address") or {}
    location = ", ".join(p for p in [venue.get("fullName"), addr.get("city"), addr.get("state")] if p)
    week = (ev.get("week") or {}).get("text")
    notes = [n.get("headline") for n in comp.get("notes", []) if n.get("headline")]
    tv = [b.get("media", {}).get("shortName") for b in comp.get("broadcasts", [])]
    lines = ([week] if week else []) + notes
    if any(tv):
        lines.append("TV: " + ", ".join(t for t in tv if t))
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


def build_ics(key, name, league, games, hours):
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out = ["BEGIN:VCALENDAR", "VERSION:2.0", f"PRODID:-//{key}-ics//EN", "CALSCALE:GREGORIAN",
           "METHOD:PUBLISH", f"X-WR-CALNAME:{name}", "REFRESH-INTERVAL;VALUE=DURATION:PT12H"]
    for g in games:
        link = f"https://www.espn.com/{league}/game/_/gameId/{g['id']}"
        end = g["start"] + timedelta(hours=hours)
        out += ["BEGIN:VEVENT", f"UID:{key}-{g['id']}@sports-calendars", f"DTSTAMP:{stamp}",
                f"DTSTART:{g['start']:%Y%m%dT%H%M%SZ}", f"DTEND:{end:%Y%m%dT%H%M%SZ}",
                f"SUMMARY:{esc(g['title'])}", f"LOCATION:{esc(g['location'])}",
                f"DESCRIPTION:{esc(chr(10).join(g['lines'] + ['', link]))}",
                f"URL:{link}", "END:VEVENT"]
    out.append("END:VCALENDAR")
    return "\r\n".join(fold(l) for l in out) + "\r\n"


def main():
    out_dir = Path(sys.argv[1] if len(sys.argv) > 1 else "public")
    out_dir.mkdir(parents=True, exist_ok=True)
    failed = []
    for key, (name, sport, league, team_id, hours) in TEAMS.items():
        base = f"https://site.api.espn.com/apis/site/v2/sports/{sport}/{league}/teams/{team_id}/schedule"
        games = {}
        for url in [base, f"{base}?seasontype=3"]:  # regular season, then playoffs if any
            try:
                for ev in fetch(url).get("events", []):
                    games[ev["id"]] = game(ev, team_id, name)
            except (urllib.error.HTTPError, KeyError, ValueError) as e:
                print(f"{name}: skipped {url} ({e})")
        if not games:
            failed.append(name)
            continue
        games = sorted(games.values(), key=lambda g: g["start"])
        (out_dir / f"{key}.ics").write_text(build_ics(key, name, league, games, hours),
                                            encoding="utf-8", newline="")
        print(f"{name}: wrote {len(games)} games to {out_dir / (key + '.ics')}")
    if failed:
        sys.exit(f"No games returned for: {', '.join(failed)} - not publishing.")


if __name__ == "__main__":
    main()
