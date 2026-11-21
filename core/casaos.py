"""Add an app from the CasaOS app store (github.com/IceWhaleTech/CasaOS-AppStore, Apache-2.0, about 180 apps) as one of your own apps.

The store's compose file is fetched when you ask, never shipped in this repository. Only what core/custom.py allows is taken:
one service, its web page port, the folders that hold its own data, and its settings. Anything with more power than that
(privileged mode, the host network, the Docker socket, extra capabilities) is refused with the reason. What is left out
(other ports, hardware devices, your own media folders) is listed, so nothing is dropped silently.
Settings that look like passwords and come with a fixed value in the store get a random one instead, so no two installs share a key."""
import json
import re
import secrets
import shlex
import urllib.error
import urllib.request

from core import apps as _apps
from core import custom as _custom
from core import versions as _versions

STORE = "https://raw.githubusercontent.com/IceWhaleTech/CasaOS-AppStore/main/Apps"
LISTING = "https://api.github.com/repos/IceWhaleTech/CasaOS-AppStore/contents/Apps"
NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
APP_DATA = re.compile(r"^/DATA/AppData/(\$AppID|[A-Za-z0-9._-]+)(/|$)")  # where CasaOS keeps an app's own data
SECRET = re.compile(r"(KEY|SECRET|PASSWORD|PASS|TOKEN|SALT)$", re.I)
MORE_POWER = ("privileged", "cap_add", "security_opt", "pid", "ipc", "userns_mode", "cgroup_parent")
SKIPPED_QUIETLY = {"image", "container_name", "restart", "ports", "volumes", "environment", "network_mode", "deploy", "x-casaos", "labels",
                   "hostname", "healthcheck", "logging", "expose", "stop_grace_period", "tty", "stdin_open", "mem_limit", "cpu_shares", "shm_size", "devices"}


def _text(v):
    """An English line from the store's {en_us: ..., zh_cn: ...} blocks."""
    if isinstance(v, dict):
        v = v.get("en_us") or v.get("en_US") or v.get("en_GB") or next(iter(v.values()), "")
    return " ".join(str(v or "").split())


def _get(url, timeout=20):
    req = urllib.request.Request(url, headers={"User-Agent": "homelab-casaos"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read(1_000_000).decode("utf-8", "replace")


def apps(fetch=None):
    """Every app name in the store, or None when the store cannot be reached."""
    try:
        items = json.loads((fetch or _get)(LISTING))
    except (OSError, ValueError, urllib.error.URLError):
        return None
    return sorted((i["name"] for i in items if isinstance(i, dict) and i.get("type") == "dir" and NAME.match(str(i.get("name", "")))), key=str.lower) if isinstance(items, list) else None


def find(word, names):
    w = word.lower()
    exact = [n for n in names if n.lower() == w]
    return exact or [n for n in names if w in n.lower()]


def load(name, fetch=None):
    """The store's compose file for an app as a dict, or (None, why)."""
    import yaml
    if not NAME.match(name or ""):
        return None, "That is not an app name from the store."
    try:
        doc = yaml.safe_load((fetch or _get)(f"{STORE}/{name}/docker-compose.yml"))
    except urllib.error.HTTPError as e:
        return None, f"The store has no app called {name}." if e.code == 404 else f"The store answered {e.code}."
    except (OSError, urllib.error.URLError):
        return None, "The CasaOS store cannot be reached (no internet?)."
    except yaml.YAMLError:
        return None, f"The store's file for {name} could not be read."
    return (doc, None) if isinstance(doc, dict) and isinstance(doc.get("services"), dict) else (None, f"The store's file for {name} is not in a shape this tool knows.")


def _pinned_image(image, tags_of):
    """The image pinned to a version. 'latest' or no tag becomes the newest plain version the registry lists, or None."""
    image = str(image or "").strip()
    if _custom.pinned(image):
        return image
    repo = image.rpartition(":")[0] if ":" in image.rsplit("/", 1)[-1] else image
    found = tags_of(f"{repo}:latest") or []
    plain = [t for t in found if re.match(r"^v?\d+(\.\d+){1,3}$", t)]
    best = max(plain, key=lambda t: tuple(int(x) for x in t.lstrip("v").split(".")), default=None)
    return f"{repo}:{best}" if best and _custom.pinned(f"{repo}:{best}") else None


def _ports(svc):
    out = []
    for p in svc.get("ports") or []:
        if isinstance(p, dict):
            out.append((str(p.get("published", "")).strip(), str(p.get("target", "")).strip(), str(p.get("protocol") or "tcp")))
        else:
            m = re.match(r"^(?:[\d.]+:)?(\d+):(\d+)(?:/(\w+))?$", str(p).strip())
            if m:
                out.append((m[1], m[2], m[3] or "tcp"))
    return out


def _volumes(svc):
    out = []
    for v in svc.get("volumes") or []:
        if isinstance(v, dict):
            out.append((str(v.get("source", "")), str(v.get("target", ""))))
        else:
            parts = str(v).split(":")
            if len(parts) >= 2:
                out.append((parts[0], parts[1]))
    return out


def spec(doc, uid=1000, gid=1000, port=None, tags_of=None):
    """-> (spec for core/custom.py check(), [notes about what was left out or changed]) or (None, why it cannot be added)."""
    tags_of = tags_of or _versions.tags
    x = doc.get("x-casaos") or {}
    services = doc["services"]
    if len(services) != 1:
        return None, f"It needs {len(services)} containers working together, and apps added here are one container each. Install it by hand with its own compose file."
    sid, svc = next(iter(services.items()))
    svc = svc or {}
    for k in MORE_POWER:
        if (svc.get(k) == "host") if k in ("pid", "ipc") else svc.get(k):
            return None, f"It asks for more power than apps added here get ({k.replace('_', ' ')}). Install it by hand if you trust it."
    if str(svc.get("network_mode") or "bridge") not in ("bridge", "default"):
        return None, "It needs the machine's own network (network_mode host), which apps added here do not get."
    vols = _volumes(svc)
    if any("docker.sock" in s or "docker.sock" in t for s, t in vols):
        return None, "It needs the Docker socket, which would let it control every container. Apps added here never get it."
    image = _pinned_image(svc.get("image"), tags_of)
    if not image:
        return None, f"Its image ({svc.get('image')}) has no version to pin to. Add it by hand with a version."
    notes = []
    ports = [p for p in _ports(svc) if p[2] == "tcp"]
    want = str(x.get("port_map") or "").strip()
    web = next((p for p in ports if p[0] == want), None) or (ports[0] if ports else None)
    if not web or not web[1].isdigit():
        return None, "The store does not say which port its web page is on. Add it by hand."
    host_port = int(port or web[0] or web[1])
    others = sorted({p[0] or p[1] for p in _ports(svc) if p is not web and (p[0] or p[1]) != web[0]})
    if others:
        notes.append(f"Only its web page port is opened. Not opened: {', '.join(others)}.")
    keep = [t for s, t in vols if APP_DATA.match(s) and t.startswith("/")]
    left = [t for s, t in vols if not APP_DATA.match(s) and t not in ("/etc/localtime", "/etc/timezone")]
    if left:
        notes.append(f"Folders from this machine are not connected: {', '.join(left)}. Add your files to the app another way.")
    if svc.get("devices"):
        notes.append("Hardware devices (like video decoding) are left off.")
    env, changed = {}, []
    raw = svc.get("environment") or {}
    if isinstance(raw, list):
        raw = dict(str(e).split("=", 1) if "=" in str(e) else (str(e), "") for e in raw)
    for k, v in raw.items():
        v = "" if v is None else str(v)
        if k == "TZ":
            continue  # every app gets your time zone already
        who = re.match(r"^\$\{?(PUID|PGID)(:-\d+)?\}?$", v)
        if who:
            v = str(uid if who[1] == "PUID" else gid)
        elif "$" in v:
            return None, f"Its setting {k} needs a value the store fills in ({v}). Add it by hand."
        elif SECRET.search(str(k)) and v:
            v = secrets.token_hex(max(8, len(v)))[:max(8, len(v))]  # the same length: some apps check it
            changed.append(k)
        env[str(k)] = v
    if changed:
        notes.append(f"The store gives {', '.join(changed)} a fixed value, so a random one was made instead.")
    command = svc.get("command")
    if isinstance(command, str):
        try:
            command = shlex.split(command)
        except ValueError:
            return None, "Its start command could not be read. Add it by hand."
    if command is not None and (not isinstance(command, list) or "$" in " ".join(map(str, command))):
        return None, "Its start command needs values the store fills in. Add it by hand."
    user = str(svc.get("user") or "").replace("$PUID", str(uid)).replace("$PGID", str(gid))
    extra = sorted(k for k in svc if k not in SKIPPED_QUIETLY and k not in MORE_POWER and k not in ("command", "user"))
    if extra:
        return None, f"It needs compose settings apps added here do not take ({', '.join(extra)}). Add it by hand."
    title = _text(x.get("title")) or sid
    app_id = _custom.slug(title)
    builtin = next((k for k, v in _apps.CATALOG.items() if app_id == k or app_id in v[2]), None)
    if builtin:
        return None, f"{title} is one of the apps that come with this, set up to work with the rest. Add it with: homelab apps add {builtin}"
    if not re.match(r"^[a-z]", app_id):
        app_id = "app-" + app_id  # 2FAuth -> app-2fauth
    category = _text(x.get("category")).lower()
    return {"id": app_id[:30], "title": title[:40], "image": image, "port": host_port, "inside": int(web[1]), "keep": keep[0] if keep else "", "more": keep[1:5], "env": env,
            "group": "tools" if category in ("developer", "utilities", "network", "backup", "security") else "apps",
            **({"command": [str(c) for c in command]} if command else {}), **({"user": user} if user else {})}, notes


def prepare(word, uid=1000, gid=1000, port=None, fetch=None, tags_of=None):
    """From a name typed by you to (store name, spec, notes), or (None, why, matches). Used by the command line and the dashboard alike."""
    names = apps(fetch)
    if names is None:
        return None, "The CasaOS store cannot be reached (no internet?).", []
    hits = find(word or "", names)
    if len(hits) != 1:
        return None, (f"The store has no app called {word}." if not hits else f"More than one app matches {word}: {', '.join(hits[:8])}."), hits
    doc, why = load(hits[0], fetch)
    if not doc:
        return None, why, []
    got, notes = spec(doc, uid, gid, port, tags_of)
    return (hits[0], got, notes) if got else (None, notes, [])
