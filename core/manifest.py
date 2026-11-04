"""What install.sh (and later homelab commands) put on this machine outside the project folder, so uninstall removes exactly that and never
something the user had before. One line per thing in HL_HOME/installed.txt: "<kind> <value>". Plain lines, so install.sh writes them with echo.

Kinds:
  brew <formula>     a Homebrew package this program installed (colima, docker, docker-compose, docker-buildx, ollama)
  homebrew yes       Homebrew itself (recorded, kept on uninstall: other programs use it)
  docker-linux yes   Docker from get.docker.com (recorded, kept on uninstall: other programs use it)
  plugin-link <path> a Docker plugin link in ~/.docker/cli-plugins
"""
import os

FILE = "installed.txt"
SHARED = ("homebrew", "docker-linux")  # recorded so the user can see them, never removed by this program


def path(home):
    return os.path.join(home, FILE)


def load(home):
    """-> list of (kind, value), in the order they were added, without repeats."""
    out = []
    try:
        lines = open(path(home)).read().splitlines()
    except OSError:
        return out
    for line in lines:
        kind, _, value = line.strip().partition(" ")
        if kind and (kind, value.strip()) not in out:
            out.append((kind, value.strip()))
    if os.path.exists(os.path.join(home, "ollama-by-homelab")) and ("brew", "ollama") not in out:  # the marker older versions wrote
        out.append(("brew", "ollama"))
    return out


def has(home, kind, value="yes"):
    return (kind, value) in load(home)


def add(home, kind, value="yes"):
    if has(home, kind, value):
        return
    os.makedirs(home, exist_ok=True)
    with open(path(home), "a") as f:
        f.write(f"{kind} {value}\n")


def drop(home, kind, value="yes"):
    keep = [(k, v) for k, v in load(home) if (k, v) != (kind, value)]
    try:
        os.remove(os.path.join(home, "ollama-by-homelab"))
    except OSError:
        pass
    if not keep:
        try:
            os.remove(path(home))
        except OSError:
            pass
        return
    with open(path(home), "w") as f:
        f.writelines(f"{k} {v}\n" for k, v in keep)


def brew(home):
    """Homebrew packages this program installed, the AI engine last so Docker goes in one go."""
    names = [v for k, v in load(home) if k == "brew"]
    return sorted(names, key=lambda n: n == "ollama")
