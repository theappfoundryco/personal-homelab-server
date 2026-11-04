#!/usr/bin/env python3
"""Undefined names, checked the way this project works. Modules and the bot get names that live elsewhere (send, state, TZ, ...) from
core.host at start-up: host.need(globals(), "send", ...). Ruff cannot see that and calls every one of them undefined.
This runs ruff's undefined-name check and accepts a name only if the same file lists it in a host.need(...) call or a NEEDS tuple.
A name that is neither imported, defined nor listed would fail at run time with a NameError, so it fails here first.
  python3 scripts/check-needs.py [folder]        (needs ruff: pip install ruff)"""
import ast
import json
import shutil
import subprocess
import sys


def listed(path):
    """Every string a file hands to host.need(...) or keeps in a NEEDS tuple."""
    with open(path, encoding="utf-8") as f:
        tree = ast.parse(f.read())
    names = set()
    for n in ast.walk(tree):
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and n.func.attr == "need":
            names |= {a.value for a in ast.walk(n) if isinstance(a, ast.Constant) and isinstance(a.value, str)}
        if isinstance(n, ast.Assign) and any(isinstance(t, ast.Name) and t.id == "NEEDS" for t in n.targets):
            names |= {a.value for a in ast.walk(n.value) if isinstance(a, ast.Constant) and isinstance(a.value, str)}
    return names


def main():
    ruff = shutil.which("ruff") or ".cache/venv/bin/ruff"
    root = sys.argv[1] if len(sys.argv) > 1 else "."
    r = subprocess.run([ruff, "check", "--select", "F821", "--output-format", "json", "--no-cache", root], capture_output=True, text=True)
    try:
        found = json.loads(r.stdout or "[]")
    except json.JSONDecodeError:
        print("check-needs: ruff did not run. Install it with: pip install ruff", file=sys.stderr)
        return 2
    cache, bad = {}, []
    for e in found:
        path = e["filename"]
        name = e["message"].split("`")[1]
        if path not in cache:
            cache[path] = listed(path)
        if name not in cache[path]:
            bad.append((path, e["location"]["row"], name))
    for path, row, name in sorted(set(bad)):
        print(f"needs: `{name}` is used at {path}:{row} but is not defined, imported or listed in host.need")
    print(f"needs: {len(found)} injected-name uses checked" + ("" if not bad else f", {len(set(bad))} not listed"))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
