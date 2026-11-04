"""Quiet alerts: server problems, F1 and flight changes. Recorded for the morning recap, not pushed at you."""
import json
import re
import time
from datetime import timedelta

from core import host
from core.helpers import cached, esc, http, now, safe

# ================================================================ alerts (quiet: recorded for the 7:00 recap)
down_count = {}


def incident(text):
    with _lock:
        cut = time.time() - 2 * 86400
        state["incidents"] = [i for i in state.get("incidents", []) if i["t"] > cut][-50:] + [{"t": time.time(), "text": text}]
        save()


def check_server():
    try:
        cs = containers()
    except Exception:
        return
    for n in ALWAYS_ON:
        if n not in cs:
            continue
        if cs[n] != "running":
            down_count[n] = down_count.get(n, 0) + 1
            if down_count[n] == 3:  # stopped for ~3 minutes (the watchdog usually fixes it before this)
                incident(f"{app_name(n)} stopped for a while")
        else:
            down_count[n] = 0
    t = one(f"avg_over_time({TEMP}[10m])")
    if t and t > 92 and once(f"hot:{now():%Y%m%d%H}"):
        send(f"🌡 The server has been running hot ({t:.0f}°C) for 10 minutes. Check that its vents aren't blocked.")
    disk = one('(1 - node_filesystem_avail_bytes{mountpoint="/"} / node_filesystem_size_bytes{mountpoint="/"}) * 100')
    if disk and disk > 85 and once(f"disk:{now():%Y%m%d}"):
        send(f"💾 Storage is {disk:.0f}% full. Time to clean up.")
    ssd = (daily() or {}).get("ssd") or {}
    if ssd.get("issues") and once(f"ssd:{now():%Y%m%d}"):
        send("🩺 <b>SSD health warning</b>\n" + "\n".join(f"• {esc(i)}" for i in ssd["issues"]) + "\nMake sure backups are working.")


def updates_message(report):
    """Watchtower's nightly report (one 'updated|name|image' or 'failed|name|image|error' line per app)."""
    ok, bad = [], []
    for line in report.splitlines():
        f = line.strip().split("|")
        if len(f) < 3 or f[0] not in ("updated", "failed"):
            continue
        name, tag = f[1].lstrip("/"), f[2].rsplit(":", 1)[-1] if ":" in f[2].rsplit("/", 1)[-1] else "latest"
        friendly = re.sub(r"\s*\(.*\)", "", app_name(name))
        (ok if f[0] == "updated" else bad).append((friendly, name, tag, f[3] if len(f) > 3 else ""))
    if not ok and not bad:
        return None
    n = len(ok)
    out = [f"⬆️ <b>{n} app{'s' if n != 1 else ''} updated</b>" if n else "⚠️ <b>Some updates failed</b>",
           f"<i>{now():%A %d %b, %-I:%M %p}</i>"]
    if ok:
        out += [""] + [f"✅ <b>{esc(f)}</b>" + (f"  <i>{esc(c)}</i>" if f.lower() != c else "") for f, c, _, _ in ok]
    if bad:
        out += ["", "⚠️ <b>Couldn't update</b>"] + [f"• {esc(f)}: <i>{esc(e[:120]) or 'unknown error'}</i>" for f, _, _, e in bad]
    out += ["", "Everything restarted on its own. Nothing to do." if not bad else "The old versions are still running."]
    return "\n".join(out)


def check_f1():
    try:
        r = jolpica("next")["RaceTable"]["Races"]
    except Exception:
        return
    if not r:
        return
    race = r[0]
    sessions = [("Qualifying", race.get("Qualifying")), ("Sprint", race.get("Sprint")), ("Race", race)]
    for label, s in sessions:
        if not s:
            continue
        t = f1_when(s)
        mins = (t - now()).total_seconds() / 60
        if 0 < mins <= 65 and once(f"f1:{race['round']}:{label}"):
            send(f"🏎 <b>{esc(race['raceName'])}</b>\n{label} starts at <b>{t:%-I:%M %p}</b> (in about {round(mins)} minutes)",
                 [[U("F1 live", "https://www.formula1.com/en/timing/f1-live")]])
    # Results: after the last race finished (checked for 2 days)
    try:
        last = jolpica("last/results")["RaceTable"]["Races"][0]
        if (now() - f1_when(last)).days < 2 and once(f"f1res:{last['season']}:{last['round']}"):
            res = last["Results"][:3]
            send(f"🏁 <b>{esc(last['raceName'])} result</b>\n🥇 {res[0]['Driver']['givenName']} {res[0]['Driver']['familyName']} ({res[0]['Constructor']['name']})\n"
                 f"🥈 {res[1]['Driver']['familyName']}  🥉 {res[2]['Driver']['familyName']}")
    except Exception:
        pass


cricket_seen = {}


def check_cricket():
    items = safe(cricket_items, None)
    if items is None:
        return
    india = {i["link"]: i for i in items if INDIA.search(i["title"])}
    for link, i in india.items():
        if not re.search(r"\d+/\d+|\d+ ?\(", i["title"]):
            continue  # not started yet
        prev = cricket_seen.get(link)
        if prev is None:
            if once(f"cric:{link}"):
                send(f"🏏 <b>India match is on</b>\n{esc(i['title'])}", [[U("Live score", i["link"])]])
            cricket_seen[link] = {"sent": i["title"], "last": i["title"], "t": time.time()}
        else:
            prev["last"] = i["title"]
            if i["title"] != prev["sent"] and time.time() - prev["t"] > 3600:  # hourly score update
                send(f"🏏 {esc(i['title'])}", [[U("Live score", i["link"])]], silent=True)
                prev.update(sent=i["title"], t=time.time())
    for link in list(cricket_seen):
        if link not in india:
            if once(f"cricend:{link}"):
                send(f"🏁 <b>India match finished</b>\nLast score: {esc(cricket_seen[link]['last'])}", [[U("Result", link)]])
            del cricket_seen[link]


def check_flights():
    for f in flights(2):
        key = f"{f['start']:%Y%m%d%H%M}"
        if timedelta(0) <= now() - f["checkin"] < timedelta(minutes=30) and once(f"checkin:{key}"):
            send(f"🛫 <b>Check-in is open</b> for {esc(f['title'])} ({nice_when(f['start'])}).\nCheck in online now to pick a good seat.")
        if timedelta(0) <= f["leave_by"] - now() <= timedelta(minutes=45) and once(f"leave:{key}"):
            send(f"🚕 <b>Time to get ready!</b>\nLeave for the airport by <b>{f['leave_by']:%-I:%M %p}</b>. Your flight departs at {f['start']:%-I:%M %p}.\n"
                 "Passport ✓ Phone & charger ✓ Wallet ✓")


def _routes(router):
    """Watchtower and Grafana post here, from other containers only (never via the home page proxy)."""
    def inbound(req):
        if req.headers.get("X-Forwarded-For") or req.headers.get("X-Real-IP"):
            return None
        return req._h.rfile.read(int(req.headers.get("Content-Length") or 0)).decode("utf-8", "replace")

    @router.post("/watchtower")
    def watchtower(req):
        raw = inbound(req)
        if raw is None:
            return {"ok": False}, 403
        if m := updates_message(raw):
            safe(lambda: send(m, [[B("\U0001F5A5 Server status", "server")]], silent=True))
        return {"ok": True}

    @router.post("/alert")
    def grafana(req):  # noted for the morning recap, not sent
        raw = inbound(req)
        if raw is None:
            return {"ok": False}, 403
        for a in (safe(lambda: json.loads(raw), {}) or {}).get("alerts", []):
            if a.get("status") == "firing":
                incident((a.get("annotations") or {}).get("summary") or (a.get("labels") or {}).get("alertname", "Server alert"))
        return {"ok": True}


def register(app):
    host.need(globals(), "ALWAYS_ON", "B", "INDIA", "TEMP", "U", "_lock", "app_name", "containers", "cricket_items", "daily", "f1_when", "flights", "jolpica", "nice_when", "once", "one", "save", "send", "state")
    _routes(app.router)
