#!/usr/bin/env python3
"""Design-token lint: raw sizes (px, rem) and hex colours belong in tokens.css, not in components.
The count of raw values left today is the ceiling in scripts/tokens-baseline.txt. It may go down, never up.
Run with --update after you have mapped some to tokens, to lower the ceiling."""
import os, re, sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BASE = os.path.join(ROOT, "scripts", "tokens-baseline.txt")
RAW = re.compile(r"(?<![\w#-])\d+(?:\.\d+)?(?:px|rem)\b|#[0-9a-fA-F]{3,8}\b")


def css_of(path):
    s = open(path, encoding="utf-8").read()
    if path.endswith(".html"):
        s = "".join(re.findall(r"<style[^>]*>(.*?)</style>", s, re.S))
    return re.sub(r"/\*.*?\*/", "", s, flags=re.S)


def files():
    for top in ("stack/landing/site", "modules"):
        for d, _, fs in os.walk(os.path.join(ROOT, top)):
            for f in fs:
                p = os.path.join(d, f)
                if f == "tokens.css" or not f.endswith((".html", ".css")):
                    continue
                yield p


def main():
    n = sum(len(RAW.findall(css_of(p))) for p in files())
    if "--update" in sys.argv:
        open(BASE, "w").write(f"{n}\n")
        print(f"baseline set to {n}")
        return 0
    ceiling = int(open(BASE).read().strip()) if os.path.exists(BASE) else n
    if n > ceiling:
        print(f"tokens: {n} raw sizes/colours outside tokens.css (ceiling {ceiling}). Use a token from tokens.css.")
        return 1
    print(f"tokens: {n} raw values left (ceiling {ceiling})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
