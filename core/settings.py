"""Settings made in the dashboard: a file in the data folder that sits on top of config.yaml (the page wins, "Reset" goes back to the file).
Every value is checked with the same rules as config.yaml. An optional PIN, off by default, guards changes. Nothing secret is stored here."""
import copy
import hashlib
import hmac
import os
import threading
import time

from core import config
from core.store import read_json, write_json

FILE = "settings.json"
PIN_KEY = "_pin"  # kept beside the settings, never part of them


def _merge(base, over):
    """over on top of base, section by section. A list or value in over replaces the one in base."""
    out = copy.deepcopy(base)
    for k, v in over.items():
        out[k] = _merge(out[k], v) if isinstance(v, dict) and isinstance(out.get(k), dict) else copy.deepcopy(v)
    return out


def _leaf(schema, parts):
    """The schema entry for a dotted path, or None. Wildcard sections (modules.*) accept any name."""
    node = schema
    for p in parts:
        if not isinstance(node, dict):
            return None
        node = node.get(p, node.get("*"))
        if node is None:
            return None
    return node


def _nest(path, value):
    out = cur = {}
    parts = path.split(".")
    for p in parts[:-1]:
        cur[p] = cur = {}
    cur[parts[-1]] = value
    return out


def _extra(path, value):
    """Rules the schema cannot say: your own tiles must be web links (never javascript: or file:), with a name, and the group must exist."""
    out = []
    if path == "dashboard.tiles" and isinstance(value, list):
        for i, t in enumerate(value, 1):
            if not isinstance(t, dict):
                continue
            if not str(t.get("name", "")).strip():
                out.append(f"dashboard.tiles[{i}] needs a name.")
            if not str(t.get("url", "")).lower().startswith(("http://", "https://")):
                out.append(f"dashboard.tiles[{i}] link should start with http:// or https://.")
            if t.get("group", "apps") not in ("apps", "tools"):
                out.append(f"dashboard.tiles[{i}] group should be apps or tools.")
    return out


def fields(schema=config.SCHEMA, prefix=""):
    """Every setting a person can edit, as (path, kind). The modules section is edited as switches, not as fields."""
    for k, kind in schema.items():
        path = f"{prefix}.{k}" if prefix else k
        if k == "*" or path == "modules" or path.startswith("dashboard"):  # edited as switches and the layout screens, not as plain fields
            continue
        if isinstance(kind, dict):
            yield from fields(kind, path)
        else:
            yield path, kind


def _hint(kind):
    """What a good value looks like. A list of sections (world clocks) has no one-line example."""
    one = kind[0] if isinstance(kind, list) else kind
    return "" if isinstance(one, dict) else config.EXAMPLES.get(one, "")


def _items(kind):
    """What a list holds: its sections' fields (name, kind), or the kind of each plain entry."""
    one = kind[0] if isinstance(kind, list) else None
    if isinstance(one, dict):
        return [{"key": k, "kind": _kind_name(v)} for k, v in one.items()]
    return _kind_name(one) if one is not None else None


def _kind_name(kind):
    if isinstance(kind, list):
        return "list"
    return {config.TIME: "time", config.ZONE: "timezone", str: "text", bool: "switch", int: "whole number", float: "number"}.get(kind, "text")


class Settings:
    def __init__(self, data_dir, base, log=print):
        self.path, self.log, self.lock = os.path.join(data_dir, FILE), log, threading.Lock()
        self.defaults = copy.deepcopy(base.data)  # what config.yaml (or the built-in defaults) say, before the page's settings go on top
        self.fails = []  # times of recent wrong PINs
        raw = read_json(self.path, {}) or {}
        self.pin = raw.pop(PIN_KEY, None) if isinstance(raw, dict) else None
        self.over = raw if isinstance(raw, dict) else {}
        bad = config.check(self.over)
        if bad:  # a hand-edited file with a wrong value: those values are ignored, with a message
            for b in bad:
                log(f"settings.json: {b}")
            self.over = {}

    # ---- the effective config
    def merged(self):
        return _merge(self.defaults, self.over)

    def apply(self, cfg):
        """Put the page's settings on top of a Config, in place. Returns it."""
        cfg.data = self.merged()
        return cfg

    # ---- reading
    def view(self, modules=()):
        eff, out = self.merged(), []
        for path, kind in fields():
            base_v = _dig(self.defaults, path)
            out.append({"path": path, "kind": _kind_name(kind), "value": _dig(eff, path), "default": base_v,
                        "changed": _dig(self.over, path) is not None, "hint": _hint(kind), "items": _items(kind)})
        switches = eff.get("modules") or {}
        mods = [{**m, "enabled": bool(switches.get(m["name"], m["default"])) and not m.get("unavailable"), "changed": m["name"] in (self.over.get("modules") or {})} for m in modules]
        return {"fields": out, "modules": mods, "pin": bool(self.pin), "restart": "Changes apply the next time the assistant starts."}

    # ---- writing
    def _save(self):
        data = dict(self.over)
        if self.pin:
            data[PIN_KEY] = self.pin
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        write_json(self.path, data, indent=1)

    def set(self, changes):
        """changes: {"owner.name": "Sam", "modules.gym": False}. All or none. Returns (ok, problems)."""
        problems, patch = [], {}
        for path, value in changes.items():
            kind = _leaf(config.SCHEMA, path.split("."))
            if kind is None or isinstance(kind, dict):
                problems.append(f"{path} is not a setting I know.")
                continue
            found = config.check(_nest(path, value)) + _extra(path, value)
            problems += found
            if not found:
                patch = _merge(patch, _nest(path, value))
        if problems:
            return False, problems
        with self.lock:
            self.over = _merge(self.over, patch)
            self._save()
        return True, []

    def reset(self, path=None):
        """Forget the page's value for one setting, or for all of them. The file's value (or the default) is back."""
        with self.lock:
            if path is None:
                self.over = {}
            else:
                node = self.over
                parts = path.split(".")
                for p in parts[:-1]:
                    node = node.get(p) if isinstance(node, dict) else None
                    if node is None:
                        return
                node.pop(parts[-1], None)
                self.over = _prune(self.over)
            self._save()

    # ---- the optional PIN
    def _hash(self, pin, salt):
        return hashlib.pbkdf2_hmac("sha256", str(pin).encode(), salt, 120_000).hex()

    def set_pin(self, pin):
        """pin None or "" turns it off."""
        with self.lock:
            if pin:
                salt = os.urandom(16)
                self.pin = {"salt": salt.hex(), "hash": self._hash(pin, salt)}
            else:
                self.pin = None
            self._save()

    def check_pin(self, pin):
        """True if no PIN is set or this one is right. Five wrong tries in a minute pause further tries."""
        if not self.pin:
            return True
        now = time.time()
        self.fails = [t for t in self.fails if now - t < 60]
        if len(self.fails) >= 5:
            return False
        ok = hmac.compare_digest(self._hash(pin or "", bytes.fromhex(self.pin["salt"])), self.pin["hash"])
        if not ok:
            self.fails.append(now)
        return ok

    def locked_out(self):
        return len([t for t in self.fails if time.time() - t < 60]) >= 5


def _dig(d, path):
    for k in path.split("."):
        if not isinstance(d, dict) or k not in d:
            return None
        d = d[k]
    return d


def _prune(d):
    """Drop sections that have become empty."""
    return {k: v for k, v in ((k, _prune(v) if isinstance(v, dict) else v) for k, v in d.items()) if v != {}}


def guard_request(settings, req):
    """None if the request may change things (no PIN is set, or the right one came with it); otherwise the refusal to send."""
    pin = req.headers.get("X-Settings-Pin", "")
    if settings.locked_out():
        return {"ok": False, "error": "Too many wrong PINs. Wait a minute and try again."}, 429
    if not settings.check_pin(pin):
        return {"ok": False, "locked": True, "error": "That PIN is not right."}, 403
    return None


def routes(router, settings, modules, restart=None):
    """GET /settings, POST /settings, /settings/reset and /settings/pin. modules() lists every module (on or off) as dicts."""
    def guard(req):
        return guard_request(settings, req)

    @router.get("/settings")
    def get_settings(req):
        if settings.pin and (bad := guard(req)):
            return {"locked": True, **bad[0]}, bad[1]
        return settings.view(modules())

    @router.post("/settings")
    def set_settings(req):
        if bad := guard(req):
            return bad
        changes = (req.json() or {}).get("set")
        if not isinstance(changes, dict) or not changes:
            return {"ok": False, "error": "Nothing to change."}, 400
        ok, problems = settings.set(changes)
        return ({"ok": True, "restart": True}, 200) if ok else ({"ok": False, "problems": problems}, 400)

    @router.post("/settings/reset")
    def reset_settings(req):
        if bad := guard(req):
            return bad
        settings.reset((req.json() or {}).get("path"))
        return {"ok": True, "restart": True}

    @router.post("/settings/pin")
    def pin(req):
        if bad := guard(req):
            return bad
        new = str((req.json() or {}).get("pin") or "")
        if new and not (4 <= len(new) <= 12 and new.isdigit()):
            return {"ok": False, "error": "Use 4 to 12 digits."}, 400
        settings.set_pin(new)
        return {"ok": True, "pin": bool(new)}
