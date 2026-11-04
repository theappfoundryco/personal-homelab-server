"""Server status, app logs and restarts, and the server pages of the dashboard."""
import json
import os
import re
import threading
import time
import uuid
from urllib.parse import quote
from urllib.request import urlopen

from core import apps as _apps
from core import custom as _custom
from core import host
from core.helpers import cached, esc, http, now, safe
from core.version import VERSION

# ================================================================ server
def prom(q):
    return http(f"{PROM}/api/v1/query?query={quote(q)}", timeout=15)["data"]["result"]


def one(q):
    try:
        r = prom(q)
        return float(r[0]["value"][1]) if r else None
    except Exception:
        return None


def daily():
    try:
        d = json.load(open(DAILY))
        return d if time.time() - d["generated"] < 3600 else None
    except Exception:
        return None


def containers():
    """{name: state} for every container, via the read-only Docker proxy."""
    return {c["Names"][0].lstrip("/"): c["State"] for c in http(f"{DOCKER}/containers/json?all=1", timeout=10)}


TEMP = 'max(node_hwmon_temp_celsius{chip=~".*coretemp.*"})'


def problems():
    p = []
    try:
        cs = containers()
        p += [f"{app_name(n)} is stopped" for n in ALWAYS_ON if n in cs and cs[n] != "running"]
    except Exception:
        p.append("can't read app status")
    d = daily() or {}
    p += [f"website {s['name']} is down" for s in d.get("sites", []) if not s.get("up_now")]
    p += (d.get("ssd") or {}).get("issues", [])
    disk = one('(1 - node_filesystem_avail_bytes{mountpoint="/"} / node_filesystem_size_bytes{mountpoint="/"}) * 100')
    if disk and disk > 85:
        p.append(f"storage {disk:.0f}% full")
    return p


def server():
    typing()
    cpu = one('100 - avg(rate(node_cpu_seconds_total{mode="idle"}[1m])) * 100')
    if cpu is None:
        return send("😕 I can't reach the server's health data right now. It may be restarting; try again in a minute.")
    t, mem = one(TEMP) or 0, one("(1 - node_memory_MemAvailable_bytes / node_memory_MemTotal_bytes) * 100") or 0
    disk = one('(1 - node_filesystem_avail_bytes{mountpoint="/"} / node_filesystem_size_bytes{mountpoint="/"}) * 100') or 0
    up = one("time() - node_boot_time_seconds") or 0
    cs = safe(containers, {})
    running = sum(1 for n in ALWAYS_ON if cs.get(n) == "running")
    p = problems()
    d = daily() or {}
    sites = d.get("sites", [])
    head = "✅ <b>Everything is running smoothly</b>" if not p else "⚠️ <b>Needs attention</b>\n" + "\n".join(f"• {esc(x)}" for x in p)
    feel = "cool" if t < 60 else "warm" if t < 80 else "hot"
    lines = [head, "",
             f"🧠 Working at {cpu:.0f}% • memory {mem:.0f}% used",
             f"🌡 {t:.0f}°C ({feel}) • 💾 storage {disk:.0f}% used",
             f"📦 {running} of {len(ALWAYS_ON)} apps running • on for {up / 86400:.1f} days"]
    ai = safe(ai_status, {}) or {}
    q = next((m for m in ai.get("models", []) if m["role"] == "Quick model"), None)
    if ai.get("busy"):
        big = next((m for m in ai["models"] if m["state"] == "working"), None)
        size = f" ({big['gb']:.0f} GB)" if big else ""
        lines.append(f"🤖 AI: {esc(ai['busy'].lower())}{size}. Quick model paused, back when it's done.")
    elif q:
        held = q["gb"] + sum(m["gb"] for m in ai["models"] if m["role"] == "Understanding model")
        lines.append(f"🤖 AI: quick model ({q['params']}) {q['note'].lower()}" + (f", kept loaded ({held:.1f} GB)" if q["state"] == "ready" else ""))
    if sites:
        down = [s for s in sites if not s.get("up_now")]
        lines.append(f"🌐 {len(sites) - len(down)} of {len(sites)} websites online")
    ev = d.get("events", [])
    if ev:
        lines += ["", "<b>Last 24 hours</b>"] + [f"• {esc(e['time'])} {esc(e['text'])}" for e in ev[-5:]]
    send("\n".join(lines), [[B("🔄 Restart an app", "apps:restart"), B("📜 See logs", "apps:logs")],
                            [B("🧹 Free AI memory", "unload"), B("⏻ Restart server", "reboot?")],
                            [B("🔁 Refresh", "server"), *([U("📈 Charts", f"{DASH}:3000/d/homelab-command")] if DASH else [])]])


def app_buttons(action):
    names = sorted(n for n in ALWAYS_ON if n not in ("docker-proxy",))
    rows, row = [], []
    for n in names:
        row.append(B(app_name(n).split(" (")[0], f"{action}?:{n}" if action == "restart" else f"logs:{n}"))
        if len(row) == 2:
            rows.append(row); row = []
    if row:
        rows.append(row)
    return rows


def host_action(action, name=""):
    """Ask the host to do something; waits for its answer. With no host helper installed it answers at once instead of waiting a minute."""
    gone = CAPS.missing(["host_agent"])
    if gone:
        return {"ok": False, "msg": gone[0]}
    rid = uuid.uuid4().hex[:10]
    os.makedirs(f"{DATA}/requests", exist_ok=True)
    open(f"{DATA}/requests/{rid}", "w").write(f"{action} {name}".strip())
    for _ in range(60):
        time.sleep(1)
        res = f"{DATA}/results/{rid}.json"
        if os.path.exists(res):
            return json.load(open(res))
    return {"ok": False, "msg": "no answer from the server"}


def app_memory(names):
    """MB each running container uses right now, read in parallel (a Docker stats read takes a moment each). Missing ones are left out."""
    out = {}

    def one(n):
        try:
            m = http(f"{DOCKER}/containers/{n}/stats?stream=false&one-shot=true", timeout=8).get("memory_stats") or {}
            st = m.get("stats") or {}
            used = (m.get("usage") or 0) - (st.get("inactive_file") or st.get("total_inactive_file") or st.get("cache") or 0)
            if used > 0:
                out[n] = round(used / 1048576)
        except Exception:
            pass
    ts = [threading.Thread(target=one, args=(n,), daemon=True) for n in names]
    for t in ts:
        t.start()
    for t in ts:
        t.join(10)
    return out


def apps_log_tail():
    """The last line of a running app change (from the host helper's apps.log), or "" when none ran in the last ten minutes."""
    p = f"{DATA}/apps.log"
    try:
        if time.time() - os.path.getmtime(p) > 600:
            return ""
        lines = [l.strip() for l in open(p, errors="replace").read().replace("\r", "\n").splitlines() if l.strip()]
        return re.sub(r"\x1b\[[0-9;]*[A-Za-z]", "", lines[-1])[:160] if lines else ""
    except OSError:
        return ""


def catalog():
    """Every optional app with whether you chose it, its state and the memory it uses now, plus the core apps."""
    ids = _apps.chosen(DATA)
    try:
        cs = containers()
    except Exception:
        cs = None
    mem = app_memory([n for n, st in cs.items() if st == "running"]) if cs else {}
    out = []
    native = _apps.native(DATA)
    for a in _apps.view(ids):
        if a["id"] in native:  # runs on the machine itself: running when it answers
            a["state"], a["native"] = ("running" if safe(lambda: urlopen(_apps.NATIVE_URL + "/api/tags", timeout=2).status == 200, False) else "stopped"), True
            a["what"] += " Runs on this Mac, using its GPU."
        elif cs is None:
            a["state"] = None
        else:
            st = [cs.get(x, "missing") for x in a["services"]]
            a["state"] = "running" if all(x == "running" for x in st) else "missing" if all(x == "missing" for x in st) else "stopped"
        a["memory_now_mb"] = sum(mem.get(x, 0) for x in a["services"]) or None
        out.append(a)
    for a in _custom.view(DATA):
        a["state"] = None if cs is None else cs.get(a["id"], "missing")
        a["memory_now_mb"] = mem.get(a["id"])
        out.append(a)
    core = [{"id": n, "title": "Telegram assistant" if n == "telegram-bot" else app_name(n).split(" (")[0], "state": None if cs is None else cs.get(n, "missing"),
             "memory_now_mb": mem.get(n)} for n in _apps.CORE]
    reboot = safe(lambda: bool(json.load(open(f"{DATA}/agent.json")).get("reboot")), False)
    return {"apps": out, "core": core, "docker": cs is not None, "helper": not CAPS.missing(["host_agent"]), "reboot": reboot, "working": apps_log_tail()}


def restart_app(name, msg=None):
    m = edit(msg, f"🔄 Restarting {esc(app_name(name))}…") if msg else send(f"🔄 Restarting {esc(app_name(name))}…")
    r = host_action("restart", name)
    edit(m, f"✅ {esc(app_name(name))} has been restarted." if r.get("ok") else f"❌ Couldn't restart {esc(app_name(name))}: {esc(r.get('msg'))}")


def demux(b):
    """Docker log stream: 8-byte frame headers when the container has no TTY."""
    out, i = [], 0
    while i + 8 <= len(b) and b[i] in (0, 1, 2):
        n = int.from_bytes(b[i + 4:i + 8], "big")
        out.append(b[i + 8:i + 8 + n]); i += 8 + n
    return (b"".join(out) if out else b).decode("utf-8", "replace")


def logs(name):
    try:
        b = http(f"{DOCKER}/containers/{name}/logs?stdout=1&stderr=1&tail=25&timestamps=0", binary=True, timeout=15)
        text = re.sub(r"\x1b\[[0-9;]*m", "", demux(b)).strip()[-3300:]
        send(f"📜 <b>Latest from {esc(app_name(name))}</b>\n<pre>{esc(text) or '(empty)'}</pre>",
             [[B("🔄 Restart it", f"restart?:{name}"), B("🔁 Refresh", f"logs:{name}")]])
    except Exception as e:
        send(f"Couldn't read logs for {esc(name)} ({esc(e)}).")


def free_ai_memory():
    """Unloads every model the AI engine holds in memory. Returns a sentence saying how much was freed."""
    _ai["held"] = True  # the watchdog leaves them out until the AI is next used
    loaded = http(f"{OLLAMA}/api/ps", timeout=10).get("models", [])
    for m in loaded:
        http(f"{OLLAMA}/api/generate", {"model": m["name"], "keep_alive": 0}, timeout=30)
    freed = sum(m.get("size", 0) for m in loaded) / 1e9
    return f"Done. Freed {freed:.1f} GB of memory." if loaded else "The AI wasn't using any memory."


def unload_ai():
    try:
        send("🧹 " + free_ai_memory())
    except Exception as e:
        send(f"Couldn't reach the AI engine ({esc(e)}).")


def find_app(text):
    t = text.lower()
    for n in APPS:
        if n in t or n.replace("-", " ") in t:
            return n
    alias = {"ai chat": "open-webui", "webui": "open-webui", "kuma": "uptime-kuma", "uptime": "uptime-kuma", "ai": "ollama",
             "automation": "n8n", "chart": "grafana", "search": "searxng", "adblock": "adguard", "logs viewer": "dozzle",
             "home page": "landing", "dashboard": "homepage", "voice": "whisper"}
    return next((v for k, v in alias.items() if k in t), None)

REPO = "theappfoundryco/personal-homelab-server"
UPDATE_STALE = 1200  # an update that has not changed the version after this many seconds counts as failed


def vtuple(v):
    """'v0.2.10' as (0, 2, 10), so 0.2.10 is newer than 0.2.9. None when it is not a plain version."""
    m = re.fullmatch(r"v?(\d+)\.(\d+)\.(\d+)", str(v or "").strip())
    return tuple(int(x) for x in m.groups()) if m else None


@cached(600)
def latest_release():
    """The newest release tag (what `homelab update` follows on the stable channel; a pre-release such as v1.0.0-rc1 does not count), or None when it cannot be read."""
    try:
        tags = [t["name"] for t in http(f"https://api.github.com/repos/{REPO}/tags?per_page=100", timeout=8, headers={"Accept": "application/vnd.github+json"}) if vtuple(t.get("name"))]
        return {"tag": max(tags, key=vtuple), "url": f"https://github.com/{REPO}/releases/tag/{max(tags, key=vtuple)}", "notes": ""} if tags else None
    except Exception:
        return None


def update_log_tail(n=4):
    try:
        text = re.sub(r"\x1b\[[0-9;]*m", "", open(f"{DATA}/update.log", errors="replace").read()[-4000:])
        return [l.strip() for l in text.splitlines() if l.strip()][-n:]
    except OSError:
        return []


def update_state(fresh=False):
    """What the Updates card shows: this version, the newest release, and whether an update is running, done or stuck."""
    if fresh:
        latest_release.clear()
    rel = latest_release()
    mark = safe(lambda: json.load(open(f"{DATA}/update-started.json")), None)
    state = "idle"
    if mark:
        if vtuple(VERSION) != vtuple(mark.get("from")):
            safe(lambda: os.remove(f"{DATA}/update-started.json"))  # the new version is running: done
        else:
            state = "updating" if time.time() - mark.get("at", 0) < UPDATE_STALE else "failed"
    have, want = vtuple(VERSION), vtuple((rel or {}).get("tag"))
    return {"version": VERSION, "latest": rel["tag"].lstrip("v") if rel else None, "available": bool(have and want and want > have), "url": rel["url"] if rel else "",
            "notes": rel["notes"] if rel else "", "state": state, "log": update_log_tail() if state != "idle" else [], "helper": not CAPS.missing(["host_agent"]),
            "to": (mark or {}).get("to") if state != "idle" else None}


def register(app):
    host.need(globals(), "ALWAYS_ON", "APPS", "B", "CAPS", "SETTINGS", "DAILY", "DASH", "DATA", "DOCKER", "OLLAMA", "PROM", "U", "_ai", "ai_status", "app_name", "edit", "send", "typing")

    router = app.router

    @router.get("/server/apps")
    def server_apps(req):
        try:
            cs = containers()
        except Exception:  # the Docker reader is optional; without it nothing can be listed, which is not the same as nothing installed
            return {"apps": None, "msg": "The app list needs the Docker reader app (docker-proxy), which is not running. Start it from the stack folder with: docker compose up -d docker-proxy"}
        names = sorted((n for n in APPS if n != "docker-proxy"), key=lambda n: app_name(n).lower())
        return {"apps": [{"id": n, "name": "Telegram assistant" if n == "telegram-bot" else app_name(n).split(" (")[0],
                          "state": cs.get(n, "missing")} for n in names]
                + [{"id": a["id"], "name": a["title"], "state": cs.get(a["id"], "missing")} for a in _custom.load(DATA)]}  # your own apps too

    @router.get("/server/catalog")
    def server_catalog(req):
        return catalog()

    @router.post("/server/apps/change")
    def server_apps_change(req):
        """Add or remove an optional app through the host helper. It answers at once; the dashboard then watches the catalog."""
        from core.settings import guard_request
        if bad := guard_request(SETTINGS, req):  # the settings PIN, when one is set, guards installing and removing too
            return bad
        b = req.json() or {}
        act, app_id = b.get("action"), b.get("id")
        if act not in ("add", "remove") or (app_id not in _apps.CATALOG and app_id not in _custom.ids(DATA)):
            return {"ok": False, "msg": "Unknown app."}, 400
        if act == "remove" and (users := _apps.needed_by(app_id, _apps.chosen(DATA))):
            return {"ok": False, "msg": f"{_apps.CATALOG[users[0]][0]} needs it. Remove that first."}, 409
        r = host_action(act, app_id)
        if not r.get("ok"):
            from core.setup import cli_name, run_in
            cli = cli_name(DATA)
            why = (r.get("msg") or "The host helper did not answer.").rstrip(".") + "."
            return {"ok": False, "msg": f"{why} {run_in(cli)}:", "cmds": [f"{cli} apps {act} {app_id}"]}
        return {"ok": True, "msg": "Adding it. The first time downloads the app, which can take a few minutes." if act == "add" else "Removing it. Its data is kept."}

    @router.post("/server/apps/custom")
    def server_apps_custom(req):
        """Add your own app: checks it, saves it to custom.json, then asks the host helper to start it (the same path as Add)."""
        from core.settings import guard_request
        if bad := guard_request(SETTINGS, req):
            return bad
        try:
            live = http(f"{DOCKER}/containers/json?all=1", timeout=10)
        except Exception:
            live = []
        taken = {p.get("PublicPort") for x in live for p in x.get("Ports") or [] if p.get("PublicPort")}
        names = {n.lstrip("/") for x in live for n in x.get("Names") or []}
        app, why = _custom.check(DATA, req.json() or {}, taken, names)
        if why:
            return {"ok": False, "msg": why}, 400
        _custom.add(DATA, app)
        r = host_action("add", app["id"])
        if not r.get("ok"):
            from core.setup import cli_name, run_in
            cli = cli_name(DATA)
            why = (r.get("msg") or "The host helper did not answer.").rstrip(".") + "."
            return {"ok": False, "saved": app["id"], "msg": f"Saved, but not started: {why} {run_in(cli)}:", "cmds": [f"{cli} apps add {app['id']}"]}
        return {"ok": True, "id": app["id"], "msg": f"Adding {app['title']}. The first time downloads it, which can take a few minutes."}

    @router.get("/server/status")
    def server_status(req):
        """What the Home status line needs. Monitoring and the Docker reader are optional apps, so a missing one is
        reported as off (None), never as the server being down. apps lists only containers that exist."""
        try:
            prom("up")
            monitoring = True
        except Exception:
            monitoring = False
        try:
            cs = containers()
        except Exception:
            cs = None
        apps = None if cs is None else [{"id": n, "name": "Telegram assistant" if n == "telegram-bot" else app_name(n).split(" (")[0], "state": s}
                                        for n, s in sorted(cs.items()) if n in APPS and n != "docker-proxy"]
        return {"monitoring": monitoring, "apps": apps}

    @router.post("/server/unload")
    def server_unload(req):
        try:
            return {"ok": True, "msg": free_ai_memory()}
        except Exception:
            return {"ok": False, "msg": "The AI engine isn't reachable right now."}

    @router.post("/server/restart")
    def server_restart(req):
        n = req.json().get("id", "")
        mine = {a["id"]: a["title"] for a in _custom.load(DATA)}
        if (n not in APPS and n not in mine) or n == "docker-proxy":
            return {"ok": False, "msg": "Unknown app."}, 400
        if n in ("telegram-bot", "landing"):  # restarting these cuts this very request off, so answer first
            threading.Thread(target=lambda: (time.sleep(1), host_action("restart", n)), daemon=True).start()
            return {"ok": True, "msg": "Restarting. Back in a few seconds.", "later": True}
        r = host_action("restart", n)
        return {"ok": bool(r.get("ok")), "msg": f"{mine.get(n) or app_name(n).split(' (')[0]} has been restarted." if r.get("ok") else f"Couldn't restart it: {r.get('msg')}"}

    @router.get("/server/update")
    def server_update(req):
        return {"ok": True, **update_state(fresh=req.query.get("fresh") == "1")}

    @router.post("/server/update")
    def server_update_start(req):
        from core.settings import guard_request
        if bad := guard_request(SETTINGS, req):  # the settings PIN, when one is set, guards updating too
            return bad
        st = update_state()
        if st["state"] == "updating":
            return {"ok": False, "msg": "An update is already running."}, 409
        if not st["available"]:
            return {"ok": False, "msg": "You already have the newest version."}, 409
        r = host_action("update")
        if r.get("ok"):
            json.dump({"from": VERSION, "to": st["latest"], "at": time.time()}, open(f"{DATA}/update-started.json", "w"))
        return {"ok": bool(r.get("ok")), "msg": r.get("msg", "")}

    @router.post("/server/gitsync")  # back up to GitHub now; answers with what the run did
    def server_gitsync(req):
        r = host_action("gitsync")
        return r if "at" in r else {"ok": False, "msg": r.get("msg", "")}

    @router.post("/server/reboot")
    def server_reboot(req):
        if req.json().get("confirm") != "reboot":
            return {"ok": False, "msg": "Not confirmed."}, 400
        safe(lambda: send("⏻ Restarting the server from the home page. Back in about 2 minutes.", silent=True))
        threading.Thread(target=lambda: (time.sleep(1), host_action("reboot")), daemon=True).start()
        return {"ok": True}

