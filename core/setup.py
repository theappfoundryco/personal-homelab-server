"""The first-run setup wizard's brain: which steps are done or skipped (saved in the data folder, so it resumes anywhere),
the Telegram connection (token, then your chat id from a /start message), the AI model download with progress, and a restart to apply it.
Every outside call is injectable, so tests never touch Telegram or Ollama. Secrets are written only to the data folder, mode 600, and never sent back."""
import json
import os
import sys
import threading
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from core import settings as _settings
from core.store import read_json, write_json
from core.version import VERSION

FILE = "setup.json"
SECRET = os.path.join("secrets", "telegram.json")
STEPS = [("modules", "What you will use"), ("apps", "Apps"), ("ai", "AI engine"), ("telegram", "Telegram"), ("access", "Access")]
IDS = [s for s, _ in STEPS]
WHY = {"apps": "Pick the extra apps you want, like AI chat or private search.", "modules": "Choose what you want on the dashboard.", "ai": "Chat and the journal's insights need a local AI.",
       "telegram": "Chat with your assistant from your phone.", "access": "Decide who can open the dashboard."}


def telegram_login(data_dir, env=os.environ):
    """(token, chat id): the environment first, then what the wizard saved. Either may be empty."""
    saved = read_json(os.path.join(data_dir, SECRET), {}) or {}
    token = (env.get("TG_TOKEN") or saved.get("token") or "").strip()
    owner = int(env.get("TG_CHAT") or saved.get("owner") or 0)
    return token, owner


def _tg_api(token, method, params, timeout=15):
    req = Request(f"https://api.telegram.org/bot{token}/{method}", json.dumps(params).encode(), {"Content-Type": "application/json"})
    with urlopen(req, timeout=timeout) as r:
        return json.loads(r.read())


def _pull_stream(url, model):
    """Yield Ollama's progress lines for a model download."""
    req = Request(url + "/api/pull", json.dumps({"name": model, "stream": True}).encode(), {"Content-Type": "application/json"})
    with urlopen(req, timeout=3600) as r:
        for line in r:
            if line.strip():
                yield json.loads(line)


def _ollama_tags(url):
    with urlopen(url.rstrip("/") + "/api/tags", timeout=6) as r:
        return json.loads(r.read())


def cli_name(data_dir):
    """How this person runs the command: homelab when install put it on the PATH, else its full path (written by install.sh and core/cli.py)."""
    try:
        name = open(os.path.join(data_dir, "cli.txt")).read().strip()
    except OSError:
        name = ""
    return name or "bin/homelab"


def run_in(cli):
    """The words before a command: a relative path only works from the project folder."""
    return "In the project folder, run" if cli.startswith("bin/") else "Run"


def find_places(q):
    from urllib.parse import urlencode
    with urlopen("https://geocoding-api.open-meteo.com/v1/search?" + urlencode({"name": q, "count": 20, "language": "en", "format": "json"}), timeout=8) as r:
        return json.loads(r.read())


def _restart():
    """Start over in the same process slot, so the new token or Ollama address is read. Docker sees nothing happen."""
    os.execv(sys.executable, [sys.executable, "-u", "-m", "core"])


class Setup:
    def __init__(self, data_dir, tg_api=_tg_api, pull_stream=_pull_stream, ollama_tags=_ollama_tags, restart=_restart, log=print, sleep=None):
        self.sleep = sleep or __import__("time").sleep
        self.dir, self.path = data_dir, os.path.join(data_dir, FILE)
        self.tg_api, self.pull_stream, self.ollama_tags, self.restart, self.log = tg_api, pull_stream, ollama_tags, restart, log
        self.lock = threading.Lock()
        self.pull = {"active": False, "models": [], "current": None, "status": "", "completed": 0, "total": 0, "error": None, "done": False}

    # ---- progress saved in the data folder
    def state(self):
        s = read_json(self.path, None)
        return s if isinstance(s, dict) else None

    def _write(self, s):
        os.makedirs(self.dir, exist_ok=True)
        write_json(self.path, s)

    def mark(self, step, status):
        if step not in IDS and step not in ("calendar",) or status not in ("done", "skipped", "pending"):
            return False
        with self.lock:
            s = self.state() or {"steps": {}}
            s.setdefault("steps", {})[step] = status
            s["finished"] = all(s["steps"].get(i) in ("done", "skipped") for i in IDS)
            self._write(s)
        return True

    def need(self, what="restart"):
        with self.lock:
            s = self.state() or {"steps": {}}
            s["restart"] = True
            self._write(s)

    def dismiss(self, item):
        with self.lock:
            s = self.state() or {"steps": {}}
            s.setdefault("dismissed", [])
            if item not in s["dismissed"]:
                s["dismissed"].append(item)
            self._write(s)

    def reset(self):
        with self.lock:
            self._write({"steps": {}})

    def view(self, telegram_on, caps_missing=()):
        """What the wizard and the home screen's Finish setup card show. Someone who already runs Telegram is not sent through first-run setup."""
        s = self.state()
        steps = (s or {}).get("steps", {})
        first_run = s is None and not telegram_on
        rows = [{"id": i, "title": t, "status": steps.get(i, "pending")} for i, t in STEPS]
        todo = [r["id"] for r in rows if r["status"] != "done"]
        dismissed = (s or {}).get("dismissed", [])
        # once the wizard has been seen, anything not done yet waits on Home instead of the wizard opening again
        checklist = [{"id": r["id"], "title": r["title"], "why": WHY[r["id"]]} for r in rows
                     if (r["status"] == "skipped" or (s and s.get("seen") and r["status"] == "pending")) and r["id"] not in dismissed]
        if s and s.get("finished") and "calendar" in caps_missing and "calendar" not in dismissed and steps.get("calendar") != "done":
            checklist.append({"id": "calendar", "title": "Add your calendar", "why": "See today's events."})
        return {"show": (first_run or bool(s and not s.get("finished") and s.get("started"))) and not (s or {}).get("seen"), "first_run": first_run, "finished": bool((s or {}).get("finished")),
                "steps": rows, "next": todo[0] if todo else None, "checklist": checklist, "restart": bool((s or {}).get("restart"))}

    def seen(self):
        """The wizard opened by itself once. It does not again; what is left waits in the Finish setup card."""
        with self.lock:
            s = self.state() or {"steps": {}}
            s["seen"] = True
            self._write(s)

    def start(self):
        with self.lock:
            s = self.state() or {"steps": {}}
            s["started"] = True
            self._write(s)

    # ---- Telegram
    def _secret(self):
        return read_json(os.path.join(self.dir, SECRET), {}) or {}

    def _save_secret(self, data):
        p = os.path.join(self.dir, SECRET)
        os.makedirs(os.path.dirname(p), exist_ok=True)
        write_json(p, data)
        os.chmod(p, 0o600)

    def telegram_token(self, token):
        """(ok, answer). Checks the token with Telegram, keeps it, and says which bot it is. The token itself is never returned."""
        token = (token or "").strip()
        if not token or ":" not in token or " " in token:
            return False, {"error": "That does not look like a bot token. It looks like 123456:ABC-def, and BotFather gives it to you."}
        try:
            me = self.tg_api(token, "getMe", {})["result"]
        except Exception:
            return False, {"error": "That token was not accepted. Copy it again from BotFather, or check this machine's internet."}
        self._save_secret({"token": token})
        return True, {"bot": me.get("username", "")}

    def telegram_detect(self):
        """Look for your first message to the bot. (state, answer): waiting until it arrives, then connected."""
        token = self._secret().get("token")
        if not token:
            return {"state": "no_token"}
        try:
            ups = self.tg_api(token, "getUpdates", {"timeout": 0, "limit": 20})["result"]
        except Exception:
            return {"state": "waiting", "note": "Could not reach Telegram just now. Trying again."}
        for u in ups:
            chat = (u.get("message") or {}).get("chat", {})
            if chat.get("type") == "private" and chat.get("id"):
                try:
                    self.tg_api(token, "getUpdates", {"offset": u["update_id"] + 1, "timeout": 0})  # so the bot does not replay it after the restart
                    self.tg_api(token, "sendMessage", {"chat_id": chat["id"], "text": "Connected. I'm ready when you are."})
                except Exception:
                    pass
                self._save_secret({"token": token, "owner": chat["id"]})
                self.mark("telegram", "done")
                self.need()
                return {"state": "connected"}
        return {"state": "waiting"}

    # ---- the AI engine
    def check_ollama(self, url):
        """(ok, message) for another machine's Ollama."""
        url = (url or "").strip().rstrip("/")
        if not url.lower().startswith(("http://", "https://")):
            return False, "The address should start with http:// or https://, for example http://192.168.1.20:11434."
        try:
            self.ollama_tags(url)
        except HTTPError:
            return False, f"Something answered at {url}, but it is not Ollama. Check the port (Ollama uses 11434)."
        except (URLError, OSError, ValueError) as e:
            why = str(getattr(e, "reason", e)).lower()
            if "refused" in why:
                hint = "The machine answered, but Ollama only listens to itself there. Open it to your network with the steps below."
            elif "timed out" in why or "timeout" in why:
                hint = "Nothing answered. Check that the machine is on, on the same network or Tailscale, and that its firewall allows port 11434."
            elif "name" in why or "known" in why:
                hint = "That name could not be found. Check the spelling, or use the machine's IP address."
            else:
                hint = "Check that the machine is on and Ollama is running there, then open it to your network with the steps below."
            return False, f"Could not reach Ollama at {url}. {hint}"
        return True, ""

    def find_ollama(self, urls):
        """Every Ollama that answers among urls (checked together, a couple of seconds at most), with its models. Used to offer the one you already have."""
        found = {}

        def one(u):
            try:
                found[u] = sorted(m.get("name", "") for m in (self.ollama_tags(u) or {}).get("models", []))
            except Exception:
                pass
        ts = [threading.Thread(target=one, args=(u,), daemon=True) for u in dict.fromkeys(urls)]
        for t in ts:
            t.start()
        for t in ts:
            t.join(4)
        return [{"url": u, "models": found[u]} for u in dict.fromkeys(urls) if u in found]

    def start_pull(self, ollama_url, models, wait=0):
        """Download models one after another in the background. False if one is already running.
        wait: seconds to wait for Ollama to come up first (it is being installed), checked every few seconds."""
        with self.lock:
            if self.pull["active"]:
                return False
            self.pull = {"active": True, "models": [{"name": m, "status": "waiting"} for m in models], "current": None, "status": "starting",
                         "completed": 0, "total": 0, "error": None, "done": False}
        threading.Thread(target=self._pull_all, args=(ollama_url, list(models), wait), daemon=True).start()
        return True

    def _pull_all(self, url, models, wait=0):
        try:
            if wait:
                self.pull.update(status="Installing the AI engine. The first time downloads it, which can take a few minutes.")
                for _ in range(int(wait / 3)):
                    try:
                        self.ollama_tags(url)
                        break
                    except Exception:
                        self.sleep(3)
                else:
                    raise RuntimeError("engine did not start")
            have = set()
            try:
                have = {n for x in (self.ollama_tags(url) or {}).get("models", []) for n in (x.get("name", ""), x.get("name", "").removesuffix(":latest"))}
            except Exception:
                pass
            for i, m in enumerate(models):
                if m in have:  # already on that Ollama: nothing to download
                    self.pull["models"][i]["status"] = "already here"
                    continue
                self.pull.update(current=m, completed=0, total=0, status="starting")
                self.pull["models"][i]["status"] = "downloading"
                for line in self.pull_stream(url, m):
                    if line.get("error"):
                        raise RuntimeError(line["error"])
                    self.pull.update(status=line.get("status", ""), completed=int(line.get("completed") or self.pull["completed"]), total=int(line.get("total") or self.pull["total"]))
                self.pull["models"][i]["status"] = "done"
            self.pull.update(done=True, status="done")
            self.mark("ai", "done")
        except Exception as e:
            self.log(f"setup: model download failed: {e}")
            why = str(e).lower()
            self.pull.update(error="The AI engine did not start. Open Settings, Apps to see why, then try again." if "did not start" in why
                             else "There is not enough free disk for this model. Free some space, or pick a smaller one, then try again." if "space" in why or "disk" in why
                             else "The AI engine stopped answering during the download. It may have restarted. Press Download to carry on where it stopped."
                             if isinstance(e, (URLError, OSError)) else f"The download stopped: {e}. Press Download to try again.")
        finally:
            self.pull["active"] = False


HOST_OLLAMA = "http://host.docker.internal:11434"  # an Ollama running on the machine itself, outside Docker (the Mac app, for the Apple GPU)


def routes(router, setup, settings, hardware_view, modules, telegram_on, caps_missing, ollama_url, add_app=None, host_do=None):
    """GET /setup, POST /setup/step, /setup/start, /setup/profile, /setup/restart, /setup/dismiss, /setup/reset, /setup/modules, /setup/telegram/*, /setup/ai/*."""
    def guard(req):
        return _settings.guard_request(settings, req)

    @router.get("/setup")
    def get_setup(req):
        out = setup.view(telegram_on(), caps_missing())
        hv = hardware_view()
        eff = settings.merged()
        return {**out, "profile": {"name": (eff.get("owner") or {}).get("name") or "", "timezone": eff.get("timezone") or "",
                            "home": (settings.over.get("home") or {}).get("city") or ""},  # only a city you picked, never the example's
                "hardware": hv, "modules": settings.view(modules())["modules"], "telegram": {"connected": telegram_on()},
                "pin": bool(settings.pin), "pull": setup.pull, "version": VERSION, "cli": cli_name(setup.dir)}

    @router.post("/setup/step")
    def step(req):
        if bad := guard(req):
            return bad
        b = req.json() or {}
        return ({"ok": True}, 200) if setup.mark(b.get("id"), b.get("status")) else ({"ok": False, "error": "Unknown step."}, 400)

    @router.post("/setup/start")
    def start(req):
        if bad := guard(req):
            return bad
        setup.start()
        return {"ok": True}

    @router.post("/setup/seen")
    def seen(req):
        setup.seen()
        return {"ok": True}

    @router.post("/setup/apps")
    def choose_apps(req):
        """The wizard's app picks. New ones are added and unticked ones removed through the host helper; the AI engine is its own step.
        Without the helper the picks are saved, and the answer says the one command that starts them."""
        if bad := guard(req):
            return bad
        from core import apps as _apps
        want = [a for a in (req.json() or {}).get("apps") or [] if a in _apps.CATALOG and a != "ollama"]
        have = _apps.chosen(setup.dir)
        add = [a for a in want if a not in have]
        drop = [a for a in have if a not in want and a != "ollama" and not _apps.needed_by(a, want)]
        if not add and not drop:
            return {"ok": True, "changed": False}
        failed = []
        for act, ids in (("add", add), ("remove", drop)):
            for a in ids:
                r = host_do(act, a) if host_do else {"ok": False}
                if not r.get("ok"):
                    failed.append(a)
        if failed:  # no helper: save the choice, so the next `homelab start` brings them up
            _apps.save(setup.dir, [a for a in have if a not in drop] + add)
            cli = cli_name(setup.dir)
            return {"ok": True, "changed": True, "pending": add, "cmds": [f"{cli} apps add {' '.join(add)}" if add else f"{cli} start"],
                    "msg": f"Saved. The host helper is not running, so start them yourself. {run_in(cli)}:"}
        return {"ok": True, "changed": True, "msg": "Adding them now. The first time downloads each app, which can take a few minutes."}

    @router.post("/setup/dismiss")
    def dismiss(req):
        setup.dismiss(str((req.json() or {}).get("id", "")))
        return {"ok": True}

    @router.post("/setup/reset")
    def reset(req):
        if bad := guard(req):
            return bad
        setup.reset()
        return {"ok": True}

    @router.get("/setup/places")
    def places(req):
        """Places matching what you typed (Open-Meteo's free place search, no key), for picking your home city."""
        q = (req.query.get("q") or "").strip()
        if len(q) < 2:
            return {"ok": True, "places": []}
        try:
            d = find_places(q)
        except Exception:
            return {"ok": False, "error": "Places can't be looked up right now (no internet?). You can skip this and set it later in Settings."}
        out, seen = [], set()
        for r in d.get("results") or []:  # the search lists villages and districts with the same name too; the biggest place comes first, keep only it
            key = (r.get("name"), r.get("admin1") or "", r.get("country") or "")
            if r.get("name") and key not in seen:
                seen.add(key)
                out.append({"city": r.get("name"), "country": r.get("country") or "", "region": r.get("admin1") or "", "lat": r.get("latitude"),
                            "lon": r.get("longitude"), "tz": r.get("timezone") or ""})
        return {"ok": True, "places": out[:6]}

    @router.post("/setup/profile")
    def profile(req):
        """Your name (how the dashboard and bot greet you) and time zone. Either may be left out."""
        if bad := guard(req):
            return bad
        b = req.json() or {}
        changes = {}
        name = str(b.get("name") or "").strip()
        if name:
            if len(name) > 40:
                return {"ok": False, "error": "Please use 40 letters or fewer."}, 400
            changes["owner.name"] = name
        if b.get("timezone"):
            changes["timezone"] = str(b["timezone"]).strip()
        h = b.get("home")
        if isinstance(h, dict) and h.get("city"):  # a place picked from the search: weather and the world clock start here
            try:
                changes.update({"home.city": str(h["city"])[:60], "home.country": str(h.get("country") or "")[:60], "home.lat": float(h["lat"]), "home.lon": float(h["lon"])})
            except (TypeError, ValueError, KeyError):
                return {"ok": False, "error": "That place could not be used. Pick it from the list again."}, 400
            if h.get("tz"):
                changes["home.tz"] = str(h["tz"])
        if not changes:
            return {"ok": True}
        ok, problems = settings.set(changes)
        if not ok:
            return {"ok": False, "error": " ".join(problems)}, 400
        if "timezone" in changes or "home.city" in changes:
            setup.need()  # the clock and home are read once at start
        return {"ok": True}

    @router.post("/setup/modules")
    def pick_modules(req):
        if bad := guard(req):
            return bad
        chosen = (req.json() or {}).get("enabled")
        if not isinstance(chosen, dict):
            return {"ok": False, "error": "Nothing to change."}, 400
        known = {m["name"] for m in modules()}
        ok, problems = settings.set({f"modules.{k}": bool(v) for k, v in chosen.items() if k in known})
        if not ok:
            return {"ok": False, "problems": problems}, 400
        setup.mark("modules", "done")
        setup.need()
        return {"ok": True}

    @router.post("/setup/telegram/token")
    def tg_token(req):
        if bad := guard(req):
            return bad
        if telegram_on():
            return {"ok": False, "error": "Telegram is already connected. To change the bot, edit TG_TOKEN and TG_CHAT in the .env file."}, 409
        ok, out = setup.telegram_token((req.json() or {}).get("token"))
        return ({"ok": True, **out}, 200) if ok else ({"ok": False, **out}, 400)

    @router.post("/setup/telegram/detect")
    def tg_detect(req):
        if bad := guard(req):
            return bad
        return {"ok": True, **setup.telegram_detect()}

    @router.post("/setup/ai")
    def ai_choose(req):
        """mode: install (download the suggested models), remote (another machine's Ollama, with url) or none."""
        if bad := guard(req):
            return bad
        b = req.json() or {}
        mode = b.get("mode")
        rec = hardware_view()["recommendation"]
        if mode == "none":
            setup.mark("ai", "skipped")
            return {"ok": True}
        url = None
        if mode == "remote":
            ok, why = setup.check_ollama(b.get("url"))
            if not ok:
                return {"ok": False, "error": why}, 400
            url = b["url"].strip().rstrip("/")
            okset, problems = settings.set({"ollama.url": url})
            if not okset:
                return {"ok": False, "problems": problems}, 400
            setup.mark("ai", "done")
            setup.need()
            return {"ok": True}
        if mode == "use":  # an Ollama that detect found; models it lacks are downloaded next
            from core import llm
            url = (b.get("url") or "").strip().rstrip("/")
            if url not in (llm.DEFAULT_URL, HOST_OLLAMA, ollama_url()):
                return {"ok": False, "error": "Choose one of the engines that were found."}, 400
            if url != ollama_url():
                okset, problems = settings.set({"ollama.url": url})
                if not okset:
                    return {"ok": False, "problems": problems}, 400
                setup.need()
            mode = "install"
            target = url
        else:
            target = None
        if mode != "install":
            return {"ok": False, "error": "Choose install, remote or none."}, 400
        if not rec["models"]:
            return {"ok": False, "error": "This machine is too small for local AI. Use another machine's Ollama, or skip."}, 400
        changes = {f"models.{m['role']}": m["name"] for m in rec["models"]}
        if bad := [w for m in rec["models"] for w in m["warnings"]]:
            if not b.get("anyway"):
                return {"ok": False, "warnings": bad}, 409
        settings.set(changes)
        from core import llm
        if not target and hardware_view()["hardware"].get("os") == "mac" and ollama_url() in (llm.DEFAULT_URL, HOST_OLLAMA):
            target = HOST_OLLAMA  # on a Mac the engine runs on the Mac itself, for the Apple GPU (the helper installs it with Homebrew)
            if ollama_url() != HOST_OLLAMA:
                settings.set({"ollama.url": HOST_OLLAMA})
                setup.need()
        target = target or ollama_url()
        wait = 0
        if not setup.find_ollama([target]):
            # No AI engine yet: install the app first (through the host helper), then the download waits for it to come up
            if target not in (llm.DEFAULT_URL, HOST_OLLAMA):
                return {"ok": False, "error": f"The AI engine at {target} is not answering. Start it, or choose another option."}, 400
            r = add_app("ollama") if add_app else {"ok": False, "msg": ""}
            if not r.get("ok"):
                cli = cli_name(setup.dir)
                return {"ok": False, "error": f"The AI engine is not installed yet, and the host helper that installs apps is not running. {run_in(cli)} the first "
                        "command to install it now, or the second once so the dashboard can do it for you. Then press Download again.",
                        "cmds": [f"{cli} apps add ollama", f"{cli} agent install"]}, 400
            wait = 900
        if not setup.start_pull(target, [m["name"] for m in rec["models"]], wait=wait):
            return {"ok": False, "error": "A download is already running."}, 409
        return {"ok": True, "installing": bool(wait)}

    @router.get("/setup/ai/detect")
    def ai_detect(req):
        """Any Ollama this assistant can already reach: the one set in config, the AI engine app, or one running on this machine itself."""
        from core import apps, llm
        found = setup.find_ollama([ollama_url(), llm.DEFAULT_URL, HOST_OLLAMA])
        for f in found:
            f["where"] = "this machine" if f["url"] == HOST_OLLAMA else "the AI engine app" if f["url"] == llm.DEFAULT_URL else f["url"]
        return {"found": found, "app_chosen": "ollama" in apps.chosen(setup.dir), "current": ollama_url()}

    @router.post("/setup/access")
    def access(req):
        """lan or local: the host helper rewrites the bind address and restarts only the dashboard, so nobody has to run install.sh --lan."""
        if bad := guard(req):
            return bad
        mode = (req.json() or {}).get("mode")
        if mode not in ("lan", "local"):
            return {"ok": False, "error": "Choose lan or local."}, 400
        if mode == "lan" and not settings.pin:
            return {"ok": False, "error": "Choose a PIN first, so only you can change things."}, 400
        r = host_do("access", mode) if host_do else {"ok": False}
        if not r.get("ok"):
            cli = cli_name(setup.dir)
            return {"ok": False, "error": f"The host helper that does this is not running. {run_in(cli)} the first command to do it now, "
                    "or the second once so the dashboard can do it for you.", "cmds": [f"{cli} access {mode}", f"{cli} agent install"]}, 400
        return {"ok": True}

    @router.get("/setup/access")
    def access_view(req):
        """What the last access change wrote (the address to open from a phone)."""
        try:
            with open(os.path.join(setup.dir, "access.json")) as f:
                return json.load(f)
        except (OSError, ValueError):
            return {"mode": "", "url": ""}

    @router.post("/setup/ai/pull")
    def ai_pull(req):
        """Download one model by name (the Server page's Download button for a model that is set but not on the engine yet)."""
        if bad := guard(req):
            return bad
        name = str((req.json() or {}).get("name") or "").strip()
        if not name or len(name) > 80 or any(c in name for c in " /\\"):
            return {"ok": False, "error": "Unknown model."}, 400
        if not setup.start_pull(ollama_url(), [name]):
            return {"ok": False, "error": "A download is already running."}, 409
        return {"ok": True}

    @router.get("/setup/ai/progress")
    def ai_progress(req):
        return setup.pull

    @router.post("/setup/restart")
    def restart(req):
        if bad := guard(req):
            return bad
        threading.Timer(1.0, setup.restart).start()
        return {"ok": True, "note": "Restarting. This page comes back in a few seconds."}
