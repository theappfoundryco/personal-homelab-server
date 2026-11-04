"""F1 and cricket: the next race, standings, and live India matches."""
import re
import xml.etree.ElementTree as ET
from datetime import datetime

from core import host
from core.helpers import cached, esc, http, now, safe

# ================================================================ sports
def jolpica(path):
    return http(f"https://api.jolpi.ca/ergast/f1/current/{path}.json", timeout=15)["MRData"]


def f1_when(s):
    return datetime.fromisoformat(f"{s['date']}T{s.get('time', '00:00:00Z').replace('Z', '+00:00')}").astimezone(TZ)


def f1_lines():
    nxt = jolpica("next")["RaceTable"]["Races"]
    last = jolpica("last/results")["RaceTable"]["Races"]
    st = jolpica("driverStandings")["StandingsTable"]["StandingsLists"]
    out = ["🏎 <b>Formula 1</b>"]
    if nxt:
        r = nxt[0]
        t = f1_when(r)
        out.append(f"Next: <b>{esc(r['raceName'])}</b>, {nice_when(t)} (your time)")
        for k, label in [("Sprint", "Sprint"), ("Qualifying", "Qualifying")]:
            if k in r:
                out.append(f"   {label} {nice_when(f1_when(r[k]))}")
    if last:
        res = last[0]["Results"][:3]
        out.append(f"Last race: {esc(last[0]['raceName'])} 🥇 {res[0]['Driver']['familyName']} 🥈 {res[1]['Driver']['familyName']} 🥉 {res[2]['Driver']['familyName']}")
    if st:
        out.append("Standings: " + ", ".join(f"{s['position']}. {s['Driver']['familyName']} {s['points']}" for s in st[0]["DriverStandings"][:5]))
    return out


@cached(120)
def cricket_items():
    root = ET.fromstring(http("https://static.cricinfo.com/rss/livescores.xml", raw=True, timeout=15))
    return [{"title": re.sub(r"\s+", " ", i.findtext("title") or "").strip(), "link": (i.findtext("guid") or i.findtext("link") or "").strip()}
            for i in root.iter("item")]


INDIA = re.compile(r"\bIndia\b")


def cricket_lines():
    items = safe(cricket_items, [])
    india = [i for i in items if INDIA.search(i["title"])]
    out = ["🏏 <b>Cricket</b>"]
    if india:
        out += [f"• {esc(i['title'])}" + (" 🔴 live" if "*" in i["title"] else "") for i in india[:4]]
    else:
        out.append("No India match on right now.")
    return out


def sports():
    typing()
    lines = safe(f1_lines, ["🏎 F1 data isn't available right now."]) + [""] + cricket_lines()
    send("\n".join(lines), [[U("🏁 F1 news", "https://www.formula1.com/en/latest"), U("🏏 Cricinfo", "https://www.espncricinfo.com/live-cricket-score")]])


def register(app):
    host.need(globals(), "TZ", "U", "nice_when", "send", "typing")
