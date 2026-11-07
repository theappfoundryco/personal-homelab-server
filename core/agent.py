"""The host helper: does the few things the assistant cannot do from inside its container (restart an app, update, reboot).
The assistant drops a small file in <data>/requests; this program, running as you on the host, answers in <data>/results.
It does only what ALLOW names, only to this project's containers, and ignores anything old or oddly shaped. Standard library only."""
import json
import os
import re
import shutil
import subprocess
import sys
import threading
import time as _time  # not `time`: the test harness swaps that name to freeze the clock

ALLOW = ("restart", "start", "reboot", "update", "add", "remove", "access", "backup", "restore", "drives", "offsite", "passphrase")
# add and remove take an app id from core/apps.py or core/custom.py; access takes lan or local; restore takes a backup's file name;
# passphrase takes the new passphrase in hex (or - to remove it)
PROJECT = "homelab"  # the compose project; only its containers can be restarted
ID = re.compile(r"^[A-Za-z0-9_-]{1,40}$")
APP = re.compile(r"^[a-z0-9][a-z0-9_.-]{0,60}$")
MAX_BYTES, MAX_AGE, KEEP_RESULTS = 200, 120, 3600  # a request file's size, how old it may be, how long answers are kept (seconds)
BEAT = "agent.json"
FRESH = 120  # a heartbeat older than this means the helper is not running
LABEL = "homelab.agent"  # launchd name; the one place to change on a rename
UNIT = "homelab-agent.service"


def shell(cmd, cwd=None, env=None, timeout=120):
    try:
        r = subprocess.run(cmd, cwd=cwd, env={**os.environ, **env} if env else None, capture_output=True, text=True, timeout=timeout)
        return r.returncode, (r.stdout + r.stderr).strip()
    except FileNotFoundError:
        return 127, f"{cmd[0]} is not installed"
    except subprocess.TimeoutExpired:
        return 124, "timed out"


def clock(text):
    """(hour, minute) from "3:30 AM" or "03:30", or None."""
    import re as _re
    m = _re.match(r"^\s*(\d{1,2})(?::(\d{2}))?\s*([AaPp][Mm])?\s*$", str(text or ""))
    if not m:
        return None
    h, mi = int(m.group(1)), int(m.group(2) or 0)
    if m.group(3):
        h = h % 12 + (12 if m.group(3).lower() == "pm" else 0)
    return (h, mi) if h < 24 and mi < 60 else None


def alive(data_dir, now=None):
    """Is the helper running? Judged by its heartbeat. A server that never had one but has a results folder (the older helper) counts as running."""
    try:
        with open(os.path.join(data_dir, BEAT)) as f:
            return (now if now is not None else _time.time()) - float(json.load(f)["time"]) < FRESH
    except (OSError, ValueError, KeyError, TypeError):
        return not os.path.exists(os.path.join(data_dir, BEAT)) and os.path.isdir(os.path.join(data_dir, "results"))


class Agent:
    def __init__(self, data_dir, root, run=shell, spawn=None, log=print, now=None, allow_reboot=False, python=None, spawn_apps=None, stats_dir=None, home=None,
                 platform=None, notify=None):
        self.data, self.root, self.run, self.log = data_dir, root, run, log
        self.home = home or os.path.dirname(os.path.abspath(data_dir))  # ~/.homelab: backups and the passphrase live here, outside the container's view
        self.backups = os.path.join(self.home, "backups")
        self.platform = platform or ("mac" if sys.platform == "darwin" else "linux")
        self.notify = notify or self._notify
        self.backup_busy, self.bot_down_since = False, None
        self.stats = stats_dir  # where host.json goes (what this machine is and how busy it is), for the Server page
        self.now = now or _time.time
        self.allow_reboot, self.python = allow_reboot, python or sys.executable
        self.spawn = spawn or self._spawn
        self.spawn_apps = spawn_apps or self._spawn_apps
        self.update_proc = self.apps_proc = None
        self.night_running = set()
        self.req, self.res = os.path.join(data_dir, "requests"), os.path.join(data_dir, "results")

    # ---- what it may do
    def containers(self):
        out = set()
        for f in (f"label=com.docker.compose.project={PROJECT}", "label=homelab.custom"):  # this project's apps, and the ones you added yourself
            rc, text = self.run(["docker", "ps", "-a", "--filter", f, "--format", "{{.Names}}"])
            out |= set(text.split()) if rc == 0 else set()
        return out

    def _spawn(self):  # unbuffered (-u): a file is block-buffered, so without it the log stayed empty until the update ended
        log = open(os.path.join(self.data, "update.log"), "ab")
        return subprocess.Popen([self.python, "-u", "-W", "ignore", "-m", "core.cli", "update", "--yes"], cwd=self.root, env={**os.environ, "PYTHONPATH": self.root, "PYTHONUNBUFFERED": "1"},
                                stdout=log, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL, start_new_session=True)

    def _spawn_apps(self, action, app):
        """Adding an app can download for minutes, so it runs on its own; progress goes to apps.log."""
        log = open(os.path.join(self.data, "apps.log"), "ab")
        args = ["access", app] if action == "access" else ["apps", action, app]
        return subprocess.Popen([self.python, "-u", "-W", "ignore", "-m", "core.cli", *args], cwd=self.root, env={**os.environ, "PYTHONPATH": self.root, "PYTHONUNBUFFERED": "1"},
                                stdout=log, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL, start_new_session=True)

    def handle(self, text):
        """One request line, like "restart telegram-bot". Returns (ok, message). Never raises."""
        parts = text.split()
        if not parts or parts[0] not in ALLOW:
            return False, "unknown action"
        action = parts[0]
        if action in ("restart", "start"):
            if len(parts) != 2 or not APP.match(parts[1]):
                return False, "that needs one app name"
            if parts[1] not in self.containers():
                return False, f"unknown app {parts[1]}"
            ok = self.run(["docker", action, parts[1]])[0] == 0
            return ok, f"{parts[1]} {'restarted' if action == 'restart' else 'started'}" if ok else f"docker {action} failed"
        if action in ("add", "remove", "access"):
            from core import apps, custom
            if len(parts) != 2 or parts[1] not in (("lan", "local") if action == "access" else [*apps.CATALOG, *custom.ids(self.data)]):
                return False, "that needs one app name from the list"
            if self.apps_proc is not None and self.apps_proc.poll() is None:
                return False, "another app change is still running"
            try:
                self.apps_proc = self.spawn_apps(action, parts[1])
            except OSError as e:
                return False, f"could not start it ({e})"
            return True, f"{ {'add': 'adding', 'remove': 'removing', 'access': 'switching access to'}[action]} {parts[1]} (progress is in apps.log)"
        if action in ("backup", "restore", "drives", "offsite", "passphrase"):
            return self.backup_action(action, parts[1:])
        if len(parts) != 1:
            return False, f"{action} takes no name"
        if action == "reboot":
            if not self.allow_reboot:
                return False, "rebooting is switched off. Turn it on with: homelab agent install --allow-reboot"
            return None, "rebooting"  # the caller answers first, then reboots
        if self.update_proc is not None and self.update_proc.poll() is None:
            return False, "an update is already running"
        try:
            self.update_proc = self.spawn()
        except OSError as e:
            return False, f"could not start the update ({e})"
        return True, "update started; the assistant restarts when it finishes (progress is in update.log)"

    # ---- the loop
    def answer(self, rid, ok, msg):
        os.makedirs(self.res, exist_ok=True)
        tmp = os.path.join(self.res, rid + ".tmp")
        with open(tmp, "w") as f:
            json.dump({"ok": bool(ok), "msg": msg}, f)
        os.replace(tmp, os.path.join(self.res, rid + ".json"))

    def drain(self):
        """Handles every waiting request. Returns how many it answered."""
        if not os.path.isdir(self.req):
            return 0
        done, reboot = 0, False
        for rid in sorted(os.listdir(self.req)):
            path = os.path.join(self.req, rid)
            try:
                st = os.lstat(path)
                regular = os.path.isfile(path) and not os.path.islink(path)
                text = open(path).read(MAX_BYTES + 1) if regular and st.st_size <= MAX_BYTES else None
                os.remove(path)
            except OSError:
                continue
            if not ID.match(rid):
                continue
            if text is None:
                self.answer(rid, False, "that request was not understood")
            elif self.now() - st.st_mtime > MAX_AGE:
                self.answer(rid, False, "that request was too old, so it was ignored")
            else:
                ok, msg = self.handle(text)
                self.log(f"{text.strip()[:60]} -> {msg}")
                self.answer(rid, ok is not False, msg)
                reboot = reboot or ok is None
            done += 1
        if reboot:
            self.run(["systemctl", "reboot"] if sys.platform.startswith("linux") else ["sudo", "-n", "shutdown", "-r", "now"])
        return done

    def beat(self):
        os.makedirs(self.data, exist_ok=True)
        tmp = os.path.join(self.data, BEAT + ".tmp")
        with open(tmp, "w") as f:
            json.dump({"time": self.now(), "pid": os.getpid(), "reboot": bool(self.allow_reboot)}, f)  # the dashboard hides Restart server unless you allowed it
        os.replace(tmp, os.path.join(self.data, BEAT))

    def prune(self):
        if os.path.isdir(self.res):
            for f in os.listdir(self.res):
                p = os.path.join(self.res, f)
                if os.path.isfile(p) and self.now() - os.path.getmtime(p) > KEEP_RESULTS:
                    os.remove(p)

    # ---- the night jobs you turned on in Settings, Night jobs (night in settings.json): a backup, and a copy of your settings to git
    def night_due(self, now=None):
        """[(job, command args)] that should start now: on, past their time today, and not run yet today."""
        try:
            with open(os.path.join(self.data, "settings.json")) as f:
                night = json.load(f).get("night") or {}
        except (OSError, ValueError, AttributeError):
            return []
        now = now or _time.localtime(self.now())
        today, done = _time.strftime("%Y-%m-%d", now), self._night_state()
        due = []
        for job, on, at, args in (("backup", night.get("backup"), night.get("backup_at") or "3:30 AM",
                                   ["backup", "--keep", str(night.get("backup_keep") or 7)] + (["--to", night["backup_to"]] if night.get("backup_to") else [])),
                                  ("github", night.get("github") and night.get("github_repo"), night.get("github_at") or "3:45 AM",
                                   ["settings-sync", str(night.get("github_repo") or "")])):
            hm = clock(at)
            if on and hm and (now.tm_hour, now.tm_min) >= hm and done.get(job) != today and job not in self.night_running:
                due.append((job, args))
        return due

    def _night_state(self):
        try:
            with open(os.path.join(self.data, "night-runs.json")) as f:
                return json.load(f).get("last") or {}
        except (OSError, ValueError, AttributeError):
            return {}

    def night_record(self, job, start, ok, msg):
        p = os.path.join(self.data, "night-runs.json")
        try:
            with open(p) as f:
                d = json.load(f)
        except (OSError, ValueError):
            d = {}
        d.setdefault("last", {})[job] = _time.strftime("%Y-%m-%d", _time.localtime(start))
        d["runs"] = (d.get("runs") or [])[-40:] + [{"job": job, "start": start, "end": self.now(), "ok": ok, "msg": msg[-300:]}]
        with open(p + ".tmp", "w") as f:
            json.dump(d, f)
        os.replace(p + ".tmp", p)

    def night(self):
        for job, args in self.night_due():
            self.night_running.add(job)
            start = self.now()
            self.night_record(job, start, None, "started")  # marks today as taken, so a restart of the helper does not run it twice

            def go(job=job, args=args, start=start):
                rc, out = self.run([self.python, "-W", "ignore", "-m", "core.cli", *args], cwd=self.root, env={"PYTHONPATH": self.root}, timeout=3600)
                self.night_record(job, start, rc == 0, out.strip().splitlines()[-1] if out.strip() else "")
                self.night_running.discard(job)
                if job == "backup":
                    self.after_backup(rc == 0, out, "nightly")
            threading.Thread(target=go, daemon=True).start()

    # ---- backups (Settings, Backups): now, restore, the copy to your own drive or folder, and problem alerts on Telegram
    def night_settings(self):
        try:
            with open(os.path.join(self.data, "settings.json")) as f:
                return json.load(f).get("night") or {}
        except (OSError, ValueError, AttributeError):
            return {}

    def backup_action(self, action, args):
        from core import backups
        if action == "drives":
            backups.write_status(self.data, drives=backups.drives(self.platform))
            return True, "drives listed"
        if action == "offsite":
            self.refresh_status()
            return True, "checked"
        if action == "passphrase":
            if len(args) != 1:
                return False, "that needs the passphrase"
            try:
                text = "" if args[0] == "-" else bytes.fromhex(args[0]).decode("utf-8")
            except ValueError:
                return False, "that passphrase was not understood"
            ok, msg = backups.set_passphrase(self.home, text)
            self.refresh_status()
            return ok, msg
        if action == "backup":
            if args:
                return False, "backup takes no name"
            if self.backup_busy:
                return False, "a backup is already running"
            self.backup_busy = True

            def go():
                try:
                    rc, out = self.run([self.python, "-W", "ignore", "-m", "core.cli", "backup"], cwd=self.root, env={"PYTHONPATH": self.root}, timeout=3600)
                    self.after_backup(rc == 0, out, "manual")
                finally:
                    self.backup_busy = False
            threading.Thread(target=go, daemon=True).start()
            return True, "backup started"
        if len(args) != 1 or not backups.NAME.match(args[0]) or not os.path.isfile(os.path.join(self.backups, args[0])):
            return False, "that backup is not in the backups folder"
        log = open(os.path.join(self.data, "restore.log"), "ab")
        subprocess.Popen([self.python, "-u", "-W", "ignore", "-m", "core.cli", "restore", os.path.join(self.backups, args[0]), "--yes"], cwd=self.root,
                         env={**os.environ, "PYTHONPATH": self.root, "PYTHONUNBUFFERED": "1"}, stdout=log, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL, start_new_session=True)
        return True, "restoring; the assistant restarts when it is done"

    def refresh_status(self, last=None):
        """Writes what the Backups page shows: the list, the chosen folder's state right now, and whether copies are locked."""
        from core import backups
        to = self.night_settings().get("offsite_to") or ""
        prev = backups.read_status(self.data).get("offsite") or {}
        prev = prev if prev.get("to") == to else {}
        live = backups.check_target(to, self.home, self.platform) if to else "off"
        state = live if live != "ok" else ("ok" if prev.get("state") == "ok" else "ready")
        parts = {"list": backups.listing(self.backups), "passphrase": os.path.isfile(os.path.join(self.home, backups.PASSFILE)),
                 "offsite": {**prev, "to": to, "state": state, "msg": backups.STATES.get(state, "")}}
        if last:
            parts["last"] = last
        return backups.write_status(self.data, **parts)

    def after_backup(self, ok, out, kind):
        """After a backup: record it, copy the newest one out if a folder is chosen, and say so on Telegram when something went wrong."""
        from core import backups
        lst = backups.listing(self.backups)
        newest = next((b for b in lst if b["kind"] in ("nightly", "backup")), None)
        msg = out.strip().splitlines()[-1].strip() if out and out.strip() else ""
        last = {"at": self.now(), "ok": bool(ok and newest), "kind": kind, "file": newest["name"] if newest and ok else None,
                "size": newest["size"] if newest and ok else 0, "msg": "" if ok else re.sub(r"^\s*stop\s+", "", msg)}
        self.refresh_status(last)
        if not ok:
            self.alert("backup-failed", f"⚠️ <b>Last night's backup did not work</b>\n{last['msg'] or 'See Settings, Backups.'}" if kind == "nightly" else None)
            return
        self.copy_out(newest)

    def copy_out(self, newest):
        from core import backups
        night = self.night_settings()
        to = night.get("offsite_to")
        if not to or not newest:
            return
        state, name = backups.copy_out(os.path.join(self.backups, newest["name"]), to, int(night.get("offsite_keep") or 7), self.home, self.platform)
        off = {"to": to, "state": state, "msg": backups.STATES.get(state, ""), "at": self.now() if state == "ok" else (backups.read_status(self.data).get("offsite") or {}).get("at"),
               "file": name if state == "ok" else (backups.read_status(self.data).get("offsite") or {}).get("file"), "source": newest["name"],
               "encrypted": bool(name and name.endswith(".enc"))}
        backups.write_status(self.data, offsite=off)
        if state != "ok":
            self.alert(f"offsite-{state}", f"💾 <b>The backup copy did not go to your drive</b>\n{backups.STATES.get(state, '')}\nThe backup itself is safe on this machine.")

    def watch(self):
        """Every few minutes: copy a waiting backup once its drive is back, warn about a nearly full disk, and about the assistant being down."""
        from core import backups
        try:
            st = backups.read_status(self.data)
            off, lst = st.get("offsite") or {}, backups.listing(self.backups)
            newest = next((b for b in lst if b["kind"] in ("nightly", "backup")), None)
            if self.night_settings().get("offsite_to") and newest and (off.get("state") != "ok" or off.get("source") != newest["name"]) and not self.backup_busy:
                self.copy_out(newest)
        except Exception as e:
            self.log(f"backup copy check: {e}")
        try:
            u = shutil.disk_usage(self.home)
            pct = round(100 * (u.total - u.free) / u.total) if u.total else 0
            backups.write_status(self.data, disk={"pct": pct, "free": u.free, "total": u.total})
            if pct >= 90:
                self.alert(f"disk-{95 if pct >= 95 else 90}", f"💽 <b>This machine's disk is {pct}% full</b>\n{u.free / 1e9:.1f} GB left. Free some space; old backups are in ~/.homelab/backups.")
        except OSError:
            pass
        if os.path.exists(os.path.join(self.data, "stopped-by-you.json")):
            self.bot_down_since = None  # you stopped it with homelab stop: nothing to say
            return
        rc, text = self.run(["docker", "inspect", "-f", "{{.State.Running}}", "telegram-bot"])
        if rc == 0 and text.strip() == "false":
            self.bot_down_since = self.bot_down_since or self.now()
            if self.now() - self.bot_down_since >= 600:
                started = self.run(["docker", "start", "telegram-bot"])[0] == 0
                self.alert("bot-down", "🛑 <b>The assistant stopped</b>\n" + ("I started it again. If it keeps stopping, run: homelab logs" if started else "It would not start. Run: homelab doctor"))
                self.bot_down_since = None
        else:
            self.bot_down_since = None

    def alert(self, key, text):
        """A problem alert on Telegram, at most once a day per kind, unless turned off in Settings, Backups."""
        from core import backups
        if text and self.night_settings().get("alerts", True) and backups.once_a_day(self.data, key, self.now()):
            self.notify(text)

    def _notify(self, text):
        from core import backups
        from core.cli import read_env
        return backups.telegram(read_env(os.path.join(self.root, "stack", ".env")), text)

    def serve(self, every=2, stop=lambda: False, sleep=_time.sleep):
        self.log(f"host helper running for {self.data}")
        for d in (self.req, self.res):  # made by you, not by the container, so you are allowed to clear what it leaves
            os.makedirs(d, exist_ok=True)
        if self.stats:  # its own thread: reading the CPU takes a second on a Mac, and requests should not wait for it
            from core import hostinfo
            threading.Thread(target=hostinfo.loop, args=(self.stats, "mac" if sys.platform == "darwin" else "linux"),
                             kwargs={"stop": stop, "log": self.log}, daemon=True).start()
        n = 0
        while not stop():
            try:
                self.beat()
                self.drain()
                if n % 15 == 0:
                    self.night()
                if n % 300 == 0:
                    self.prune()
                if n % 150 == 0:  # every 5 minutes: a copy that is waiting for its drive, the disk, and the assistant itself
                    self.watch()
            except Exception as e:  # keep serving: one bad request must not stop restarts working
                self.log(f"error: {e}")
            n += 1
            sleep(every)


# ---- installing it as a background service on this machine

def path_for_service(home):
    return ":".join([os.path.join(home, ".orbstack", "bin"), "/opt/homebrew/bin", "/usr/local/bin", "/usr/bin", "/bin", "/usr/sbin", "/sbin"])


def systemd_unit(root, python, home_dir, allow_reboot):
    env = [f"PYTHONPATH={root}", f"HL_HOME={home_dir}"] + (["HL_AGENT_REBOOT=1"] if allow_reboot else [])
    return ("[Unit]\nDescription=Host helper for the assistant (restart apps, update)\nAfter=docker.service\n\n[Service]\n"
            + "".join(f"Environment={e}\n" for e in env)
            + f"ExecStart={python} -W ignore -m core.cli agent run\nWorkingDirectory={root}\nRestart=always\nRestartSec=5\n\n[Install]\nWantedBy=default.target\n")


def launchd_plist(root, python, home, home_dir, allow_reboot):
    env = {"PYTHONPATH": root, "HL_HOME": home_dir, "PATH": path_for_service(home)}
    if allow_reboot:
        env["HL_AGENT_REBOOT"] = "1"
    items = "".join(f"    <key>{k}</key><string>{v}</string>\n" for k, v in env.items())
    log = os.path.join(home_dir, "agent.log")
    return ('<?xml version="1.0" encoding="UTF-8"?>\n<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">\n<plist version="1.0"><dict>\n'
            f"  <key>Label</key><string>{LABEL}</string>\n  <key>ProgramArguments</key><array><string>{python}</string><string>-W</string><string>ignore</string>"
            f"<string>-m</string><string>core.cli</string><string>agent</string><string>run</string></array>\n  <key>WorkingDirectory</key><string>{root}</string>\n"
            f"  <key>EnvironmentVariables</key><dict>\n{items}  </dict>\n  <key>RunAtLoad</key><true/>\n  <key>KeepAlive</key><true/>\n"
            f"  <key>StandardOutPath</key><string>{log}</string>\n  <key>StandardErrorPath</key><string>{log}</string>\n</dict></plist>\n")


def unit_path(platform, home):
    if platform == "mac":
        return os.path.join(home, "Library", "LaunchAgents", LABEL + ".plist")
    return os.path.join(home, ".config", "systemd", "user", UNIT)


def install(root, home_dir, platform, home, run=shell, python=None, allow_reboot=False, out=print, uid=None):
    """Writes the service file and starts it. Returns True on success. Changes nothing outside the user's own folders."""
    python = python or sys.executable
    path = unit_path(platform, home)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    os.makedirs(home_dir, exist_ok=True)
    if platform == "mac":
        text = launchd_plist(root, python, home, home_dir, allow_reboot)
    elif platform in ("linux",):
        text = systemd_unit(root, python, home_dir, allow_reboot)
    else:
        out("  stop  The host helper runs on Linux (systemd) and macOS today.")
        return False
    with open(path, "w") as f:
        f.write(text)
    uid = os.getuid() if uid is None else uid
    steps = ([["launchctl", "bootout", f"gui/{uid}/{LABEL}"], ["launchctl", "bootstrap", f"gui/{uid}", path]] if platform == "mac"
             else [["systemctl", "--user", "daemon-reload"], ["systemctl", "--user", "enable", "--now", UNIT]])
    for i, cmd in enumerate(steps):
        rc, msg = run(cmd)
        if rc != 0 and not (platform == "mac" and i == 0):  # bootout fails harmlessly when it was not loaded yet
            out(f"  stop  `{' '.join(cmd)}` failed: {msg or 'no message'}")
            out(f"        The service file is at {path}. Fix the problem above, then run: homelab agent install")
            return False
    out(f"  ok    Host helper installed ({path}).")
    if platform == "linux":
        out("        To keep it running when you are logged out: sudo loginctl enable-linger $USER")
    return True


def uninstall(platform, home, run=shell, out=print, uid=None):
    path = unit_path(platform, home)
    if not os.path.exists(path):
        out("  ok    The host helper was not installed.")
        return True
    uid = os.getuid() if uid is None else uid
    run(["launchctl", "bootout", f"gui/{uid}/{LABEL}"] if platform == "mac" else ["systemctl", "--user", "disable", "--now", UNIT])
    os.remove(path)
    if platform == "linux":
        run(["systemctl", "--user", "daemon-reload"])
    out("  ok    Host helper removed.")
    return True
