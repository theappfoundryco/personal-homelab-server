"""What is on today and tomorrow, the evening plan with a suggested alarm, and the Sunday weekly report."""
import re
from datetime import datetime, timedelta

from core import host
from core.helpers import cached, esc, http, now, safe

# ================================================================ my day / evening plan / weekly report
def my_day():
    typing()
    today, tom = now().date(), now().date() + timedelta(1)
    loc = location()
    lines = [f"📅 <b>{now():%A %d %B}</b> • {esc(loc['city'])}"]
    w = safe(lambda: weather_lines(loc)[0])
    if w:
        lines.append(w)
    if has_calendar():
        ev = day_events(today)
        lines += ["", "<b>Today</b>"] + ([event_line(e) for e in ev] or ["Nothing scheduled. Free day 🎉"])
        ev2 = day_events(tom)
        lines += ["", f"<b>Tomorrow</b> • {tom:%a %d %b}"] + ([event_line(e) for e in ev2] or ["Nothing scheduled."])
    else:
        lines += ["", "Calendar isn't connected."]
    for f in flights(1):
        lines += ["", flight_text(f)]
    rs = [r for r in state["reminders"] if datetime.fromtimestamp(r["due"], TZ).date() in (today, tom)]
    if rs:
        lines += ["", "<b>Reminders</b>"] + [f"• {nice_when(datetime.fromtimestamp(r['due'], TZ))}: {esc(r['text'])}" for r in sorted(rs, key=lambda r: r["due"])]
    if state["notes"]:
        lines += ["", f"📝 {len(state['notes'])} open note(s)"]
    send("\n".join(lines), [[B("🌙 Plan for tomorrow", "evening"), B("📝 Notes", "notes")]])


def alarm_suggestion(ev, fl):
    if fl:
        return fl[0]["leave_by"] - timedelta(hours=1), f"so you're ready to leave for your {fl[0]['code'] or 'flight'} at {fl[0]['leave_by']:%-I:%M %p}"
    timed = [e for e in ev if e["start"]]
    if timed:
        first = timed[0]
        return first["start"] - timedelta(hours=1, minutes=30), f"for {first['title']} at {first['start']:%-I:%M %p}"
    return None, ""


def evening(scheduled=False):
    tom = now().date() + timedelta(1)
    ev = day_events(tom)
    fl = [f for f in flights(1) if f["start"].date() == tom]
    loc, wx = safe(tomorrow_weather, (location(tom), ""))
    lines = [f"🌙 <b>{'Good evening! ' if scheduled else ''}Here's tomorrow</b> • {tom:%A %d %b}"]
    if loc["city"] != location()["city"]:
        lines.append(f"📍 You'll be in {esc(loc['city'])}")
    if wx:
        lines.append(wx)
    lines += ["", "<b>Plans</b>"] + ([event_line(e) for e in ev] or ["Nothing scheduled. Enjoy a free day 🎉"])
    for f in fl:
        lines += ["", flight_text(f)]
    alarm, why = alarm_suggestion(ev, fl)
    lines += ["", f"⏰ Suggested alarm: <b>{alarm:%-I:%M %p}</b> {esc(why)}" if alarm else "😴 No early plans. Sleep in!"]
    rs = [r for r in state["reminders"] if datetime.fromtimestamp(r["due"], TZ).date() == tom]
    if rs:
        lines += ["", "<b>Reminders tomorrow</b>"] + [f"• {datetime.fromtimestamp(r['due'], TZ):%-I:%M %p} {esc(r['text'])}" for r in rs]
    if state["notes"]:
        lines += ["", "📝 <b>Still open</b>"] + [f"• {esc(n['text'])}" for n in state["notes"][:5]]
    buttons = [[B(f"⏰ Remind me at {alarm:%-I:%M %p}", f"alarm:{int(alarm.timestamp())}")]] if alarm else None
    send("\n".join(lines), buttons)


def weekly():
    typing()
    d = daily() or {}
    wk = d.get("week", {})
    up = one('avg_over_time(up{job="node"}[7d]) * 100')
    cpu = one('100 - avg(avg_over_time(rate(node_cpu_seconds_total{mode="idle"}[5m])[7d:15m])) * 100')
    tpk = one(f"max_over_time({TEMP}[7d:5m])")
    ev = wk.get("events", [])
    count = lambda pat: sum(1 for e in ev if re.search(pat, e["text"]))
    sites = wk.get("sites", [])
    lines = [f"📊 <b>Your week</b> • {now() - timedelta(days=6):%d %b} to {now():%d %b}", "",
             "<b>Server</b>",
             f"• Online {up or 0:.2f}% of the time • average load {cpu or 0:.1f}% • hottest {tpk or 0:.0f}°C",
             f"• {count('rebooted')} restart(s) • {count('^Updated')} update round(s) • {count('Backup saved')} of 7 backups saved"]
    issues = [e for e in ev if re.search(r"DOWN|FAILED|failed|unexpected|dropped", e["text"])]
    if issues:
        lines += ["• Hiccups:"] + [f"   {esc(e['time'])} {esc(e['text'])}" for e in issues[-5:]]
    if sites:
        avg = sum(s["uptime"] for s in sites) / len(sites)
        worst = min(sites, key=lambda s: s["uptime"])
        lines += ["", "<b>Websites</b>", f"• {len(sites)} sites, {avg:.2f}% average uptime"]
        if worst["uptime"] < 100:
            lines.append(f"• Least reliable: {esc(worst['name'])} ({worst['uptime']}%)")
    if has_calendar():
        nxt = [now().date() + timedelta(i) for i in range(1, 8)]
        ev7 = safe(lambda: events_for(tuple(nxt)), {})
        lines += ["", "<b>Coming week</b>"]
        for day in nxt:
            items = [e for e in ev7.get(day, []) if not (e["all_day"] and re.match(rf"^{NAME} in ", e["title"], re.I))]
            if items:
                lines.append(f"• {day:%a %d}: " + "; ".join(esc(f"{e['when']} {e['title']}" if e["start"] else e["title"]) for e in items[:3])
                             + (f" +{len(items) - 3} more" if len(items) > 3 else ""))
        if lines[-1] == "<b>Coming week</b>":
            lines.append("Nothing scheduled yet.")
    lines += safe(journal_week_lines, [])
    send("\n".join(lines))


def register(app):
    host.need(globals(), "B", "NAME", "TEMP", "TZ", "daily", "day_events", "event_line", "events_for", "flight_text", "flights", "has_calendar", "journal_week_lines", "location", "nice_when", "one", "send", "state", "tomorrow_weather", "typing", "weather_lines")
