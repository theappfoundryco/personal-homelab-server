"""Medicines: when each one is due, checking what someone typed into the form, and turning the old morning, lunch and night
slots and weekly courses into medicines. Plain functions over plain data, so tests need no clock, no Telegram and no files.

A medicine: {"id", "name", "dose", "every": day | week | 2weeks | month, "times": ["08:00", ...] (24-hour, as stored),
"weekday": 0-6 (Monday is 0, for every week), "monthday": 1-28 (for every month), "start": "YYYY-MM-DD", "stop_after": n or None, "remind": bool}.
One dose is a medicine at one of its times on one day. It is ticked in the log as "<id>@<HHMM>", so a medicine taken twice a day has two ticks."""
import re
from datetime import date, datetime, timedelta

EVERY = ("day", "week", "2weeks", "month")
MAX_TIMES = 6
OLD_TIMES = {"morning": "09:30", "lunch": "14:00", "night": "21:00"}  # when the old fixed slots nudged
TIME = re.compile(r"([01]\d|2[0-3]):[0-5]\d")
DAY = re.compile(r"\d{4}-\d{2}-\d{2}")


def key(mid, t):
    return f"{mid}@{t.replace(':', '')}"


def split_key(k):
    """'m1@0800' as ('m1', '08:00'). A key with no time (an old slot or course id) gives ('m1', '')."""
    mid, _, t = str(k).partition("@")
    return mid, f"{t[:2]}:{t[2:]}" if re.fullmatch(r"\d{4}", t) else ""


def dose_no(m, d):
    """Which dose of medicine m falls on day d (1 is the first), or 0 when none is due that day or it has stopped."""
    start = date.fromisoformat(m["start"])
    if d < start:
        return 0
    e = m["every"]
    if e == "day":
        n = (d - start).days + 1
    elif e == "week":
        if d.weekday() != m["weekday"]:
            return 0
        first = start + timedelta(days=(m["weekday"] - start.weekday()) % 7)
        n = (d - first).days // 7 + 1
    elif e == "2weeks":
        if (d - start).days % 14:
            return 0
        n = (d - start).days // 14 + 1
    elif e == "month":
        if d.day != m["monthday"]:
            return 0
        fy, fm = (start.year, start.month) if start.day <= m["monthday"] else (start.year + start.month // 12, start.month % 12 + 1)
        n = (d.year * 12 + d.month) - (fy * 12 + fm) + 1
    else:
        return 0
    return 0 if m.get("stop_after") and n > m["stop_after"] else n


def next_due(m, d, horizon=400):
    """The first day on or after d with a dose of m, or None when it has finished (or nothing falls within the horizon)."""
    for i in range(horizon):
        x = d + timedelta(days=i)
        if dose_no(m, x):
            return x
    return None


def doses_on(meds, d):
    """Every dose due on day d, earliest first: [(medicine, time, dose number)]."""
    out = [(m, t, n) for m in meds for t in m["times"] if (n := dose_no(m, d))]
    return sorted(out, key=lambda x: (early(x[1]), x[0]["name"].lower()))


def early(t):
    """Sort key for a time in the meds day, which turns over at 4 AM: 1:00 AM comes after 11:00 PM."""
    h = int(t[:2])
    return (h + 24 if h < 4 else h) * 60 + int(t[3:])


def at(d, t, tz=None):
    """When a dose at time t on meds day d happens. A time before 4 AM is after midnight, so it is the next calendar day."""
    x = datetime.combine(d, datetime.strptime(t, "%H:%M").time(), tz)
    return x + timedelta(days=1) if int(t[:2]) < 4 else x


def clean(b, today):
    """A medicine from the form, or (None, what to fix) in plain words."""
    name = str(b.get("name") or "").strip()[:60]
    if not name:
        return None, "Give it a name."
    every = b.get("every")
    if every not in EVERY:
        return None, "Choose how often."
    times = []
    for t in b.get("times") or []:
        if TIME.fullmatch(str(t)) and t not in times:
            times.append(t)
    if not times:
        return None, "Add a time."
    times = sorted(times, key=early)[:MAX_TIMES if every == "day" else 1]
    m = {"id": str(b.get("id") or ""), "name": name, "dose": str(b.get("dose") or "").strip()[:60], "every": every, "times": times,
         "start": str(b.get("start") or "") if DAY.fullmatch(str(b.get("start") or "")) else today.isoformat(), "remind": bool(b.get("remind"))}
    if every == "week":
        if b.get("weekday") not in range(7):
            return None, "Choose the day of the week."
        m["weekday"] = b["weekday"]
    if every == "month":
        if b.get("monthday") not in range(1, 29):
            return None, "Choose a date from 1 to 28 (every month has those)."
        m["monthday"] = b["monthday"]
    stop = b.get("stop_after")
    if stop not in (None, "", 0):
        if not isinstance(stop, int) or not 1 <= stop <= 999:
            return None, "Stop after must be a number from 1 to 999."
        m["stop_after"] = stop
    return m, None


def parse_when(s):
    """'8:00 AM' or '8 PM' as '08:00' or '20:00'. None when it isn't a time."""
    x = re.fullmatch(r"\s*(\d{1,2})(?::(\d{2}))?\s*([ap])\.?m\.?\s*", str(s or ""), re.I)
    if not x or not 1 <= int(x.group(1)) <= 12:
        return None
    h = int(x.group(1)) % 12 + (12 if x.group(3).lower() == "p" else 0)
    return f"{h:02d}:{x.group(2) or '00'}"


def convert_old(sg, today):
    """The old shape (fixed slots and weekly courses) as medicines, with their ticks moved to the new keys. Safe to run twice."""
    if "meds" in sg and not sg.get("slots") and not sg.get("courses"):
        return False
    log, meds = sg.setdefault("log", {}), list(sg.get("meds") or [])
    first = min([d for d in log if DAY.fullmatch(d)] or [today.isoformat()])

    def move(old, new):
        for day in log.values():
            if isinstance(day, dict) and old in day:
                v = day.pop(old)
                if v:
                    day[new] = True

    for sl in sg.get("slots") or []:
        t = parse_when(sl.get("when")) or OLD_TIMES.get(sl.get("id"), "09:00")
        items = [str(i) for i in sl.get("items") or [] if str(i).strip()]
        meds.append({"id": sl["id"], "name": ", ".join(items) or sl.get("label") or "Medicine", "dose": "", "every": "day", "times": [t],
                     "start": first, "remind": sl.get("id") in OLD_TIMES})
        move(sl["id"], key(sl["id"], t))
    for c in sg.get("courses") or []:
        meds.append({"id": c["id"], "name": c.get("name") or "Weekly dose", "dose": "", "every": "week", "times": ["09:00"], "weekday": c.get("weekday", 0),
                     "start": c.get("start") or first, "stop_after": c.get("weeks") or None, "remind": True})
        move(c["id"], key(c["id"], "09:00"))
    sg["meds"] = meds
    sg.pop("slots", None)
    sg.pop("courses", None)
    return True
