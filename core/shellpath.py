"""Puts the `homelab` command on the terminal's PATH: a link in ~/.local/bin, plus one marked line in the shell's startup file if that folder
is not on the PATH yet. Both come out again with remove(), and only if they are ours.

check() looks first and changes nothing, so the installer can say "already there, skipping" instead of asking. Every case it knows:
  ready       the command already runs this project (our link, or this project's bin folder on the PATH) and a new terminal finds it
  needs_line  our link is there but ~/.local/bin is not on the PATH and the startup file lacks our line
  missing     nothing yet
  stale       a homelab link points at a folder that no longer exists (an old download): safe to replace
  other       a homelab link points at another download of this project: replaced only when asked (force)
  clash       something else is called homelab (a file, or another program earlier on the PATH): never touched
"""
import os
import shutil

MARK = "# added by homelab, remove with: homelab path remove"
LINE = 'export PATH="$HOME/.local/bin:$PATH"'
FISH = "fish_add_path $HOME/.local/bin"


def rc_file(home, shell, platform, env=None):
    """The startup file the user's shell reads for a new terminal."""
    name = os.path.basename(shell or "")
    if name == "zsh":
        return os.path.join((env or {}).get("ZDOTDIR") or home, ".zshrc")
    if name == "bash":
        return os.path.join(home, ".bash_profile" if platform == "mac" else ".bashrc")
    if name == "fish":
        return os.path.join(home, ".config", "fish", "config.fish")
    return os.path.join(home, ".profile")


def _same(a, b):
    return os.path.realpath(a) == os.path.realpath(b)


def _ours(link, target):
    return os.path.islink(link) and _same(link, target)


def _a_project_link(link, name):
    """A link made by some download of this project: it points at <folder>/bin/<name>."""
    if not os.path.islink(link):
        return False
    dest = os.readlink(link)
    return os.path.basename(dest) == name and os.path.basename(os.path.dirname(dest)) == "bin"


def _on_path(folder, path):
    return os.path.realpath(folder) in {os.path.realpath(p) for p in path.split(os.pathsep) if p}


def _has_line(rc):
    try:
        return MARK in open(rc).read()
    except OSError:
        return False


def check(root, home, name="homelab", path=None, shell=None, platform="linux", which=shutil.which, env=None):
    """-> dict(state, link, rc, found, detail). Changes nothing."""
    env = os.environ if env is None else env
    path = env.get("PATH", "") if path is None else path
    shell = env.get("SHELL", "") if shell is None else shell
    bindir, target = os.path.join(home, ".local", "bin"), os.path.join(root, "bin", name)
    link, rc = os.path.join(bindir, name), rc_file(home, shell, platform, env)
    found = which(name, path=path)
    reachable = _on_path(bindir, path) or _has_line(rc)
    r = {"link": link, "rc": rc, "found": found, "detail": None}
    if found and _same(found, target) and not _ours(found, target):  # this project's own bin folder is on the PATH
        return {**r, "state": "ready", "detail": os.path.dirname(found)}
    if found and not _same(found, target) and not _same(found, link):  # another homelab comes first on the PATH
        return {**r, "state": "clash", "detail": found}
    if os.path.lexists(link):
        if _ours(link, target):
            return {**r, "state": "ready" if reachable else "needs_line", "detail": link}
        if _a_project_link(link, name):
            dest = os.path.realpath(link)
            return {**r, "state": "other" if os.path.exists(dest) else "stale", "detail": os.path.dirname(os.path.dirname(os.readlink(link)))}
        return {**r, "state": "clash", "detail": link}
    if found:  # resolves to us through some other route
        return {**r, "state": "ready", "detail": found}
    return {**r, "state": "missing"}


def add(root, home, name="homelab", path=None, shell=None, platform="linux", which=shutil.which, force=False, env=None):
    """-> (state, detail). state: added, already, replaced (detail: the old folder), other (not forced), clash (detail: what is in the way).
    detail for added/already is the startup file that holds our line, or None when it was not needed. Raises OSError when a file is not writable."""
    env = os.environ if env is None else env
    path = env.get("PATH", "") if path is None else path
    c = check(root, home, name, path, shell, platform, which, env)
    target = os.path.join(root, "bin", name)
    st = c["state"]
    if st == "clash" or (st == "other" and not force):
        return st, c["detail"]
    if st == "ready":
        return "already", c["rc"] if _has_line(c["rc"]) else None
    state = "already" if st == "needs_line" else "added"
    if st in ("stale", "other"):
        os.remove(c["link"])
        state = "replaced"
    if st != "needs_line":
        os.makedirs(os.path.dirname(c["link"]), exist_ok=True)
        os.symlink(target, c["link"])
    rc = None
    if not _on_path(os.path.dirname(c["link"]), path):
        rc = c["rc"]
        text = open(rc).read() if os.path.exists(rc) else ""
        if MARK not in text:
            os.makedirs(os.path.dirname(rc), exist_ok=True)
            with open(rc, "a") as f:
                f.write(("" if not text or text.endswith("\n") else "\n") + f"\n{MARK}\n{FISH if rc.endswith('.fish') else LINE}\n")
            if state == "already":
                state = "added"
    return (state, c["detail"]) if state == "replaced" else (state, rc)


def manual(home, shell, platform, root, name="homelab", env=None):
    """The two commands to run by hand when a file was not writable."""
    rc = rc_file(home, shell, platform, env)
    line = FISH if rc.endswith(".fish") else LINE
    return [f"mkdir -p ~/.local/bin && ln -s '{os.path.join(root, 'bin', name)}' ~/.local/bin/{name}",
            f"echo '{line}' >> {rc.replace(home, '~', 1)}"]


def remove(root, home, name="homelab"):
    """Removes our link and our marked line from every startup file. -> list of what was removed."""
    gone, link = [], os.path.join(home, ".local", "bin", name)
    if _a_project_link(link, name) and not _ours(link, os.path.join(root, "bin", name)) and os.path.exists(os.path.realpath(link)):
        return gone  # another download of this project uses the link and the PATH line; leave both
    if _ours(link, os.path.join(root, "bin", name)):
        os.remove(link)
        gone.append(link)
    elif _a_project_link(link, name) and not os.path.exists(os.path.realpath(link)):  # left by a download that is gone
        os.remove(link)
        gone.append(link)
    rcs = {rc_file(home, s, p) for s in ("zsh", "bash", "fish", "") for p in ("mac", "linux")}
    if os.environ.get("ZDOTDIR"):
        rcs.add(os.path.join(os.environ["ZDOTDIR"], ".zshrc"))
    for rc in rcs:
        try:
            lines = open(rc).read().split("\n")
        except OSError:
            continue
        if MARK not in lines:
            continue
        i = lines.index(MARK)
        drop = {i, i + 1} if i + 1 < len(lines) and lines[i + 1] in (LINE, FISH) else {i}
        if i > 0 and lines[i - 1] == "":
            drop.add(i - 1)
        with open(rc, "w") as f:
            f.write("\n".join(l for n, l in enumerate(lines) if n not in drop))
        gone.append(rc)
    return gone
