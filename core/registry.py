"""Finds modules (modules/*/module.yaml), works out which are on, and in what order to start them. Never raises on a bad module: it is skipped with a message."""
import os
import sys

import yaml

PLATFORMS = {"linux", "mac", "wsl"}


def this_platform():
    if sys.platform == "darwin":
        return "mac"
    if sys.platform.startswith("linux"):
        return "wsl" if "microsoft" in os.uname().release.lower() else "linux"
    return sys.platform


class Module:
    def __init__(self, path, meta):
        self.path = path
        self.name = meta["name"]
        self.title = meta.get("title") or self.name
        self.description = meta.get("description", "")
        self.version = str(meta.get("version", "0.1.0"))
        self.default = bool(meta.get("default", True))                # on unless the user switches it off
        self.requires = list(meta.get("requires") or [])               # other modules it cannot work without
        self.optional = list(meta.get("optional") or [])               # capabilities it can use if present (ollama, telegram, ...)
        self.platforms = list(meta.get("platforms") or sorted(PLATFORMS))
        self.settings = meta.get("settings") or {}
        self.dashboard = meta.get("dashboard") or {}                   # tab and home cards it adds, with default order (read by the Settings layout editor)


def discover(root, log=print):
    """All valid modules under root, by name. A folder with a broken module.yaml is skipped and reported."""
    found = {}
    if not os.path.isdir(root):
        return found
    for d in sorted(os.listdir(root)):
        f = os.path.join(root, d, "module.yaml")
        if d.startswith(("_", ".")) or not os.path.isfile(f):
            continue
        try:
            with open(f) as fh:
                meta = yaml.safe_load(fh) or {}
            if not isinstance(meta, dict) or not meta.get("name"):
                raise ValueError("it needs a name: line")
            if meta["name"] != d:
                raise ValueError(f"name is {meta['name']!r} but the folder is {d!r}; they must match")
            bad = [p for p in (meta.get("platforms") or []) if p not in PLATFORMS]
            if bad:
                raise ValueError(f"platforms should be from {sorted(PLATFORMS)} (you wrote {bad})")
            found[d] = Module(os.path.join(root, d), meta)
        except Exception as e:
            log(f"module {d} skipped: {d}/module.yaml is not valid ({e}).")
    return found


def find_cycle(mods):
    """A dependency loop as a list of names (a, b, a), or None."""
    state, stack = {}, []

    def visit(n):
        state[n] = 1
        stack.append(n)
        for r in mods[n].requires:
            if r not in mods:
                continue
            if state.get(r) == 1:
                return stack[stack.index(r):] + [r]
            if r not in state and (c := visit(r)):
                return c
        stack.pop()
        state[n] = 2
        return None

    for n in mods:
        if n not in state and (c := visit(n)):
            return c
    return None


def plan(mods, switches=None, platform=None, log=print):
    """(ordered, notes): module names to start, dependencies first, plus a plain-English note for everything left out.
    switches is config's modules: section, {name: True/False}; a module not mentioned follows its own default."""
    switches, platform = switches or {}, platform or this_platform()
    notes = {}
    on = {n for n, m in mods.items() if switches.get(n, m.default)}
    for n in list(on):
        if platform not in mods[n].platforms:
            on.discard(n)
            notes[n] = f"{mods[n].title} is hidden: it needs {' or '.join(mods[n].platforms)} and this machine is {platform}."
    for n in sorted(set(switches) - set(mods)):
        log(f"config.yaml modules: there is no module called {n!r}. Known modules: {', '.join(sorted(mods)) or 'none'}.")
    cyc = find_cycle(mods)
    if cyc:
        for n in cyc:
            on.discard(n)
            notes[n] = f"{mods[n].title} is off: modules depend on each other in a loop ({' > '.join(cyc)})."
    changed = True
    while changed:  # a module whose requirement is off or missing cannot run
        changed = False
        for n in sorted(on):
            for r in mods[n].requires:
                if r not in on:
                    on.discard(n)
                    why = "is not installed" if r not in mods else notes.get(r, "is switched off")
                    notes[n] = f"{mods[n].title} is off: it needs {r}, which {why.removeprefix(mods[r].title + ' ') if r in mods else why}."
                    changed = True
                    break
    for n in mods:
        if n not in on and n not in notes:
            notes[n] = f"{mods[n].title} is switched off in config.yaml."
    order, seen = [], set()

    def add(n):
        if n in seen:
            return
        seen.add(n)
        for r in mods[n].requires:
            if r in on:
                add(r)
        order.append(n)

    for n in sorted(on):
        add(n)
    return order, notes


def start(mod, app, log=print):
    """Import modules/<name>/__init__.py and call its register(app). Returns True if it started; a module that breaks is skipped with a message."""
    import importlib.util
    try:
        key = f"modules.{mod.name}"
        py = sys.modules.get(key)
        if py is None or os.path.dirname(getattr(py, "__file__", "") or "") != mod.path:  # already imported by the app: reuse that copy
            spec = importlib.util.spec_from_file_location(key, os.path.join(mod.path, "__init__.py"))
            py = importlib.util.module_from_spec(spec)
            sys.modules[key] = py
            spec.loader.exec_module(py)
        py.register(app)
        return True
    except Exception as e:
        log(f"module {mod.name} could not start ({e}). The rest of the app keeps working; check modules/{mod.name}/.")
        return False
