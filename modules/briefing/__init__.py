"""The morning briefing and the morning news digest, built from every module that is on."""
import html
import re
import threading
import time
from datetime import datetime, timedelta

from core import host
from core.helpers import cached, esc, http, now, safe

host.need(globals(), "NAME", "cfg")

# ================================================================ briefing & news
KINDS = {
    "brief": {"name": "briefing", "hook": "briefing", "at": 7 * 60, "match": lambda m: (m.get("title") or "").startswith("Good ")},
    "news": {"name": "news", "hook": "news", "at": 7 * 60 + 5, "match": lambda m: "newspaper" in (m.get("tags") or [])},
}


def heading(line):
    m = re.match(r"^(\S+)\s+(.+)$", line)
    if not m or re.search(r"[\x00-\x7F•]", m[1]):
        return None
    title, *rest = re.split(r" [·•] ", m[2])
    bare = re.sub(r"\([^)]*\)", "", title).strip()
    if not re.fullmatch(r"[A-Z0-9 &'/-]+", bare) or len(re.findall(r"[A-Z]", bare)) < 2:
        return None
    return m[1], title, rest


def to_html(m):
    out = [f"<b>{esc(m.get('title') or '')}</b>"]
    for line in (m.get("message") or "").split("\n"):
        h = heading(line.strip()) if line.strip() else None
        if h:
            icon, title, rest = h
            bare = re.sub(r"\s*\([^)]*\)", "", title).strip()
            paren = (re.search(r"\(([^)]*)\)", title) or [None, None])[1]
            name = bare.title() if len(bare) > 3 else bare  # "WEBSITES (24h)" -> "Websites" + "24h"
            sub = " • ".join([x for x in [paren, *rest] if x])
            out.append(f"\n{icon} <b>{esc(name)}</b>" + (f"  <i>{esc(sub)}</i>" if sub else ""))
        elif line.strip():
            out.append(esc(line))
    return "\n".join(out)


def stamp(t):
    d = datetime.fromtimestamp(t, TZ)
    day = "today" if d.date() == now().date() else "yesterday" if d.date() == now().date() - timedelta(1) else f"{d:%a %d %b}"
    return f"{day} at {d:%-I:%M %p}"


def menu(kind):
    k = KINDS[kind]
    rows = [[B(f"🌅 This morning's", f"stored:{kind}"), B("✨ Make a new one", f"fresh:{kind}")]]
    if kind == "news":
        rows += [[B("🏎 F1", "topic:f1"), B("🏏 Cricket", "topic:cricket"), B("💻 Tech", "topic:tech")],
                 [B("🇮🇳 India", "topic:india"), B("🌍 World", "topic:world"), B("📈 Markets", "topic:business")]]
    send(f"{'☀️' if kind == 'brief' else '🗞'} Which {k['name']} would you like?" + ("\n<i>Or just type a topic, like “news about Tesla”.</i>" if kind == "news" else ""), rows)


def stored(kind):
    if kind != "brief":
        return live_digest()
    m = state.get("last_brief")
    if not m or time.time() - m["time"] > 2 * 86400:
        return send("I couldn't find a briefing from the last two days.", [[B("✨ Make a new one", "fresh:brief")]])
    send(f"<i>Sent {stamp(m['time'])}</i>\n\n" + m["html"], [[B("✨ Fresh one now", "full")]])


LAST_BRIEF = {}
LOC_EVENT = re.compile(rf"^(?:{NAME}\s+)?(?:is\s+)?in\s+[A-Za-z .'-]+", re.I)
# The news sections in the brief are yours to pick (news.topics, set on the News page in Settings). Your own feeds are sections too.
TOPIC_HEAD = {"world": ("🌍", "WORLD"), "tech": ("💻", "TECH"), "science": ("🔬", "SCIENCE"), "business": ("📈", "BUSINESS & MARKETS"), "sports": ("🏆", "SPORT"),
              "launches": ("🚀", "NEW APPS & TECH"), "mna": ("🤝", "M&As"), "f1": ("🏎", "FORMULA 1"), "cricket": ("🏏", "CRICKET"), "india": ("🇮🇳", "INDIA")}
NEWS_DEFAULT = ["world", "tech", "science", "business"]
BRIEF_NEWS = [(k, *TOPIC_HEAD.get(k, ("📰", k.upper()))) for k in (cfg("news.topics", None) or NEWS_DEFAULT)]
BRIEF_PER = 5  # stories per news section in the brief


def server_recap():
    """The last 24 hours of the server in a few lines, for the 7:00 briefing (replaces live up/down alerts)."""
    d, rows = daily() or {}, []
    for x in sorted(d.get("sites") or [], key=lambda x: x["uptime"]):
        mins = round((100 - x["uptime"]) * 14.4)
        if not x["up_now"]:
            rows.append(f"• 🔴 {esc(x['name'])} is down right now")
        elif mins >= 1:
            rows.append(f"• {esc(x['name'])}: down {mins} min in total")
    with _lock:
        cut = time.time() - 86400
        inc = [i for i in state.get("incidents", []) if i["t"] > cut]
    stopped = sorted({i["text"] for i in inc})
    rows += [f"• {esc(t)}" for t in stopped[:4]]
    if (d.get("ssd") or {}).get("issues"):
        rows.append("• 🩺 SSD health warning, check backups")
    return rows or ["All websites and apps ran fine 👌"]


def backup_line():
    """One line for the 7:00 briefing: last successful backup, and the last failed one if there was any."""
    b = (daily() or {}).get("backups") or {}
    when = lambda x: (lambda t: f"{'today' if t.date() == now().date() else 'yesterday' if (now().date() - t.date()).days == 1 else f'{t:%a %d %b}'}, {t12(t)}")(
        datetime.fromtimestamp(x["at"], TZ)) + f" ({x['where']})"
    ok = b.get("ok")
    if ok and time.time() - ok["at"] < 3 * 86400:
        line = f"Last successful backup: {when(ok)}"
    else:
        line = "⚠️ No successful backup in 3 days" + (f" (last: {when(ok)})" if ok else "")
    f = b.get("fail")
    # a failure shows once (the brief after it), and keeps showing only while that backup is still failing
    if f and (time.time() - f["at"] < 86400 or f["at"] > (b.get("ok_by") or {}).get(f["where"], 0)):
        line += f" • last failed: {when(f)}"
    return line


def build_briefing(recap=False):
    """Personal briefing: weather, day, travel, reminders, notes, money, World / India / F1 news, and (at 7:00) a server recap.
    Everything is fetched in parallel and mostly cached, so it takes a second or two.
    Returns (title, html, plain text for the phone notification)."""
    loc, t = location(), now()
    greet = "Good morning" if 5 <= t.hour < 12 else "Good afternoon" if 12 <= t.hour < 17 else "Good evening"
    got = {}
    jobs = {"wx": lambda: weather_lines(loc), "fx": lambda: travel_fx(loc),
            "next": lambda: next((l for l in f1_lines() if l.startswith("Next:")), None),
            **{k: (lambda k=k: headlines_for(k, 10)) for k, _, _ in BRIEF_NEWS}}
    threads = [threading.Thread(target=lambda k=k, f=f: got.__setitem__(k, safe(f))) for k, f in jobs.items()]
    [x.start() for x in threads]; [x.join(12) for x in threads]

    sections = []  # (icon, TITLE, sub, [(html, plain)])
    if got.get("wx"):
        sections.append(("🌦", "WEATHER", loc["city"], [(l, strip_tags(l)) for l in got["wx"]]))
    if has_calendar():
        ev = [e for e in day_events(t.date()) if not (e["all_day"] and LOC_EVENT.match(e["title"]))]  # "{name} in X" markers
        sections.append(("📅", "TODAY", f"{t:%a %d %b}", [(event_line(e), strip_tags(event_line(e, False))) for e in ev]
                         or [("Nothing scheduled. Free day 🎉",) * 2]))
    fl = [f for f in flights(1) if f["start"] > t]  # not the ones already gone
    if fl:
        sections.append(("✈️", "TRAVEL", "", [(flight_text(f), strip_tags(flight_text(f))) for f in fl]))
    rs = sorted((r for r in state["reminders"] if datetime.fromtimestamp(r["due"], TZ).date() == t.date()), key=lambda r: r["due"])
    if rs:
        sections.append(("⏰", "REMINDERS", "today", [(f"• {datetime.fromtimestamp(r['due'], TZ):%-I:%M %p} {esc(r['text'])}",
                                                      f"• {datetime.fromtimestamp(r['due'], TZ):%-I:%M %p} {r['text']}") for r in rs]))
    if state["notes"]:
        sections.append(("📝", "NOTES", "", [(f"• {esc(n['text'])}", f"• {n['text']}") for n in state["notes"][:5]]))
    if got.get("fx"):
        line = " • ".join(f"1 {c} = ₹{r:.2f}" for c, r in got["fx"])
        sections.append(("💱", "MONEY", "", [(line, line)]))
    for k, icon, name in BRIEF_NEWS:
        items = got.get(k) or []
        last_headlines[k] = items
        rows = news_rows(k, items, BRIEF_PER)
        if k == "f1" and got.get("next"):
            rows.insert(0, (got["next"], strip_tags(got["next"])))
        if rows:
            sections.append((icon, name, "", rows))
    if recap:
        line = backup_line()
        sections.append(("💾", "BACKUPS", "", [(esc(line), line)]))
    gs = [g for g in state.get("goals", []) if not g.get("achieved")]
    if gs:  # his life goals close the briefing
        sections.append(("🎯", "GOALS", "", [(f"• {esc(g['text'])}", f"• {g['text']}") for g in gs]))

    title = f"{greet}, {NAME}"
    head = f"📍 {loc['city']} • {t:%A %d %B, %-I:%M %p}"
    LAST_BRIEF.update(title=title, city=loc["city"], at=time.time(),
                      sections=[{"icon": i, "name": n.title() if len(n) > 3 else n, "sub": sb, "rows": [h for h, _ in r]} for i, n, sb, r in sections])
    body_html = [f"☀️ <b>{title}</b>", f"<i>{esc(head)}</i>"]
    body_txt = [head]
    for icon, name, sub, rows in sections:
        nice = name.title() if len(name) > 3 else name
        body_html += ["", f"{icon} <b>{nice}</b>" + (f"  <i>{esc(sub)}</i>" if sub else "")] + [h for h, _ in rows]
        body_txt += ["", f"{icon} {name}" + (f" • {sub}" if sub else "")] + [html.unescape(x) for _, x in rows]
    return title, "\n".join(body_html), "\n".join(body_txt)


def warm_briefing():
    """Keeps the briefing's sources in the cache so asking for it is instant."""
    loc = location()
    jobs = [lambda: weather_data(loc["lat"], loc["lon"]), f1_lines] + [lambda u=u: feed_items(u) for k, _, _ in BRIEF_NEWS for _, u in FEEDS.get(k, [])]
    for f in jobs:
        threading.Thread(target=lambda f=f: safe(f), daemon=True).start()


def full_briefing():
    """What 'brief me' means: a fresh briefing with World, India and F1 news. Takes a second or two."""
    typing()
    _, html_text, _ = build_briefing()
    send(html_text, [[B("🗞 More news", "news"), B("🌙 Tomorrow", "evening")]])


def scheduled_briefing(late=False):
    _, html_text, _ = build_briefing(recap=True)
    if late:
        html_text = "⚡ <i>Sent late: the server was down at 7 AM.</i>\n\n" + html_text
    send(html_text, [[B("🗞 More news", "news"), B("🌙 Tomorrow", "evening")]], silent=True)
    with _lock:
        state["last_brief"] = {"time": time.time(), "html": html_text}
        save()


def morning_briefing():
    """This morning's 7:00 briefing, as it was sent."""
    stored("brief")


def _routes(router):
    @router.get("/brief/run")
    def brief_run(req):
        threading.Thread(target=lambda: safe(full_briefing), daemon=True).start()
        return {"ok": True}

    @router.get("/brief")
    def brief(req):
        build_briefing()
        return LAST_BRIEF


def register(app):
    host.need(globals(), "B", "FEEDS", "TZ", "_lock", "daily", "day_events", "event_line", "f1_lines", "feed_items", "flight_text", "flights", "has_calendar", "headlines_for", "last_headlines", "live_digest", "location", "news_rows", "save", "send", "state", "strip_tags", "t12", "travel_fx", "typing", "weather_data", "weather_lines")
    _routes(app.router)
