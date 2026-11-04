#!/usr/bin/env python3
"""Fails if a compose file or Dockerfile uses an image that is not pinned to an exact version (no latest, main, or bare major tags).
Images built from this repo (a service with `build:`) are exempt. Run by `make check` and CI."""
import glob
import os
import re
import sys

import yaml

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FLOATING = {"latest", "main", "master", "stable", "edge", "alpine", "slim", "lts"}
PINNED = re.compile(r".+:v?\d+(\.\d+)+([.-][0-9A-Za-z.-]+)?$")  # at least major.minor, so "2" or "3.12" alone do not count


def pinned(ref):
    if "@sha256:" in ref:
        return True
    tag = ref.rsplit(":", 1)[1] if ":" in ref.split("/")[-1] else ""
    return bool(tag) and tag not in FLOATING and bool(PINNED.match(ref))


def problems(root=ROOT):
    out = []
    for path in sorted(glob.glob(os.path.join(root, "**", "compose*.y*ml"), recursive=True)):
        if "/node_modules/" in path or "/.private/" in path:
            continue
        for name, svc in ((yaml.safe_load(open(path)) or {}).get("services") or {}).items():
            ref = (svc or {}).get("image")
            if ref and "build" not in svc and not pinned(ref):
                out.append(f"{os.path.relpath(path, root)}: {name} uses {ref}, which is not an exact version")
    for path in sorted(glob.glob(os.path.join(root, "**", "Dockerfile*"), recursive=True)):
        if "/.private/" in path:
            continue
        for line in open(path):
            m = re.match(r"\s*FROM\s+(?:--platform=\S+\s+)?(\S+)", line, re.I)
            if m and m.group(1).lower() != "scratch" and not pinned(m.group(1)):
                out.append(f"{os.path.relpath(path, root)}: FROM {m.group(1)} is not an exact version")
    return out


if __name__ == "__main__":
    found = problems()
    for f in found:
        print(f)
    print("pins: " + ("some images float" if found else "every image is pinned"))
    sys.exit(1 if found else 0)
