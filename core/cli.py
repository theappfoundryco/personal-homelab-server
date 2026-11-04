"""The command line: homelab status | start | stop | restart | logs | doctor | modules | config | backup | restore | update | uninstall.
Everything outside this process (git, docker, the dashboard's address, the keyboard) goes through Ctx, so tests can pretend."""
import argparse
import datetime as _datetime  # not `datetime`: the test harness swaps that name to freeze the clock
import io
import json
import os
import re
import shutil
import subprocess
import sys
import tarfile
import time as _time
import urllib.request

from core import apps as _apps
from core import custom as _custom

NAME = "homelab"
BRANCH = "origin/main"
KEEP = {"snapshot": 5, "before-restore": 3}  # automatic backups older than this many are removed
HEALTH_WAIT, HEALTH_EVERY = 60, 3  # seconds


def shell(cmd, cwd=None, stream=False, env=None):
    """Runs a command. Returns (exit code, output). stream=True lets it talk to the screen and keyboard."""
    e = {**os.environ, **env} if env else None
    try:
        if stream:
            return subprocess.run(cmd, cwd=cwd, env=e).returncode, ""
        r = subprocess.run(cmd, cwd=cwd, env=e, capture_output=True, text=True)
        return r.returncode, (r.stdout + r.stderr).strip()
    except FileNotFoundError:
        return 127, f"{cmd[0]} is not installed"


def read_env(path):
    out = {}
    try:
        with open(path) as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, v = line.split("=", 1)
                    out[k.strip()] = v.strip().strip("\"'")
    except OSError:
        pass
    return out


def when(d):
    return f"{d:%b} {d.day}, {d.year} {d.hour % 12 or 12}:{d:%M} {'AM' if d.hour < 12 else 'PM'}"


class Ctx:
    def __init__(self, root, env=None, **over):
        self.root, self.env = root, dict(os.environ if env is None else env)
        self.stack = os.path.join(root, "stack")
        self.home = self.env.get("HL_HOME") or os.path.join(os.path.expanduser("~"), ".homelab")
        dotenv = read_env(os.path.join(self.stack, ".env"))
        self.data = dotenv.get("HL_DATA_DIR") or os.path.join(self.home, "data")
        self.stats = dotenv.get("HL_STATS_DIR") or os.path.join(self.home, "stats")
        self.port = dotenv.get("HL_PORT") or self.env.get("HL_PORT") or "3095"
        self.backups = os.path.join(self.home, "backups")
        self.out = print
        self.run = shell
        self.which = shutil.which
        self.now = _datetime.datetime.now
        self.sleep = _time.sleep
        self.python = sys.executable
        self.user_home = os.path.expanduser("~")
        self.platform = "mac" if sys.platform == "darwin" else "linux"
        self.yes = False
        self.health_wait = HEALTH_WAIT
        self.prompt = lambda q: input(q) if sys.stdin.isatty() else ""
        self.probe = self._probe
        self.__dict__.update(over)

    def _probe(self):
        """The dashboard's health check as a dict, or None if nothing answers."""
        try:
            with urllib.request.urlopen(f"http://localhost:{self.port}/api/bot/doctor", timeout=5) as r:
                return json.load(r)
        except Exception:
            return None

    def ask(self, question):
        if self.yes:
            return True
        return self.prompt(f"  {question} [y/N] ").strip().lower() in ("y", "yes")

    def compose(self, *args, stream=False):
        return self.run(["docker", "compose", *args], cwd=self.stack, stream=stream)

    def git(self, *args):
        return self.run(["git", *args], cwd=self.root)

    def docker_ready(self):
        if not self.which("docker"):
            self.out("  stop  Docker is not installed. Run ./install.sh first.")
            return False
        return True

    def running(self):
        rc, text = self.run(["docker", "ps", "--format", "{{.Names}}"])
        return rc == 0 and "telegram-bot" in text.split()

    def version(self):
        rc, text = self.git("describe", "--tags", "--always")
        return text if rc == 0 and text else "unknown"


def services(c):
    """What start, stop and update touch: the core plus the apps this install chose (apps.json in the data folder)."""
    return _apps.services(_apps.chosen(c.data), _apps.native(c.data))


# ---- running it

def status(c):
    c.out(f"{NAME} {c.version()}   data: {c.data}")
    if not c.docker_ready():
        return 1
    rc, text = c.compose("ps", "-a", "--format", "{{.Service}}|{{.State}}")
    states = dict(l.split("|", 1) for l in text.splitlines() if "|" in l) if rc == 0 else {}
    for s in services(c):
        c.out(f"  {s}: {states.get(s, 'not created')}")
    rep = c.probe()
    if rep is None:
        c.out(f"  The dashboard is not answering on port {c.port}. Start it with: {NAME} start")
        return 1
    counts = {}
    for m in rep.get("modules", []):
        counts[m["state"]] = counts.get(m["state"], 0) + 1
    c.out("  Health: " + ("all fine" if rep.get("ok") else "something is broken") + "   " + ", ".join(f"{n} {k}" for k, n in sorted(counts.items())))
    c.out(f"  For the full list: {NAME} doctor")
    return 0 if rep.get("ok") else 1


def start(c):
    if not c.docker_ready():
        return 1
    return c.compose("up", "-d", "--build", *services(c), stream=True)[0]


def stop(c):
    if not c.docker_ready():
        return 1
    return c.compose("stop", *services(c), stream=True)[0]


def restart(c):
    if not c.docker_ready():
        return 1
    return c.compose("restart", *services(c), stream=True)[0]


def logs(c, service=None, follow=False):
    if not c.docker_ready():
        return 1
    return c.compose("logs", "--tail", "100", *(["-f"] if follow else []), service or "telegram-bot", stream=True)[0]


def doctor(c):
    if not c.docker_ready():
        return 1
    if not c.running():
        c.out(f"  stop  The assistant is not running. Start it with: {NAME} start")
        return 1
    return c.compose("exec", "-T", "telegram-bot", "python", "-m", "core", "doctor", stream=True)[0]


def _settings(c):
    from core import config, registry, settings
    base = config.load(os.path.join(c.stack, "config.yaml"), log=lambda m: None)
    return registry, settings.Settings(c.data, base, log=lambda m: None)


def custom_compose(c, app_id, *args, stream=False):
    """docker compose for one of your own apps: its own project and file, with stack/.env for the access setting and time zone."""
    env = os.path.join(c.stack, ".env")
    return c.run(["docker", "compose", "-p", _custom.project(app_id), "-f", _custom.compose_path(c.data, app_id),
                  *(["--env-file", env] if os.path.exists(env) else []), *args], cwd=c.stack, stream=stream)


def _port_free(port):
    import socket
    with socket.socket() as s:
        try:
            s.bind(("127.0.0.1", int(port)))
            return True
        except OSError:
            return False


def custom_cmd(c, args, inside=None, keep=None, group="apps"):
    """homelab apps custom add <name> <image> <port> | remove <name> | list"""
    sub, rest = (args[0], list(args[1:])) if args else ("list", [])
    if sub == "list":
        mine = _custom.load(c.data)
        for a in mine:
            c.out(f"    {a['id']:<16} {a['image']}  port {a['port']}" + (f"  keeps {a['keep']}" if a.get("keep") else ""))
        c.out("  None yet." if not mine else f"  {len(mine)} of your own.")
        c.out(f"  Add one with: {NAME} apps custom add <name> <image:version> <port> [--inside PORT] [--keep /folder] [--tools]")
        return 0
    if sub == "remove":
        return apps_cmd(c, "remove", rest) if rest else (c.out(f"  stop  Say which: {NAME} apps custom remove <name>") or 2)
    if sub != "add" or len(rest) != 3:
        c.out(f"  stop  Use: {NAME} apps custom add <name> <image:version> <port>, {NAME} apps custom remove <name>, or {NAME} apps custom list")
        return 2
    app, why = _custom.check(c.data, {"title": rest[0], "image": rest[1], "port": rest[2], "inside": inside, "keep": keep, "group": group})
    if why:
        c.out(f"  stop  {why}")
        return 2
    if not _port_free(app["port"]):
        c.out(f"  stop  Port {app['port']} is already used on this machine. Pick another.")
        return 2
    _custom.add(c.data, app)
    return apps_cmd(c, "add", [app["id"]])


def apps_cmd(c, action="list", names=()):
    """List the optional apps, or add or remove some. Adding starts them now; removing stops and deletes their containers (their data volumes stay).
    Your own apps (core/custom.py) work the same way, except that removing one also forgets it."""
    ids = _apps.chosen(c.data)
    if action == "list":
        group = None
        for a in _apps.view(ids):
            if a["group"] != group:
                group = a["group"]
                c.out(f"  {group}")
            c.out(f"    {'on ' if a['chosen'] else 'off'}  {a['id']:<12} {a['title']}, about {a['memory_mb']} MB")
        mine = _custom.load(c.data)
        if mine:
            c.out("  Your apps")
            for a in mine:
                c.out(f"    on   {a['id']:<12} {a['title']}, {a['image']}, port {a['port']}")
        c.out(f"  Add one with: {NAME} apps add <name>   Remove with: {NAME} apps remove <name>   Your own: {NAME} apps custom")
        return 0
    mine = _custom.ids(c.data)
    bad = [n for n in names if n not in _apps.CATALOG and n not in mine]
    if bad:
        c.out(f"  stop  Unknown app: {', '.join(bad)}. See the list with: {NAME} apps")
        return 2
    if not c.docker_ready():
        return 1
    own, names = [n for n in names if n in mine], [n for n in names if n not in mine]
    rc = 0
    for n in own:
        if action == "add":
            app = _custom.get(c.data, n)
            _custom.write(c.data, app)
            r = custom_compose(c, n, "up", "-d", stream=True)[0]
            c.out(f"  ok    {app['title']} started on port {app['port']}" if r == 0 else f"  stop  {app['title']} did not start. See why with: docker logs {n}")
        else:
            r = custom_compose(c, n, "down", stream=True)[0] if os.path.exists(_custom.compose_path(c.data, n)) else 0
            if r == 0:
                _custom.forget(c.data, n)
                c.out(f"  ok    Removed {n}." + (f" Its data is kept in the Docker volume {_custom.volume(n)}." if c.run(["docker", "volume", "inspect", _custom.volume(n)])[0] == 0 else ""))
            else:
                c.out(f"  stop  Docker could not remove {n}.")
        rc = rc or r
    if not names:
        return rc
    if action == "add":
        added = [n for n in _apps.with_needs(ids + list(names)) if n not in ids]
        if not added:
            c.out("  ok    Already installed.")
            return 0
        native = _apps.native(c.data)
        if "ollama" in added and c.platform == "mac" and c.env.get("HL_OLLAMA_DOCKER") != "1":
            if ollama_on_mac(c):
                native = sorted(set(native) | {"ollama"})
            else:
                c.out("  warn  Using the AI engine in Docker instead (slower on a Mac: no Apple GPU there).")
        _apps.save(c.data, ids + list(names), native)
        docker_side = [s for n in added if n not in native for s in _apps.CATALOG[n][2]]
        rc = c.compose("up", "-d", *docker_side, stream=True)[0] if docker_side else 0
        titles = ", ".join(_apps.CATALOG[n][0] for n in added)
        c.out(f"  ok    {titles} started" if rc == 0 else f"  stop  {titles} did not start. See why with: {NAME} logs <service>")
        return rc
    users = [u for n in names for u in _apps.needed_by(n, ids) if u not in names]
    if users:
        c.out(f"  stop  {', '.join(_apps.CATALOG[u][0] for u in users)} needs it. Remove that first, or both together.")
        return 1
    native = _apps.native(c.data)
    if "ollama" in names and "ollama" in native:
        c.run(["brew", "services", "stop", "ollama"])
        c.out("  ok    The AI engine on this Mac is stopped. Its models stay; delete Ollama fully with: brew uninstall ollama")
    gone = [s for n in names if n in ids and n not in native for s in _apps.CATALOG[n][2]]
    _apps.save(c.data, [i for i in ids if i not in names], [n for n in native if n not in names])
    rc = c.compose("rm", "-s", "-f", *gone, stream=True)[0] if gone else 0
    c.out(f"  {'ok' if rc == 0 else 'stop'}    {'Removed. Its data is kept, so adding it again picks up where it was.' if gone else 'It was not installed.'}")
    return rc


def ollama_on_mac(c):
    """Installs Ollama with Homebrew and runs it on the Mac itself, where it uses the Apple GPU (in Docker it only gets the CPU).
    The assistant then reaches it at host.docker.internal. Returns True when it answers."""
    if not c.which("brew"):
        c.out("  warn  Homebrew is not installed, so the AI engine can't run on the Mac itself.")
        return False
    if not c.which("ollama"):
        c.out("  Installing Ollama with Homebrew (about 100 MB)...")
        if c.run(["brew", "install", "ollama"], stream=True)[0] != 0:
            return False
        from core import manifest
        manifest.add(c.home, "brew", "ollama")  # so uninstall and reset remove only an Ollama this program put there
    c.run(["brew", "services", "start", "ollama"])  # starts now and at every login
    for _ in range(30):
        try:
            with urllib.request.urlopen("http://127.0.0.1:11434/api/tags", timeout=2):
                break
        except Exception:
            c.sleep(2)
    else:
        c.out("  warn  Ollama was installed but is not answering yet. Try: brew services restart ollama")
        return False
    from core import config, settings
    settings.Settings(c.data, config.Config({}), log=lambda m: None).set({"ollama.url": _apps.NATIVE_URL})
    set_env(c, "HL_OLLAMA_URL", _apps.NATIVE_URL)  # for AI chat (Open WebUI)
    c.out("  ok    The AI engine runs on this Mac and uses its GPU. The assistant uses it after its next restart.")
    return True


def set_env(c, key, value):
    """One line in stack/.env, replaced if it is there."""
    p = os.path.join(c.stack, ".env")
    try:
        with open(p) as f:
            lines = [l for l in f.read().splitlines() if not l.startswith(key + "=")]
    except OSError:
        lines = []
    with open(p, "w") as f:
        f.write("\n".join(lines + [f"{key}={value}"]) + "\n")
    os.chmod(p, 0o600)


def lan_ip(c):
    """This machine's address on the home network, or "" if it cannot be told."""
    for cmd in (["hostname", "-I"], ["ipconfig", "getifaddr", "en0"], ["ipconfig", "getifaddr", "en1"]):
        rc, text = c.run(cmd)
        if rc == 0 and text.split():
            return text.split()[0]
    return ""


def access(c, mode):
    """Who can open the dashboard: lan (your home network; needs the settings PIN) or local (this machine only). Restarts only the dashboard."""
    if mode == "lan":
        try:
            with open(os.path.join(c.data, "settings.json")) as f:
                has_pin = bool(json.load(f).get("_pin"))
        except (OSError, ValueError, AttributeError):
            has_pin = False
        if not has_pin:
            c.out("  stop  Set a PIN first (Settings, Security, or the setup wizard), because the dashboard holds your journal and budget.")
            return 1
    if not c.docker_ready():
        return 1
    path = os.path.join(c.stack, ".env")
    try:
        lines = [l for l in open(path).read().splitlines() if not l.startswith("HL_BIND=")]
    except OSError:
        c.out("  stop  There is no .env yet. Run ./install.sh first.")
        return 1
    bind = "0.0.0.0" if mode == "lan" else "127.0.0.1"
    with open(path + ".new", "w") as f:
        f.write("\n".join(lines + [f"HL_BIND={bind}"]) + "\n")
    os.chmod(path + ".new", 0o600)
    os.replace(path + ".new", path)
    ip = lan_ip(c) if mode == "lan" else ""
    try:
        with open(os.path.join(c.data, "access.json"), "w") as f:
            json.dump({"mode": mode, "url": f"http://{ip}:{c.port}" if ip else ""}, f)
    except OSError:
        pass
    rc = c.compose("up", "-d", "landing", stream=True)[0]
    for n in _custom.ids(c.data):  # your own apps follow the same setting
        if os.path.exists(_custom.compose_path(c.data, n)):
            custom_compose(c, n, "up", "-d", stream=True)
    if rc == 0:
        c.out(f"  ok    {'Open it from your phone at http://' + ip + ':' + c.port if ip else 'Open on your home network' if mode == 'lan' else 'Only this machine can open it now'}")
    return rc


def modules(c, action="list", name=None):
    registry, st = _settings(c)
    mods = registry.discover(os.path.join(c.root, "modules"), log=lambda m: None)
    mods = {k: v for k, v in mods.items() if not k.startswith("_")}
    if action == "list":
        switches = st.merged().get("modules") or {}
        plat = registry.this_platform()
        for k in sorted(mods):
            m = mods[k]
            on = bool(switches.get(k, m.default))
            note = f"   (needs {' or '.join(m.platforms)}, this machine is {plat})" if plat not in m.platforms else ""
            c.out(f"  {'on ' if on else 'off'}  {k:<12} {m.title}{note}")
        c.out(f"\n  Change one with: {NAME} modules enable|disable <name>")
        return 0
    if name not in mods:
        c.out(f"  stop  There is no module called {name!r}. See them with: {NAME} modules list")
        return 1
    try:
        ok, problems = st.set({f"modules.{name}": action == "enable"})
    except OSError as e:
        c.out(f"  stop  Could not save to {st.path} ({e}). Change it in the dashboard (Settings), or fix the folder's owner.")
        return 1
    if not ok:
        c.out("  stop  " + " ".join(problems))
        return 1
    c.out(f"  ok    {name} is now {'on' if action == 'enable' else 'off'}")
    if c.which("docker") and c.running():
        c.out("  Restarting so it takes effect.")
        return c.compose("restart", "telegram-bot")[0]
    c.out("  It takes effect the next time the assistant starts.")
    return 0


def config_edit(c):
    from core import config
    path = os.path.join(c.stack, "config.yaml")
    if not os.path.isfile(path):
        shutil.copy(os.path.join(c.stack, "config.example.yaml"), path)
    editor = c.env.get("VISUAL") or c.env.get("EDITOR") or next((e for e in ("nano", "vi") if c.which(e)), None)
    if not editor:
        c.out(f"  stop  No text editor found. Open {path} in any editor, then check it with: {NAME} config check")
        return 1
    before = open(path).read()
    c.run([editor, path], stream=True)
    return _check_config(c, path, before)


def _check_config(c, path, before):
    from core import config
    msgs = []
    cfg = config.load(path, log=msgs.append)
    problems = msgs + [p for p in cfg.problems if p != "unreadable"]
    now = open(path).read()
    if problems:
        c.out("  warn  config.yaml has problems:")
        for p in problems:
            c.out(f"        {p}")
        if not c.ask("Keep it anyway?"):
            with open(path, "w") as f:
                f.write(before)
            c.out("  ok    Put the previous version back.")
            return 1
        return 0
    if now == before:
        c.out("  ok    No changes.")
        return 0
    c.out("  ok    config.yaml looks good.")
    if c.which("docker") and c.running() and c.ask("Restart now so it takes effect?"):
        return c.compose("restart", "telegram-bot")[0]
    return 0


# ---- backup and restore

PARTS = (("data", "data"), ("stack/config.yaml", "config.yaml"), ("stack/.env", ".env"), ("stack/secrets", "secrets"))


def make_backup(c, prefix="backup", dest=None, keep=None):
    """A dated .tar.gz of the data folder, config.yaml, .env and secrets. Returns its path, or None with a message."""
    dest = dest or c.backups
    stamp = c.now()
    os.makedirs(dest, exist_ok=True)
    path = os.path.join(dest, f"{prefix}-{stamp:%Y%m%d-%H%M%S}.tar.gz")
    n = 1
    while os.path.exists(path):
        n += 1
        path = os.path.join(dest, f"{prefix}-{stamp:%Y%m%d-%H%M%S}-{n}.tar.gz")
    sources = {"data": c.data, "stack/config.yaml": os.path.join(c.stack, "config.yaml"), "stack/.env": os.path.join(c.stack, ".env"), "stack/secrets": os.path.join(c.stack, "secrets")}
    meta = json.dumps({"format": 1, "created": stamp.isoformat(timespec="seconds"), "version": c.version(), "data_dir": c.data}).encode()
    tmp = path + ".part"
    try:
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "wb") as raw, tarfile.open(fileobj=raw, mode="w:gz") as tar:
            info = tarfile.TarInfo("meta.json")
            info.size, info.mtime = len(meta), int(stamp.timestamp())
            tar.addfile(info, io.BytesIO(meta))
            for arc, src in sources.items():
                if os.path.exists(src):
                    tar.add(src, arcname=arc)
        os.replace(tmp, path)
    except OSError as e:
        if os.path.exists(tmp):
            os.remove(tmp)
        c.out(f"  stop  Could not make the backup ({e}). If a file belongs to another user, try again with sudo.")
        return None
    prune(c, prefix, dest, keep)
    return path


def prune(c, prefix, dest, keep=None):
    keep = keep or KEEP.get(prefix)
    if not keep:
        return
    old = sorted(f for f in os.listdir(dest) if f.startswith(prefix + "-") and f.endswith(".tar.gz"))[:-keep]
    for f in old:
        os.remove(os.path.join(dest, f))


def _safe(tar):
    """The archive's meta, or None if it is not one of ours or tries to write outside the folders it should."""
    try:
        names = tar.getnames()
        if "meta.json" not in names:
            return None
        for m in tar.getmembers():
            n = m.name
            top = n.split("/")[0]
            ok_top = n == "meta.json" or top == "data" or n in ("stack/config.yaml", "stack/.env") or n == "stack/secrets" or n.startswith("stack/secrets/")
            if n.startswith("/") or ".." in n.split("/") or not (m.isfile() or m.isdir()) or not ok_top:
                return None
        return json.load(tar.extractfile("meta.json"))
    except (tarfile.TarError, OSError, ValueError, KeyError):
        return None


def _extract(tar, arc, dest):
    """Writes the archive's arc (a file or a folder) to dest, replacing what was there."""
    members = [m for m in tar.getmembers() if m.name == arc or m.name.startswith(arc + "/")]
    if not members:
        return
    if os.path.isdir(dest) and not os.path.islink(dest):
        shutil.rmtree(dest)
    elif os.path.lexists(dest):
        os.remove(dest)
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    for m in members:
        target = os.path.join(dest, os.path.relpath(m.name, arc)) if m.name != arc else dest
        if m.isdir():
            os.makedirs(target, exist_ok=True)
            continue
        os.makedirs(os.path.dirname(target), exist_ok=True)
        with tar.extractfile(m) as src, open(target, "wb") as out:
            shutil.copyfileobj(src, out)
        os.chmod(target, m.mode & 0o777)
    if not os.path.exists(dest):
        os.makedirs(dest)


def apply_backup(c, path):
    with tarfile.open(path) as tar:
        _extract(tar, "data", c.data)
        _extract(tar, "stack/config.yaml", os.path.join(c.stack, "config.yaml"))
        _extract(tar, "stack/.env", os.path.join(c.stack, ".env"))
        _extract(tar, "stack/secrets", os.path.join(c.stack, "secrets"))


def backup(c, to=None, keep=None):
    """keep: also remove the oldest backups made this way in that folder, keeping this many (the nightly backup uses it)."""
    path = make_backup(c, prefix="nightly" if keep else "backup", dest=to, keep=keep)
    if not path:
        return 1
    c.out(f"  ok    Backup saved: {path} ({os.path.getsize(path) // 1024} KB)")
    c.out(f"        Bring it back with: {NAME} restore {path}")
    c.out("        It holds your passwords and journal: keep it somewhere private.")
    return 0


def settings_sync(c, repo):
    """Your settings in your own private git repository, so a new machine can start from them. Uses your git and SSH key, as you.
    Only config.yaml, the dashboard's settings (without the PIN) and the app list: never .env, keys, the journal or other data."""
    if not re.match(r"^(git@[\w.-]+:[\w./-]+|https://[\w.-]+/[\w./-]+|ssh://[\w@.:/-]+)$", repo or ""):
        c.out("  stop  That does not look like a git repository address, for example git@github.com:you/homelab-settings.git")
        return 2
    if not c.which("git"):
        c.out("  stop  git is not installed.")
        return 1
    work = os.path.join(c.home, "settings-repo")
    quiet = {"GIT_SSH_COMMAND": "ssh -o BatchMode=yes -o StrictHostKeyChecking=accept-new", "GIT_TERMINAL_PROMPT": "0"}  # never wait for a question nobody sees
    if not os.path.isdir(os.path.join(work, ".git")):
        rc, text = c.run(["git", "clone", "-q", repo, work], env=quiet)
        if rc != 0:
            c.out(f"  stop  Could not reach the repository: {text.strip().splitlines()[-1] if text.strip() else 'no answer'}. "
                  "Check the address, that it is private, and that this machine's SSH key is added to it (on GitHub: the repository, Settings, Deploy keys, with write access).")
            return 1
    files = {"config.yaml": os.path.join(c.stack, "config.yaml"), "apps.json": os.path.join(c.data, "apps.json")}
    for name, src in files.items():
        if os.path.isfile(src):
            shutil.copy(src, os.path.join(work, name))
    try:
        with open(os.path.join(c.data, "settings.json")) as f:
            st = json.load(f)
        st.pop("_pin", None)
        with open(os.path.join(work, "settings.json"), "w") as f:
            json.dump(st, f, indent=1, sort_keys=True)
    except (OSError, ValueError):
        pass
    c.run(["git", "-C", work, "add", "-A"])
    if c.run(["git", "-C", work, "diff", "--cached", "--quiet"])[0] == 0:
        c.out("  ok    Settings unchanged since the last copy.")
        return 0
    rc, text = c.run(["git", "-C", work, "-c", "user.name=homelab", "-c", "user.email=homelab@localhost", "commit", "-q", "-m", f"Settings on {c.now():%Y-%m-%d}"])
    if rc == 0:
        rc, text = c.run(["git", "-C", work, "push", "-q", "origin", "HEAD"], env=quiet)
    c.out("  ok    Settings copied to your repository." if rc == 0 else f"  stop  The copy did not go up: {text.strip().splitlines()[-1] if text.strip() else 'no answer'}")
    return rc


def restore(c, path):
    if not os.path.isfile(path):
        c.out(f"  stop  There is no file at {path}.")
        return 1
    try:
        with tarfile.open(path) as tar:
            meta = _safe(tar)
    except (tarfile.TarError, OSError):
        meta = None
    if not meta:
        c.out("  stop  That is not a backup made by this tool (or it is damaged). Nothing was changed.")
        return 1
    made = _datetime.datetime.fromisoformat(meta["created"])
    c.out(f"  Backup from {when(made)}, version {meta.get('version', 'unknown')}.")
    c.out(f"  It will replace: your data folder ({c.data}), config.yaml, .env and the secrets folder.")
    if not c.ask("Replace what is there now? A safety copy is made first."):
        c.out("  Cancelled. Nothing was changed. (Add --yes to skip this question.)")
        return 1
    was_up = c.which("docker") and c.running()
    if was_up:
        c.compose("stop", *services(c))
    safety = make_backup(c, "before-restore")
    if not safety:
        return 1
    c.out(f"  ok    Safety copy of the current state: {safety}")
    try:
        apply_backup(c, path)
    except OSError as e:
        c.out(f"  stop  Restoring failed part way ({e}). Your previous state is in {safety}; restore that to undo.")
        return 1
    c.out("  ok    Restored.")
    if was_up:
        return c.compose("up", "-d", "--build", *services(c), stream=True)[0]
    return 0


# ---- update

def release_tag(c):
    rc, text = c.git("tag", "-l", "v[0-9]*", "--sort=-v:refname")
    tags = [t for t in text.splitlines() if "-" not in t] if rc == 0 else []  # a dash marks a pre-release (v1.0.0-rc1)
    return tags[0] if tags else None


def channel_file(c):
    return os.path.join(c.home, "channel")


def read_channel(c):
    try:
        v = open(channel_file(c)).read().strip()
    except OSError:
        return "stable"
    return v if v in ("stable", "edge") else "stable"


def wait_healthy(c, must_be_ok):
    for i in range(max(1, c.health_wait // HEALTH_EVERY)):
        rep = c.probe()
        if rep is not None and (rep.get("ok") or not must_be_ok):
            return True
        if i + 1 < max(1, c.health_wait // HEALTH_EVERY):
            c.sleep(HEALTH_EVERY)
    return False


def rollback(c, old, snapshot, must_be_ok):
    c.out("  warn  Going back to the version you had.")
    c.compose("stop", *services(c))
    c.git("reset", "--hard", old)
    try:
        apply_backup(c, snapshot)
        c.out("  ok    Your data is back as it was before the update.")
    except OSError as e:
        c.out(f"  stop  Could not put the data back ({e}). The snapshot is {snapshot}: {NAME} restore {snapshot}")
    c.compose("up", "-d", "--build", *services(c), stream=True)
    if wait_healthy(c, must_be_ok):
        c.out(f"  ok    The old version is running again ({c.version()}). Nothing was lost.")
    else:
        c.out(f"  stop  The old version did not come back either. See why with: {NAME} logs")


def update(c, check=False, dry=False, channel=None):
    ch = channel or read_channel(c)
    if not c.which("git") or not os.path.isdir(os.path.join(c.root, ".git")):
        c.out("  stop  This copy was not installed with git, so it cannot update itself. Clone the project again, or download the newest version.")
        return 1
    rc, text = c.git("status", "--porcelain", "--untracked-files=no")
    if text:
        c.out("  stop  You have changed files in the program folder, so an update could overwrite them:")
        for l in text.splitlines()[:8]:
            c.out(f"        {l}")
        c.out("        Put them aside (git stash) and run this again. Your settings and data are elsewhere and are not affected.")
        return 1
    c.out(f"  Checking for updates ({ch} channel)")
    if c.git("fetch", "--tags", "--quiet", "origin")[0] != 0:
        c.out("  stop  Could not reach the project's server. Check your internet connection and try again.")
        return 1
    if ch == "edge":
        ref = BRANCH
    else:
        ref = release_tag(c)
        if not ref:
            c.out("  stop  There is no stable release yet. To follow the newest work instead: " + f"{NAME} update --channel edge")
            return 1
    rc, target = c.git("rev-parse", f"{ref}^{{commit}}")
    rc2, head = c.git("rev-parse", "HEAD")
    if rc or rc2:
        c.out("  stop  Could not read the version history. Try: git fetch --tags")
        return 1
    if target == head:
        c.out(f"  ok    Already up to date ({c.version()}).")
        return 0
    if c.git("merge-base", "--is-ancestor", head, target)[0] != 0:
        c.out(f"  stop  This copy is ahead of or different from {ref}, so it cannot move forward on its own. Nothing was changed.")
        return 1
    rc, news = c.git("log", "--oneline", "-n", "10", f"{head}..{target}")
    c.out(f"  Update available: {c.version()} to {ref}")
    for l in news.splitlines():
        c.out(f"        {l}")
    if check:
        return 0
    if dry:
        c.out("  Dry run. It would: take a snapshot, stop the assistant, move to the new version, update saved data, restart, check health, and go back on any failure. Nothing was changed.")
        return 0
    if not c.docker_ready():
        return 1
    if not c.ask("Update now?"):
        c.out("  Cancelled. (Add --yes to skip this question.)")
        return 1
    if channel:
        os.makedirs(c.home, exist_ok=True)
        open(channel_file(c), "w").write(ch + "\n")
    was_up = c.running()
    before = c.probe()
    must_be_ok = bool(before and before.get("ok"))
    snapshot = make_backup(c, "snapshot")
    if not snapshot:
        return 1
    c.out(f"  ok    Snapshot: {snapshot}")
    c.compose("stop", *services(c))
    if c.git("merge", "--ff-only", target)[0] != 0:
        c.out("  stop  Could not move to the new version. Starting the old one again.")
        c.compose("up", "-d", "--build", *services(c), stream=True)
        return 1
    rc, out = c.run([c.python, "-W", "ignore", "-m", "core", "migrate", c.data], cwd=c.root, env={"PYTHONPATH": c.root})
    if rc != 0:
        c.out(f"  stop  Updating your saved data failed: {out.splitlines()[-1] if out else 'unknown error'}")
        rollback(c, head, snapshot, must_be_ok)
        return 1
    c.out("  ok    Data is up to date. Starting the new version.")
    if c.compose("up", "-d", "--build", *services(c), stream=True)[0] != 0:
        c.out("  stop  The new version would not start.")
        rollback(c, head, snapshot, must_be_ok)
        return 1
    if not wait_healthy(c, must_be_ok):
        c.out("  stop  The new version started but did not pass its health check.")
        rollback(c, head, snapshot, must_be_ok)
        return 1
    c.out(f"  ok    Updated to {c.version()}. The snapshot stays in {c.backups} in case you want to go back.")
    return 0


# ---- the host helper

def agent_cmd(c, action, allow_reboot=False):
    from core import agent
    if action == "run":
        agent.Agent(c.data, c.root, allow_reboot=allow_reboot or c.env.get("HL_AGENT_REBOOT") == "1", stats_dir=c.stats).serve()
        return 0
    if action == "install":
        return 0 if agent.install(c.root, c.home, c.platform, c.user_home, run=lambda cmd: c.run(cmd), python=c.python, allow_reboot=allow_reboot, out=c.out) else 1
    if action == "uninstall":
        return 0 if agent.uninstall(c.platform, c.user_home, run=lambda cmd: c.run(cmd), out=c.out) else 1
    up = agent.alive(c.data)
    c.out("  Host helper: " + ("running" if up else "not running") + f"   (service file: {agent.unit_path(c.platform, c.user_home)})")
    if not up:
        c.out(f"  Without it the Restart buttons and in-app updates do not work. Install it with: {NAME} agent install")
    return 0 if up else 1


# ---- uninstall

def autostart_cmd(c, action):
    from core import autostart
    kind = autostart.runtime(c.run)
    if action == "off":
        c.out("  ok    Docker no longer starts by itself." if autostart.off(c.user_home) else f"  ok    Nothing to turn off here{'' if kind == 'colima' else ' (this Docker has its own switch)'}.")
        return 0
    if action == "status":
        state, how = autostart.status(kind, c.user_home, c.run)
        c.out("  Starts by itself after a restart: " + {True: "yes", False: "no", None: "set in the Docker app"}[state] + f"   ({how})")
        return 0
    done, msg = autostart.on(kind, c.user_home)
    c.out(("  ok    " if done else "  warn  ") + msg)
    return 0 if done else 1


def _note_cli(c, cmd):
    """Tells the dashboard how to write commands for this person: homelab when it is on the PATH, else the full path."""
    try:
        os.makedirs(c.data, exist_ok=True)
        with open(os.path.join(c.data, "cli.txt"), "w") as f:
            f.write(cmd + "\n")
    except OSError:
        pass


def path_cmd(c, action, force=False):
    from core import shellpath
    full = os.path.join(c.root, "bin", NAME)
    if action == "remove":
        gone = shellpath.remove(c.root, c.user_home, NAME)
        _note_cli(c, full)
        c.out("  ok    Removed: " + ", ".join(gone) if gone else f"  ok    The {NAME} command was not added by this program. Nothing to remove.")
        return 0
    if action == "status":
        r = shellpath.check(c.root, c.user_home, NAME, platform=c.platform)
        c.out(f"  {r['state']}  " + {"ready": f"{NAME} works from any folder.", "needs_line": f"Linked, but new terminals do not look in ~/.local/bin yet. Run: {full} path add",
              "missing": f"Not added. Run: {full} path add", "stale": f"Points at a download that is gone ({r['detail']}). Run: {full} path add",
              "other": f"Points at another download ({r['detail']}). To point it here: {full} path add --force",
              "clash": f"Another program called {NAME} is at {r['detail']}."}[r["state"]])
        return 0 if r["state"] == "ready" else 1
    try:
        state, detail = shellpath.add(c.root, c.user_home, NAME, platform=c.platform, force=force)
    except OSError as e:
        c.out(f"  warn  Could not change {getattr(e, 'filename', None) or 'a file'} ({e.strerror or e}). Run these yourself, then open a new terminal:")
        for line in shellpath.manual(c.user_home, os.environ.get("SHELL", ""), c.platform, c.root, NAME):
            c.out("        " + line)
        return 1
    if state == "clash":
        c.out(f"  warn  Skipping: another program called {NAME} is at {detail}. Left it alone; use {full} instead.")
        return 1
    if state == "other":
        c.out(f"  warn  Skipping: {NAME} already points at another download ({detail}). To point it here: {full} path add --force")
        return 1
    _note_cli(c, NAME)
    src = f" (or now, after: source {detail.replace(c.user_home, '~', 1)})" if state == "added" and detail else ""
    c.out({"already": f"  ok    Skipping: {NAME} is already in your terminal.",
           "replaced": f"  ok    {NAME} pointed at an old download ({detail}); it runs this one now.",
           "added": f"  ok    Added. {NAME} works from any folder in a new terminal{src}."}[state])
    return 0


def _uninstall_plan(c, purge):
    """-> (remove, keep, brew, links): what uninstall takes off this machine, read from what is really there and what install recorded."""
    from core import agent, autostart, manifest, shellpath
    rec = manifest.load(c.home)
    native = "ollama" in _apps.native(c.data)
    rm, keep = ["The assistant's apps (containers) and their network"], []
    mine = _custom.ids(c.data)
    if mine:
        rm.append("Your own apps: " + ", ".join(mine) + (" (with their saved data and images)" if purge else " (their data is kept)"))
    if os.path.exists(agent.unit_path(c.platform, c.user_home)):
        rm.append("The host helper (the background service behind the dashboard's Restart and Update buttons)")
    if os.path.exists(autostart.plist_path(c.user_home)):
        rm.append("Docker starting by itself at login")
    if shellpath.check(c.root, c.user_home, NAME, platform=c.platform)["state"] in ("ready", "needs_line") and os.path.islink(os.path.join(c.user_home, ".local", "bin", NAME)):
        rm.append(f"The {NAME} command in your terminal (~/.local/bin/{NAME} and its PATH line)")
    brew, links = (manifest.brew(c.home), [v for k, v in rec if k == "plugin-link"]) if purge else ([], [])
    if native and "ollama" not in brew:
        rm.append("The AI engine is stopped (Ollama was already on this Mac, so it stays installed)")
    if purge:
        rm += [f"Your data: settings, journal, budget, chats ({c.data})", f"Live numbers ({c.stats})", "config.yaml, .env and the passwords in stack/secrets",
               "The apps' saved state (Docker volumes) and their downloaded images"]
        if brew:
            rm.append("Installed by this program with Homebrew: " + ", ".join(brew) + (" (and the Colima virtual machine)" if "colima" in brew else ""))
        if links:
            rm.append("Docker plugin links: " + ", ".join(l.replace(c.user_home, "~", 1) for l in links))
        keep.append(f"Backups in {c.backups}")
    else:
        keep += [f"Your data in {c.data} (homelab uninstall --purge deletes it)", "Downloaded app images and AI models", "Homebrew packages this program installed (--purge removes them)"]
    shared = [{"homebrew": "Homebrew", "docker-linux": "Docker"}[k] for k, _ in rec if k in manifest.SHARED]
    if shared:
        keep.append(" and ".join(shared) + ": other programs use it, so it stays")
    keep.append(f"This folder ({c.root}); delete it yourself when you are done")
    return rm, keep, brew, links


def _model_size(c, brew):
    """Where the AI models are and how big, or None. Only models this program can own: Docker's volume, or ~/.ollama with our Ollama."""
    where = []
    if c.run(["docker", "volume", "inspect", "homelab_ollama-data"])[0] == 0:
        where.append("docker")
    home = os.path.join(c.user_home, ".ollama")
    if "ollama" in brew and os.path.isdir(home):
        where.append("home")
    if not where:
        return None
    size = 0
    for d, _, files in os.walk(home) if "home" in where else ():
        for f in files:
            try:
                size += os.path.getsize(os.path.join(d, f))
            except OSError:
                pass
    return where, size


def uninstall(c, purge=False):
    if not c.docker_ready():
        return 1
    if purge:
        data = os.path.realpath(c.data)
        if data in ("/", os.path.realpath(os.path.expanduser("~"))) or len([p for p in data.split(os.sep) if p]) < 2:
            c.out(f"  stop  Refusing to delete {data}: it is not a folder just for this program.")
            return 1
    rm, keep, brew, links = _uninstall_plan(c, purge)
    c.out("  This will remove:")
    for line in rm:
        c.out(f"    - {line}")
    c.out("  Kept:")
    for line in keep:
        c.out(f"    - {line}")
    if purge:
        folder = os.path.basename(c.home.rstrip(os.sep)) or "data"
        word = folder.lstrip(".") or folder  # ".homelab" reads like punctuation next to "to confirm", so ask for "homelab" and take both
        if c.prompt(f"  This cannot be undone. To go ahead, type the word {word} and press Enter: ").strip() not in (word, folder):
            c.out("  Cancelled. Nothing was changed.")
            return 1
    elif not c.ask("Remove these?"):
        c.out("  Cancelled. Nothing was changed.")
        return 1
    drop_models = False
    if purge and (m := _model_size(c, brew)):
        gb = f" (about {m[1] / 1e9:.1f} GB)" if m[1] else ""
        drop_models = c.prompt(f"  Also delete the AI models{gb}? They take a while to download again. [y/N] ").strip().lower() in ("y", "yes")
    for n in _custom.ids(c.data):
        if os.path.exists(_custom.compose_path(c.data, n)):
            custom_compose(c, n, "down", *(["-v", "--rmi", "all"] if purge else []), stream=True)
    if purge and not drop_models and m and "docker" in m[0]:  # keep the models' volume, every other one goes
        rc = c.compose("down", "--rmi", "all", stream=True)[0]
        if rc == 0:
            vols = c.run(["docker", "volume", "ls", "-q", "--filter", "label=com.docker.compose.project=homelab"])[1].split()
            for v in vols:
                if not v.endswith("ollama-data"):
                    c.run(["docker", "volume", "rm", v])
    else:
        rc = c.compose("down", *(["-v", "--rmi", "all"] if purge else []), stream=True)[0]
    if rc != 0:
        c.out("  stop  Docker could not remove everything. Your data was not touched.")
        return 1
    from core import agent, autostart, manifest, shellpath
    if os.path.exists(agent.unit_path(c.platform, c.user_home)):  # the helper would otherwise keep running for nothing
        agent.uninstall(c.platform, c.user_home, run=lambda cmd: c.run(cmd), out=c.out)
    shellpath.remove(c.root, c.user_home, NAME)
    autostart.off(c.user_home)
    if "ollama" in _apps.native(c.data):  # the AI engine on the Mac itself is not a container, so Docker did not stop it
        c.run(["brew", "services", "stop", "ollama"])
    if purge:
        for p in (c.data, c.stats, os.path.join(c.stack, "secrets")):
            shutil.rmtree(p, ignore_errors=True)
        for f in ("config.yaml", ".env"):
            try:
                os.remove(os.path.join(c.stack, f))
            except OSError:
                pass
        if "colima" in brew and not (m and "docker" in m[0] and not drop_models):
            c.run(["colima", "delete", "-f"], stream=True)
        elif "colima" in brew:
            brew = [b for b in brew if b not in ("colima", "docker", "docker-compose", "docker-buildx")]
            c.out("  ok    Kept Colima and Docker, because the AI models you kept live inside it.")
        for name in brew:
            if c.which("brew") and c.run(["brew", "uninstall", name], stream=True)[0] == 0:
                manifest.drop(c.home, "brew", name)
        for link in links:
            if os.path.islink(link) and not os.path.exists(os.path.realpath(link)):
                os.remove(link)
                manifest.drop(c.home, "plugin-link", link)
        if drop_models and "ollama" in brew:
            shutil.rmtree(os.path.join(c.user_home, ".ollama"), ignore_errors=True)
        elif "ollama" in brew and os.path.isdir(os.path.join(c.user_home, ".ollama")):
            c.out("  ok    The AI models are kept in ~/.ollama. Delete that folder to free the space.")
        c.out("  ok    Deleted.")
    c.out(f"  ok    Removed. To remove the program too, delete the folder {c.root}." + ("" if purge else " To start again: ./install.sh"))
    return 0


# ---- command line

def parser():
    p = argparse.ArgumentParser(prog=NAME, description="Run and look after your assistant.")
    sub = p.add_subparsers(dest="cmd", metavar="command")
    for n, h in (("status", "what is running and how healthy it is"), ("start", "start the assistant"), ("stop", "stop it"), ("restart", "restart it"), ("doctor", "the full health check")):
        sub.add_parser(n, help=h)
    s = sub.add_parser("logs", help="show recent log lines")
    s.add_argument("service", nargs="?")
    s.add_argument("-f", "--follow", action="store_true")
    s = sub.add_parser("modules", help="list modules, or turn one on or off")
    s.add_argument("action", nargs="?", choices=("list", "enable", "disable"), default="list")
    s.add_argument("name", nargs="?")
    s = sub.add_parser("apps", help="list the optional apps, or add or remove them")
    s.add_argument("action", nargs="?", choices=("list", "add", "remove", "custom"), default="list")
    s.add_argument("names", nargs="*")
    s.add_argument("--inside", help="custom: the port the app listens on inside its container (default: the same port)")
    s.add_argument("--keep", help="custom: a folder inside the app to keep across restarts and updates, like /config")
    s.add_argument("--tools", action="store_true", help="custom: put its tile under Tools")
    s = sub.add_parser("access", help="who can open the dashboard: lan (home network, needs a PIN) or local")
    s.add_argument("mode", choices=("lan", "local"))
    s = sub.add_parser("config", help="edit config.yaml safely")
    s.add_argument("action", choices=("edit", "check"))
    s = sub.add_parser("backup", help="save your data and settings to one file")
    s.add_argument("--to", help="folder to save into (default: ~/.homelab/backups)")
    s.add_argument("--keep", type=int, help="keep only this many of these backups in that folder (the nightly backup uses it)")
    s = sub.add_parser("settings-sync", help="copy your settings (never your journal, passwords or PIN) to your own private git repository")
    s.add_argument("repo", help="the repository address, for example git@github.com:you/homelab-settings.git")
    s = sub.add_parser("restore", help="bring a backup back")
    s.add_argument("file")
    s.add_argument("--yes", action="store_true")
    s = sub.add_parser("update", help="move to the newest version, with a snapshot and automatic undo")
    s.add_argument("--check", action="store_true", help="only say whether there is something new")
    s.add_argument("--dry-run", action="store_true")
    s.add_argument("--channel", choices=("stable", "edge"), help="stable = tagged releases (default), edge = newest work")
    s.add_argument("--yes", action="store_true")
    s = sub.add_parser("agent", help="the background helper that restarts apps and updates (install, uninstall, status)")
    s.add_argument("action", choices=("install", "uninstall", "status", "run"))
    s.add_argument("--allow-reboot", action="store_true", help="let the assistant reboot this machine too (off by default)")
    s = sub.add_parser("autostart", help="start Docker, and so the assistant, by itself after a restart (on, off, status)")
    s.add_argument("action", choices=("on", "off", "status"))
    s = sub.add_parser("path", help=f"add or remove the {NAME} command in your terminal, so it works from any folder")
    s.add_argument("action", choices=("add", "remove", "status"))
    s.add_argument("--force", action="store_true", help="point it here even if it points at another download")
    s = sub.add_parser("uninstall", help="stop and remove the containers (keeps your data)")
    s.add_argument("--purge", action="store_true", help="also delete your data")
    s.add_argument("--yes", action="store_true")
    return p


def main(argv=None, ctx=None):
    p = parser()
    a = p.parse_args(argv)
    if not a.cmd:
        p.print_help()
        return 0
    c = ctx or Ctx(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    c.yes = bool(getattr(a, "yes", False)) or c.yes
    try:
        if a.cmd == "logs":
            return logs(c, a.service, a.follow)
        if a.cmd == "modules":
            if a.action != "list" and not a.name:
                p.error(f"modules {a.action} needs a module name")
            return modules(c, a.action, a.name)
        if a.cmd == "access":
            return access(c, a.mode)
        if a.cmd == "apps":
            if a.action == "custom":
                return custom_cmd(c, a.names, a.inside, a.keep, "tools" if a.tools else "apps")
            if a.action != "list" and not a.names:
                p.error(f"apps {a.action} needs an app name")
            return apps_cmd(c, a.action, a.names)
        if a.cmd == "config":
            if a.action == "edit":
                return config_edit(c)
            path = os.path.join(c.stack, "config.yaml")
            return _check_config(c, path, open(path).read()) if os.path.isfile(path) else (c.out("  stop  There is no config.yaml yet. Run ./install.sh first.") or 1)
        if a.cmd == "backup":
            return backup(c, a.to, a.keep)
        if a.cmd == "settings-sync":
            return settings_sync(c, a.repo)
        if a.cmd == "restore":
            return restore(c, a.file)
        if a.cmd == "update":
            return update(c, a.check, a.dry_run, a.channel)
        if a.cmd == "agent":
            return agent_cmd(c, a.action, a.allow_reboot)
        if a.cmd == "autostart":
            return autostart_cmd(c, a.action)
        if a.cmd == "path":
            return path_cmd(c, a.action, a.force)
        if a.cmd == "uninstall":
            return uninstall(c, a.purge)
        return {"status": status, "start": start, "stop": stop, "restart": restart, "doctor": doctor}[a.cmd](c)
    except ImportError as e:
        c.out(f"  stop  A needed Python package is missing ({e}). Install it with: pip3 install pyyaml")
        return 1
    except KeyboardInterrupt:
        c.out("\n  Stopped.")
        return 130


if __name__ == "__main__":
    sys.exit(main())
