"""Reads your calendar (a secret iCal link) so the bot knows what is on today and tomorrow."""
import os, re
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from core import host
from core.helpers import cached, esc, http, now, safe

# ================================================================ calendar (secret iCal feed)
@cached(300)
def ics_text():
    return http(open(ICS_FILE).read().strip(), raw=True, timeout=20)


def parse_dt(line):
    head, val = line.split(":", 1)
    val = val.strip()
    if re.fullmatch(r"\d{8}", val):
        return datetime.strptime(val, "%Y%m%d").replace(tzinfo=TZ), True
    if val.endswith("Z"):
        return datetime.strptime(val[:15], "%Y%m%dT%H%M%S").replace(tzinfo=timezone.utc).astimezone(TZ), False
    m = re.search(r"TZID=([^;:]+)", head)
    zone = safe(lambda: ZoneInfo(m[1]), TZ) if m else TZ
    return datetime.strptime(val[:15], "%Y%m%dT%H%M%S").replace(tzinfo=zone).astimezone(TZ), False


DAYS = ["MO", "TU", "WE", "TH", "FR", "SA", "SU"]


def occurs_on(day, start, all_day, end, rrule, exdates):
    if day in exdates:
        return False
    s0 = start.date()
    if not rrule:  # single event; multi-day events cover every day until DTEND
        e0 = (end.date() if all_day else end.date() + timedelta(1)) if end else s0 + timedelta(1)
        return s0 <= day < (e0 if e0 > s0 else s0 + timedelta(1))
    if s0 > day:
        return False
    r = dict(p.split("=", 1) for p in rrule.split(";") if "=" in p)
    if "UNTIL" in r and parse_dt("X:" + r["UNTIL"])[0].date() < day:
        return False
    n, f = int(r.get("INTERVAL", 1)), r.get("FREQ")
    if f == "DAILY":
        return (day - s0).days % n == 0
    if f == "WEEKLY":
        weeks = (day - (s0 - timedelta(s0.weekday()))).days // 7
        return weeks % n == 0 and DAYS[day.weekday()] in r.get("BYDAY", DAYS[s0.weekday()]).split(",")
    if f == "MONTHLY":
        return s0.day == day.day and ((day.year - s0.year) * 12 + day.month - s0.month) % n == 0
    if f == "YEARLY":
        return (s0.month, s0.day) == (day.month, day.day)
    return False


@cached(120)
def events_for(days):
    """{date: [event]} for a tuple of dates. Event: all_day, start (datetime|None), when, title, loc."""
    raw = re.sub(r"\r?\n[ \t]", "", ics_text())
    unesc = lambda v: v.replace("\\,", ",").replace("\\;", ";").replace("\\n", " ").replace("\\N", " ").strip()
    blocks = []
    for b in raw.split("BEGIN:VEVENT")[1:]:
        lines = [l.rstrip("\r") for l in b.split("\n")]
        blocks.append((lines, lambda k, L=lines: next((l for l in L if l.startswith(k + ":") or l.startswith(k + ";")), None)))
    moved = {}
    for lines, get in blocks:
        if get("RECURRENCE-ID") and get("UID"):
            moved.setdefault(get("UID"), set()).add(parse_dt(get("RECURRENCE-ID"))[0].date())
    found, seen = {d: [] for d in days}, set()
    for lines, get in blocks:
        dt = get("DTSTART")
        if not dt or (get("STATUS") or "").endswith("CANCELLED"):
            continue
        start, all_day = parse_dt(dt)
        end = parse_dt(get("DTEND"))[0] if get("DTEND") else None
        rrule = "" if get("RECURRENCE-ID") else re.sub(r"^RRULE:", "", get("RRULE") or "")
        ex = {parse_dt(l.split(":", 1)[0] + ":" + x)[0].date() for l in lines if l.startswith("EXDATE")
              for x in l.split(":", 1)[1].split(",")}
        if rrule:
            ex |= moved.get(get("UID"), set())
        title = unesc(re.sub(r"^SUMMARY[^:]*:", "", get("SUMMARY") or "")) or "(no title)"
        loc = unesc(re.sub(r"^LOCATION[^:]*:", "", get("LOCATION") or ""))
        loc = "online" if loc.startswith("http") else loc.split(",")[0][:40]
        length = (end - start) if end and not all_day else None
        for d in days:
            if not occurs_on(d, start, all_day, end, rrule, ex):
                continue
            st = None if all_day else datetime.combine(d, start.time(), TZ)
            when = "All day" if all_day else t12_range(st, st + length if length else None)
            flight = bool(st and FLIGHT.search(title))
            if (d, when, title) in seen or (flight and (d, when, "flight") in seen):
                continue  # same event twice, or the same flight added by hand and by Gmail
            seen.add((d, when, title))
            if flight:
                seen.add((d, when, "flight"))
            found[d].append({"all_day": all_day, "start": st, "end": st + length if st and length else None,
                             "when": when, "title": title, "loc": loc})
    for d in days:
        found[d].sort(key=lambda e: (not e["all_day"], e["start"] or datetime.min.replace(tzinfo=TZ)))
    return found


def has_calendar():
    return os.path.exists(ICS_FILE)


def day_events(d):
    if not has_calendar():
        return []
    return safe(lambda: events_for((d,))[d], [])


def event_line(e, rich=True):
    loc = f" ({e['loc']})" if e["loc"] else ""
    return f"• {e['when']}  {esc(e['title'])}" + (f"<i>{esc(loc)}</i>" if rich else esc(loc))


def register(app):
    host.need(globals(), "FLIGHT", "ICS_FILE", "TZ", "t12_range")
