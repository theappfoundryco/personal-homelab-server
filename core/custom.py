"""Apps you add yourself: any Docker image, pinned to a version, with one port and an optional folder to keep.

The list lives in custom.json in the data folder, so the dashboard, the host helper and the command line read the same one.
Each app gets its own compose file in <data>/custom and its own compose project, so updates never touch it.
Its port follows the dashboard's access setting (this machine only, or the home network). Deliberately not offered:
privileged mode, the Docker socket and the host network. Standard library only (the host helper imports this)."""
import json
import os
import re

from core import apps as _apps

FILE = "custom.json"
NAME = re.compile(r"^[a-z][a-z0-9-]{1,29}$")
TAG = re.compile(r"^[A-Za-z0-9_][A-Za-z0-9_.-]{0,127}$")
REPO = re.compile(r"^[a-z0-9]+([._-][a-z0-9]+)*(:[0-9]{1,5})?(/[a-z0-9]+([._-][a-z0-9]+)*)*$")
KEEP = re.compile(r"^/[A-Za-z0-9_./-]{0,120}$")
GROUPS = ("apps", "tools")
LABEL = "homelab.custom"
# ports the built-in apps publish (installed or not), so a later Add of a built-in never clashes; tests check this against compose.yaml
BUILTIN_PORTS = (53, 3000, 3001, 3002, 3080, 3095, 5678, 8081, 8888, 8889, 9090, 9100, 11434)
RESERVED = set(_apps.CORE) | set(_apps.CATALOG) | {s for v in _apps.CATALOG.values() for s in v[2]} | {"watchtower", "homelab", "custom"}


def path(data_dir):
    return os.path.join(data_dir, FILE)


def load(data_dir):
    """-> list of app dicts (id, title, image, port, inside, keep, group). A missing or broken file means none."""
    try:
        with open(path(data_dir)) as f:
            items = json.load(f).get("apps", [])
    except (OSError, ValueError, AttributeError):
        return []
    return [a for a in items if isinstance(a, dict) and NAME.match(str(a.get("id", ""))) and a["id"] not in RESERVED]


def ids(data_dir):
    return [a["id"] for a in load(data_dir)]


def get(data_dir, app_id):
    return next((a for a in load(data_dir) if a["id"] == app_id), None)


def _save(data_dir, items):
    os.makedirs(data_dir, exist_ok=True)
    tmp = path(data_dir) + ".tmp"
    with open(tmp, "w") as f:
        json.dump({"apps": items}, f, indent=1)
    os.replace(tmp, path(data_dir))


def slug(title):
    return re.sub(r"-+", "-", re.sub(r"[^a-z0-9]+", "-", str(title or "").lower())).strip("-")[:30]


def pinned(image):
    """True for repo:tag (not latest) or repo@sha256:digest."""
    image = str(image or "").strip()
    if "@" in image:
        repo, _, digest = image.partition("@")
        return bool(REPO.match(repo.rsplit(":", 1)[0] if ":" in repo.rsplit("/", 1)[-1] else repo)) and bool(re.match(r"^sha256:[a-f0-9]{64}$", digest))
    repo, sep, tag = image.rpartition(":")
    if not sep or "/" in tag:
        return False
    return bool(REPO.match(repo)) and bool(TAG.match(tag)) and tag.lower() != "latest"


def _port(v):
    try:
        p = int(str(v).strip())
    except ValueError:
        return None
    return p if 1024 <= p <= 65535 else None


def check(data_dir, spec, taken=(), containers=()):
    """-> (app, None) ready to save, or (None, what is wrong). taken: ports in use now; containers: names of containers that exist now."""
    title = str(spec.get("title") or spec.get("name") or "").strip()[:40]
    app_id = slug(spec.get("id") or title)
    image = str(spec.get("image") or "").strip()
    port, inside = _port(spec.get("port")), _port(spec.get("inside") or spec.get("port"))
    keep = str(spec.get("keep") or "").strip()
    group = spec.get("group") or "apps"
    mine = ids(data_dir)
    if not title or not NAME.match(app_id):
        return None, "Give it a name that starts with a letter (letters, numbers and dashes)."
    if app_id in RESERVED or app_id in mine:
        return None, f"The name {app_id} is taken. Pick another."
    if app_id in containers:
        return None, f"A container called {app_id} already exists on this machine. Pick another name."
    if not image:
        return None, "Add the image, like jellyfin/jellyfin:10.10.7."
    if not pinned(image):
        return None, "Pin the image to a version, like jellyfin/jellyfin:10.10.7, not latest, so it only changes when you change it."
    if port is None:
        return None, "The port must be a number from 1024 to 65535."
    if inside is None:
        return None, "The port inside the app must be a number from 1024 to 65535."
    used = set(BUILTIN_PORTS) | {int(p) for p in taken if str(p).isdigit()} | {a["port"] for a in load(data_dir)}
    if port in used:
        return None, f"Port {port} is already used on this machine. Pick another."
    if keep and (not KEEP.match(keep) or ".." in keep.split("/") or keep == "/"):
        return None, "The folder to keep is a path inside the app, like /config."
    if group not in GROUPS:
        return None, "Choose Everyday apps or Tools."
    return {"id": app_id, "title": title, "image": image, "port": port, "inside": inside, "keep": keep, "group": group}, None


def add(data_dir, app):
    _save(data_dir, [a for a in load(data_dir) if a["id"] != app["id"]] + [app])


def forget(data_dir, app_id):
    _save(data_dir, [a for a in load(data_dir) if a["id"] != app_id])
    try:
        os.remove(compose_path(data_dir, app_id))
    except OSError:
        pass


def project(app_id):
    return f"homelab-custom-{app_id}"


def volume(app_id):
    return f"homelab-custom-{app_id}"


def compose_path(data_dir, app_id):
    return os.path.join(data_dir, "custom", f"{app_id}.yaml")


def compose_text(app):
    """The compose file for one app. Values are checked by check(), and quoted here anyway."""
    q = json.dumps
    lines = ["# Written by homelab from custom.json. Change it in Settings, Apps, or with: homelab apps custom",
             f"name: {q(project(app['id']))}", "services:", f"  {app['id']}:", f"    image: {q(app['image'])}", f"    container_name: {q(app['id'])}",
             "    restart: unless-stopped", f"    labels: {{{q(LABEL)}: {q(app['id'])}}}", "    environment: {TZ: \"${HL_TIMEZONE:-UTC}\"}",
             f"    ports: [\"${{HL_BIND:-127.0.0.1}}:{int(app['port'])}:{int(app['inside'])}\"]"]
    if app.get("keep"):
        lines += [f"    volumes: [{q(volume(app['id']) + ':' + app['keep'])}]", "volumes:", f"  {volume(app['id'])}:", f"    name: {q(volume(app['id']))}"]
    return "\n".join(lines) + "\n"


def write(data_dir, app):
    p = compose_path(data_dir, app["id"])
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p + ".tmp", "w") as f:
        f.write(compose_text(app))
    os.replace(p + ".tmp", p)
    return p


def view(data_dir):
    """Your apps, shaped like core/apps.py view() for the dashboard and the command line."""
    return [{"id": a["id"], "title": a["title"], "what": a["image"], "services": [a["id"]], "memory_mb": None, "needs": [], "group": "Your apps",
             "chosen": True, "custom": True, "port": a["port"], "tile": a.get("group", "apps")} for a in load(data_dir)]
