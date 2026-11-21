"""Newer versions of the apps you added yourself (core/custom.py). Once a week the assistant asks each image's registry which tags exist,
and the morning recap and Settings, Apps say when a newer version is out. It only tells you: nothing is ever updated by itself,
which keeps the rule that images are pinned and change only when you change them. Move to it with: homelab apps custom update <name>.

Any registry that speaks the standard registry API works (Docker Hub, GHCR, Quay, lscr.io and others), with an anonymous token
for public images. Standard library only (the command line imports this too)."""
import json
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request

FILE = "versions.json"  # in the data folder: {app id: {current, newest (same major), major (a bigger jump), checked, told}}
EVERY = 6 * 86400  # a check counts for this long, so a restart does not ask again
PAGES, PER_PAGE = 20, 1000  # big images have thousands of tags; this reads up to 20,000
SHAPE = re.compile(r"^(?P<pre>[A-Za-z]*[-_.]?)(?P<num>\d+(?:\.\d+)*)(?P<post>.*)$")
UNSTABLE = re.compile(r"(alpha|beta|rc|dev|nightly|test|preview|pre|snapshot|unstable|canary|next|edge)", re.I)


def split(image):
    """'jellyfin/jellyfin:10.10.7' -> ('registry-1.docker.io', 'jellyfin/jellyfin', '10.10.7'). A digest has no tag to compare: None."""
    if "@" in image:
        return None
    repo, _, tag = image.rpartition(":")
    if not repo or "/" in tag:
        return None
    first = repo.split("/")[0]
    if "/" in repo and ("." in first or ":" in first or first == "localhost"):
        host, name = first, repo.split("/", 1)[1]
    else:
        host, name = "registry-1.docker.io", repo if "/" in repo else f"library/{repo}"
    if host == "docker.io":
        host = "registry-1.docker.io"
    return host, name, tag


def _get(url, headers=None, timeout=15):
    req = urllib.request.Request(url, headers={"User-Agent": "homelab-versions", **(headers or {})})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.load(r), r.headers.get("Link", "")


def _token(challenge, fetch):
    """An anonymous pull token from the realm a registry names in its 401 answer (Bearer realm="...",service="...",scope="...")."""
    parts = dict(re.findall(r'(\w+)="([^"]*)"', challenge or ""))
    if not parts.get("realm", "").startswith("https://"):
        return None
    q = urllib.parse.urlencode({k: v for k, v in parts.items() if k in ("service", "scope")})
    body, _ = fetch(parts["realm"] + ("?" + q if q else ""), {})
    return body.get("token") or body.get("access_token")


def tags(image, fetch=None):
    """Every tag the image's registry lists, or None when it cannot be asked (private, offline, not a registry)."""
    fetch = fetch or _get
    s = split(image)
    if not s:
        return None
    host, name, _ = s
    url, auth, out = f"https://{host}/v2/{name}/tags/list?n={PER_PAGE}", {}, []
    for _ in range(PAGES):
        try:
            body, link = fetch(url, auth)
        except urllib.error.HTTPError as e:
            if e.code != 401 or auth:
                return None
            try:
                tok = _token(e.headers.get("WWW-Authenticate", ""), fetch)
            except (OSError, ValueError, urllib.error.URLError):
                return None
            if not tok:
                return None
            auth = {"Authorization": f"Bearer {tok}"}
            continue
        except (OSError, ValueError, urllib.error.URLError):
            return None
        out += [t for t in (body.get("tags") or []) if isinstance(t, str)]
        m = re.search(r"<([^>]+)>", link or "")
        if not m:
            break
        url = urllib.parse.urljoin(f"https://{host}", m.group(1))
    return out


def _shape(tag):
    """(prefix, numbers, the suffix with its digits taken out) or None: 'v2.38.1' -> ('v', (2, 38, 1), ''); '10.10.7-ls45' -> ('', (10, 10, 7), '-ls')."""
    m = SHAPE.match(tag)
    if not m:
        return None
    return m["pre"], tuple(int(x) for x in m["num"].split(".")), re.sub(r"\d+", "", m["post"])


def newer(current, available, same_major=False):
    """The newest tag that looks like the one you run (same prefix, as many numbers, same kind of suffix) and is higher, or None.
    Test builds (beta, rc, nightly...) only count if you already run one. '10.10.7' never moves to '10.11.0-alpine'.
    same_major: only within the first number, so a database on 16.4 is offered 16.10, not 19.0."""
    me = _shape(current)
    if not me or len(me[1]) < 2:  # 'latest'-like or a bare major tag: nothing sensible to compare
        return None
    unstable_ok = bool(UNSTABLE.search(current))
    best, best_key = None, (me[1], _suffix_num(current))
    for t in available:
        s = _shape(t)
        if not s or s[0] != me[0] or len(s[1]) != len(me[1]) or s[2] != me[2] or (UNSTABLE.search(t) and not unstable_ok) or (same_major and s[1][0] != me[1][0]):
            continue
        key = (s[1], _suffix_num(t))
        if key > best_key:
            best, best_key = t, key
    return best


def _suffix_num(tag):
    m = SHAPE.match(tag)
    return tuple(int(x) for x in re.findall(r"\d+", m["post"])) if m else ()


def read(data_dir):
    try:
        with open(os.path.join(data_dir, FILE)) as f:
            d = json.load(f)
        return d if isinstance(d, dict) else {}
    except (OSError, ValueError):
        return {}


def _write(data_dir, d):
    p = os.path.join(data_dir, FILE)
    with open(p + ".tmp", "w") as f:
        json.dump(d, f, indent=1)
    os.replace(p + ".tmp", p)


def check_all(data_dir, apps, fetch=None, clock=time.time, force=False):
    """Asks about each app (a list of core/custom.py app dicts) not asked in the last 6 days, or all of them with force. Returns the saved state."""
    old, now = read(data_dir), clock()
    out = {}
    for a in apps:
        s = split(a.get("image", ""))
        if not s:
            continue
        prev = old.get(a["id"]) or {}
        if not force and prev.get("current") == s[2] and now - (prev.get("checked") or 0) < EVERY:
            out[a["id"]] = prev
            continue
        found = tags(a["image"], fetch)
        if found is None:  # could not ask this time: keep what was known, and try again next week
            out[a["id"]] = {**prev, "current": s[2], "checked": now, "failed": True} if prev.get("current") == s[2] else {"current": s[2], "checked": now, "failed": True}
            continue
        top, near = newer(s[2], found), newer(s[2], found, same_major=True)
        out[a["id"]] = {"current": s[2], "newest": near, "major": top if top != near else None, "checked": now,
                        "told": prev.get("told") if prev.get("current") == s[2] else None}
    _write(data_dir, out)
    return out


def available(data_dir, apps):
    """{app id: {"newest": tag or None, "major": tag or None}} for your apps with something newer, as last checked."""
    state = read(data_dir)
    out = {}
    for a in apps:
        s, v = split(a.get("image", "")), state.get(a["id"]) or {}
        if s and v.get("current") == s[2] and (v.get("newest") or v.get("major")):
            out[a["id"]] = {"newest": v.get("newest"), "major": v.get("major")}
    return out


def sentence(title, v, app_id):
    """'Jellyfin 10.10.9 is out (you have 10.10.7). Move to it with: homelab apps custom update jellyfin', plus the bigger jump when there is one."""
    move = f"homelab apps custom update {app_id}"
    if v.get("newest"):
        out = f"{title} {v['newest']} is out (you have {v['current']}). Move to it with: {move}"
        return out + (f" • A bigger jump, {v['major']}, is out too. Read its release notes first, then: {move} {v['major']}" if v.get("major") else "")
    return f"{title} {v['major']} is out (you have {v['current']}), a bigger jump. Read its release notes first, then: {move} {v['major']}"


def news(data_dir, apps):
    """Lines for the morning recap: each newer version once, the first morning after it is found."""
    state, lines = read(data_dir), []
    for a in apps:
        v = state.get(a["id"]) or {}
        s = split(a.get("image", ""))
        found = (v.get("newest"), v.get("major"))
        if s and v.get("current") == s[2] and any(found) and v.get("told") != list(found):
            lines.append(sentence(a["title"], v, a["id"]))
            v["told"] = list(found)
    if lines:
        _write(data_dir, state)
    return lines
