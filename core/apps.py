"""The optional apps: what each one is, which compose services it starts, and which ones this install chose.

The choice lives in apps.json in the data folder, so the installer, the host helper, the command line and the dashboard
all read the same list. The core (dashboard, assistant, Docker reader) always runs and is never in the list.
Standard library only (the host helper imports this)."""
import json
import os

CORE = ("landing", "telegram-bot", "docker-proxy")  # always on: the dashboard, the assistant, and the read-only Docker reader

# id: (title, what it gives you, compose services, rough memory in MB when idle, apps it needs, group)
CATALOG = {
    "ollama": ("Local AI engine (Ollama)", "Runs AI models on this machine for chat, journal summaries and news.", ("ollama",), 300, (), "AI"),
    "open-webui": ("AI chat (Open WebUI)", "A ChatGPT-style page for your local models.", ("open-webui",), 600, ("ollama",), "AI"),
    "whisper": ("Voice to text (Whisper)", "Turns voice notes from Telegram into text.", ("whisper",), 500, (), "AI"),
    "monitoring": ("Monitoring (Prometheus and Grafana)", "Server health, app status and charts on the Server page.", ("prometheus", "node-exporter", "cadvisor", "grafana"), 400, (), "Server"),
    "uptime-kuma": ("Website monitor (Uptime Kuma)", "Checks that your websites are up and alerts you.", ("uptime-kuma",), 150, (), "Server"),
    "dozzle": ("Live logs (Dozzle)", "Read every app's log in the browser.", ("dozzle",), 30, (), "Server"),
    "searxng": ("Private search (SearXNG)", "Web search for the assistant without tracking.", ("searxng",), 150, (), "Tools"),
    "n8n": ("Automations (n8n)", "Connect apps and build your own workflows.", ("n8n",), 300, (), "Tools"),
    "homepage": ("Full dashboard (Homepage)", "One page with links to every app.", ("homepage",), 120, (), "Tools"),
    "adguard": ("Ad blocker (AdGuard Home)", "Blocks ads for every device on your network. Needs port 53, so set it up on a machine that is always on.", ("adguard",), 120, (), "Network"),
}


def path(data_dir):
    return os.path.join(data_dir, "apps.json")


def chosen(data_dir):
    """The app ids this install chose, in catalog order. A missing or broken file means none."""
    try:
        with open(path(data_dir)) as f:
            ids = json.load(f).get("apps", [])
    except (OSError, ValueError, AttributeError):
        return []
    return [a for a in CATALOG if a in ids]


def with_needs(ids):
    """ids plus every app they need, in catalog order."""
    want, todo = set(), list(ids)
    while todo:
        a = todo.pop()
        if a in CATALOG and a not in want:
            want.add(a)
            todo.extend(CATALOG[a][4])
    return [a for a in CATALOG if a in want]


def needed_by(app, ids):
    """Chosen apps that need app (so removing it would break them)."""
    return [a for a in ids if app in CATALOG[a][4]]


NATIVE_OK = ("ollama",)  # can run on the machine itself instead of in Docker (Ollama on a Mac, for the Apple GPU)
NATIVE_URL = "http://host.docker.internal:11434"


def native(data_dir):
    """Chosen apps that run on the machine itself, not in Docker."""
    try:
        with open(path(data_dir)) as f:
            return [a for a in json.load(f).get("native", []) if a in NATIVE_OK]
    except (OSError, ValueError, AttributeError):
        return []


def save(data_dir, ids, native_ids=None):
    """native_ids None keeps what was saved before."""
    ids = with_needs(ids)
    keep = native(data_dir) if native_ids is None else list(native_ids)
    os.makedirs(data_dir, exist_ok=True)
    tmp = path(data_dir) + ".tmp"
    with open(tmp, "w") as f:
        json.dump({"apps": ids, **({"native": [a for a in keep if a in ids]} if keep else {})}, f, indent=1)
    os.replace(tmp, path(data_dir))
    return ids


def services(ids, native_ids=()):
    """Compose services to run: the core plus the chosen apps, leaving out the ones that run on the machine itself."""
    out = list(CORE)
    for a in with_needs(ids):
        if a not in native_ids:
            out += [s for s in CATALOG[a][2] if s not in out]
    return out


def owner(service):
    """The app id a compose service belongs to (None for the core or an unknown name)."""
    return next((a for a, v in CATALOG.items() if service in v[2]), None)


def view(ids):
    """The catalog for the dashboard and the command line."""
    return [{"id": a, "title": v[0], "what": v[1], "services": list(v[2]), "memory_mb": v[3], "needs": list(v[4]), "group": v[5], "chosen": a in ids}
            for a, v in CATALOG.items()]
