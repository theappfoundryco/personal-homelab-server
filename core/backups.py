"""Backups on the host: the list of backups, the copy to your own drive or folder (optionally locked with a passphrase), and the
problem alerts the host helper sends on Telegram itself, so they arrive even when the assistant is down. Standard library only.

The state lives in <data>/backup-status.json, which the dashboard reads:
  {"last": {...}, "list": [...], "offsite": {"to", "state", "msg", "at", "file", "encrypted"}, "passphrase": bool, "drives": [...]}
Offsite states: off (no folder chosen), ok, missing (the drive is not plugged in), blocked (macOS has not allowed access),
denied (no permission), full, inside (the folder is inside ~/.homelab, so it would not help), notdir, nolock (no openssl), failed."""
import errno
import json
import os
import re
import shutil
import subprocess
import time as _time
import urllib.parse
import urllib.request

STATUS = "backup-status.json"
PASSFILE = "backup-passphrase"  # in ~/.homelab, outside the data folder the container can see; mode 600
NAME = re.compile(r"^(nightly|backup|snapshot|before-restore)-\d{8}-\d{6}(-\d+)?\.tar\.gz$")
COPY = re.compile(r"^(nightly|backup)-\d{8}-\d{6}(-\d+)?\.tar\.gz(\.enc)?$")
STATES = {
    "ok": "Copied.",
    "ready": "Ready. The next backup is copied here.",
    "missing": "The drive is not plugged in. The copy runs as soon as it is back.",
    "blocked": "macOS has not allowed the host helper to use this drive. Open System Settings, Privacy & Security, Files and Folders (or Full Disk Access), and allow python3. The copy runs by itself after that.",
    "denied": "You do not have permission to write to this folder. Choose another one, or fix its permissions.",
    "full": "The drive is full. Free some space on it, or keep fewer copies.",
    "inside": "This folder is inside ~/.homelab, so a copy there would not help if this machine fails. Choose a folder on another drive.",
    "notdir": "That is not a folder.",
    "nolock": "Locking copies with a passphrase needs openssl, and the one here cannot do it. On a Mac: brew install openssl. On Linux: sudo apt install openssl.",
    "failed": "The copy did not finish.",
}


def read_status(data):
    try:
        with open(os.path.join(data, STATUS)) as f:
            d = json.load(f)
        return d if isinstance(d, dict) else {}
    except (OSError, ValueError):
        return {}


def write_status(data, **parts):
    d = read_status(data)
    d.update(parts)
    os.makedirs(data, exist_ok=True)
    tmp = os.path.join(data, STATUS + ".tmp")
    with open(tmp, "w") as f:
        json.dump(d, f)
    os.replace(tmp, os.path.join(data, STATUS))
    return d


def listing(folder, limit=30):
    """Backups in a folder, newest first: [{"name", "at", "size", "kind"}]."""
    try:
        names = [n for n in os.listdir(folder) if NAME.match(n)]
    except OSError:
        return []
    out = []
    for n in names:
        try:
            st = os.stat(os.path.join(folder, n))
        except OSError:
            continue
        out.append({"name": n, "at": st.st_mtime, "size": st.st_size, "kind": n.split("-", 1)[0]})
    return sorted(out, key=lambda x: x["at"], reverse=True)[:limit]


def drives(platform, user=None, home=None):
    """External drives and network shares that are mounted now: [{"path", "name", "free", "total"}]."""
    user = user or os.environ.get("USER") or ""
    roots = ["/Volumes"] if platform == "mac" else [f"/media/{user}", f"/run/media/{user}", "/mnt", "/media"]
    out, seen = [], set()
    for root in roots:
        try:
            names = sorted(os.listdir(root))
        except OSError:
            continue
        for n in names:
            p = os.path.join(root, n)
            try:
                if not os.path.isdir(p) or os.path.realpath(p) == "/" or p in seen or (platform != "mac" and not os.path.ismount(p)):
                    continue
                u = shutil.disk_usage(p)
            except OSError:
                continue
            seen.add(p)
            out.append({"path": p, "name": n, "free": u.free, "total": u.total})
    return out


def mount_of(path, platform):
    """The drive a folder lives on, when it is a removable one (/Volumes/Name, /media/user/Name), else None."""
    parts = os.path.normpath(path).split(os.sep)
    if platform == "mac" and len(parts) >= 3 and parts[1] == "Volumes":
        return os.sep.join(parts[:3])
    if len(parts) >= 4 and parts[1] in ("media", "run") and (parts[1] == "media" or parts[2] == "media"):
        return os.sep.join(parts[:4] if parts[1] == "media" else parts[:5])
    if len(parts) >= 3 and parts[1] == "mnt":
        return os.sep.join(parts[:3])
    return None


def check_target(path, home, platform):
    """Can copies go to this folder now? -> state (see STATES)."""
    if not path:
        return "off"
    path = os.path.abspath(os.path.expanduser(path))
    if os.path.realpath(path).startswith(os.path.realpath(home) + os.sep) or os.path.realpath(path) == os.path.realpath(home):
        return "inside"
    m = mount_of(path, platform)
    if m and not os.path.isdir(m):
        return "missing"
    try:
        os.makedirs(path, exist_ok=True)
    except OSError as e:
        return _state(e, missing_if_absent=bool(m))
    if not os.path.isdir(path):
        return "notdir"
    probe = os.path.join(path, ".homelab-write-test")
    try:
        with open(probe, "w") as f:
            f.write("ok")
        os.remove(probe)
    except OSError as e:
        return _state(e)
    return "ok"


def _state(e, missing_if_absent=False):
    if e.errno == errno.EPERM:
        return "blocked"  # macOS privacy controls answer EPERM for a drive the helper was not allowed to use
    if e.errno in (errno.EACCES, errno.EROFS):
        return "denied"
    if e.errno == errno.ENOSPC:
        return "full"
    if e.errno == errno.ENOENT and missing_if_absent:
        return "missing"
    return "failed"


def can_lock(run=None):
    """Does this machine's openssl do AES-256 with PBKDF2? (old LibreSSL builds cannot)"""
    run = run or _run
    rc, _ = run(["openssl", "enc", "-aes-256-cbc", "-pbkdf2", "-iter", "1000", "-pass", "pass:x", "-in", os.devnull, "-out", os.devnull])
    return rc == 0


def lock(src, dst, passfile, run=None):
    run = run or _run
    return run(["openssl", "enc", "-aes-256-cbc", "-pbkdf2", "-iter", "200000", "-salt", "-in", src, "-out", dst, "-pass", f"file:{passfile}"])[0] == 0


def unlock(src, dst, passfile, run=None):
    run = run or _run
    return run(["openssl", "enc", "-d", "-aes-256-cbc", "-pbkdf2", "-iter", "200000", "-in", src, "-out", dst, "-pass", f"file:{passfile}"])[0] == 0


def copy_out(src, target, keep, home, platform, run=None):
    """Copies one backup to the chosen folder (locked when a passphrase is set), then keeps only the newest `keep` copies there.
    -> (state, file name or None)."""
    state = check_target(target, home, platform)
    if state != "ok":
        return state, None
    target = os.path.abspath(os.path.expanduser(target))
    passfile = os.path.join(home, PASSFILE)
    locked = os.path.isfile(passfile)
    name = os.path.basename(src) + (".enc" if locked else "")
    dst, part = os.path.join(target, name), os.path.join(target, name + ".part")
    try:
        if locked:
            if not can_lock(run):
                return "nolock", None
            if not lock(src, part, passfile, run):
                _rm(part)
                return "failed", None
        else:
            shutil.copyfile(src, part)
        os.replace(part, dst)
    except OSError as e:
        _rm(part)
        return _state(e), None
    old = sorted(n for n in os.listdir(target) if COPY.match(n))[:-keep] if keep else []
    for n in old:
        _rm(os.path.join(target, n))
    return "ok", name


def _rm(p):
    try:
        os.remove(p)
    except OSError:
        pass


def _run(cmd):
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=1800)
        return r.returncode, (r.stdout + r.stderr).strip()
    except (FileNotFoundError, subprocess.TimeoutExpired) as e:
        return 127, str(e)


def set_passphrase(home, text):
    """Saves the passphrase for locking copies (mode 600), or removes it when text is empty. -> (ok, message)."""
    p = os.path.join(home, PASSFILE)
    if not text:
        _rm(p)
        return True, "Copies are no longer locked. Copies already locked still need the old passphrase."
    if not 8 <= len(text) <= 64:
        return False, "Use 8 to 64 characters."
    os.makedirs(home, exist_ok=True)
    fd = os.open(p, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        f.write(text)
    return True, "Copies are locked from now on."


def telegram(env, text, http=None):
    """Sends a message with the bot from .env (TG_TOKEN, TG_CHAT). -> True when Telegram took it. Never raises."""
    token, chat = env.get("TG_TOKEN"), env.get("TG_CHAT")
    if not token or not chat:
        return False
    body = urllib.parse.urlencode({"chat_id": chat, "text": text, "parse_mode": "HTML", "disable_web_page_preview": "true"}).encode()
    try:
        if http:
            return bool(http(f"https://api.telegram.org/bot{token}/sendMessage", body))
        with urllib.request.urlopen(urllib.request.Request(f"https://api.telegram.org/bot{token}/sendMessage", body), timeout=15) as r:
            return r.status == 200
    except Exception:
        return False


def once_a_day(data, key, now=None):
    """True the first time a key is asked for on a day (so an alert repeats at most daily)."""
    p = os.path.join(data, "alerts-sent.json")
    try:
        with open(p) as f:
            d = json.load(f)
    except (OSError, ValueError):
        d = {}
    today = _time.strftime("%Y-%m-%d", _time.localtime(now))
    if d.get(key) == today:
        return False
    d[key] = today
    d = {k: v for k, v in d.items() if v == today}  # forget older days
    try:
        with open(p + ".tmp", "w") as f:
            json.dump(d, f)
        os.replace(p + ".tmp", p)
    except OSError:
        pass
    return True
