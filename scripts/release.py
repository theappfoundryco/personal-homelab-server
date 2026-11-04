#!/usr/bin/env python3
"""Releases, without typing git tag. A release exists once main's core/version.py names a version that has no tag yet:
the Cut release workflow then tags that commit and writes the GitHub Release. Run it yourself to see what would happen:

  python3 scripts/release.py preview    the version on this branch, whether it is new, and its notes (nothing is changed)
  python3 scripts/release.py check      for the workflow: prints tag=... and new=true|false, fails if the version went down
  python3 scripts/release.py notes vX   the notes for tag vX, from the commit sentences since the release before it"""
import os
import re
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from core.release_notes import markdown, parse_notes  # noqa: E402


def git(*args):
    r = subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True)
    return r.returncode, r.stdout.strip()


def vkey(v):
    m = re.fullmatch(r"v?(\d+)\.(\d+)\.(\d+)", str(v or "").strip())
    return tuple(int(x) for x in m.groups()) if m else None


def version(ref="HEAD"):
    rc, text = git("show", f"{ref}:core/version.py")
    m = re.search(r'VERSION = "([^"]+)"', text) if rc == 0 else None
    if not m or not vkey(m.group(1)):
        sys.exit("core/version.py has no plain version like 0.3.0")
    return m.group(1)


def tags():
    rc, text = git("tag", "-l", "v*")
    return sorted((t for t in text.split() if vkey(t)), key=vkey)


def notes(tag, head=None):
    older = [t for t in tags() if vkey(t) < vkey(tag)]
    if not older:
        return "The first release."
    rc, text = git("log", "--format=%s", f"{older[-1]}..{head or tag}")
    return markdown(parse_notes(text.splitlines()))


def main(argv):
    cmd = argv[1] if len(argv) > 1 else "preview"
    if cmd == "notes" and len(argv) > 2:
        print(notes(argv[2]))
        return 0
    v, have = version(), tags()
    tag, newest = f"v{version()}", (have[-1] if have else None)
    if cmd == "check":
        if tag in have:
            print(f"tag={tag}\nnew=false")
            return 0
        if newest and vkey(tag) < vkey(newest):
            print(f"core/version.py says {v}, which is older than the newest release {newest}. Raise it.", file=sys.stderr)
            return 1
        print(f"tag={tag}\nnew=true")
        return 0
    if cmd == "preview":
        if tag in have:
            print(f"{v} is already released ({tag}). To make a new release, raise VERSION in core/version.py in your pull request.")
            return 0
        print(f"Merging this makes release {tag} (newest now: {newest or 'none'}).\n\nRelease notes:\n")
        print(notes(tag, head="HEAD"))
        return 0
    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv))
