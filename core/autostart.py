"""Docker starting by itself after a restart, so the assistant comes back without anyone typing a command.
Colima on a Mac gets a small login item of ours (runs `colima start` once at login). OrbStack, Docker Desktop and Linux have their own switch; we say where it is."""
import os
import shutil

from core.agent import path_for_service

LABEL = "homelab.docker"


def runtime(run):
    """Which Docker this machine uses: colima, orbstack, desktop or linux. `run` returns (rc, output)."""
    rc, out = run(["docker", "context", "show"])
    name = (out or "").strip() if rc == 0 else ""
    if name == "colima" or name.startswith("colima-"):
        return "colima"
    if name == "orbstack":
        return "orbstack"
    if name == "desktop-linux":
        return "desktop"
    return "linux" if not os.path.exists("/Applications") else ("desktop" if os.path.isdir("/Applications/Docker.app") else "colima" if shutil.which("colima") else "unknown")


def plist_path(home):
    return os.path.join(home, "Library", "LaunchAgents", LABEL + ".plist")


def plist(colima, home):
    return ('<?xml version="1.0" encoding="UTF-8"?>\n<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">\n<plist version="1.0"><dict>\n'
            f"  <key>Label</key><string>{LABEL}</string>\n  <key>ProgramArguments</key><array><string>{colima}</string><string>start</string></array>\n"
            f"  <key>EnvironmentVariables</key><dict><key>PATH</key><string>{path_for_service(home)}</string></dict>\n"
            "  <key>RunAtLoad</key><true/>\n  <key>KeepAlive</key><false/>\n</dict></plist>\n")


def status(kind, home, run):
    """-> (on, how to change it)"""
    if kind == "colima":
        return os.path.exists(plist_path(home)), "homelab autostart on"
    if kind == "orbstack":
        return None, "OrbStack, Settings, General: turn on Start at login"
    if kind == "desktop":
        return None, "Docker Desktop, Settings, General: turn on Start Docker Desktop when you sign in"
    rc, out = run(["systemctl", "is-enabled", "docker"])
    return (rc == 0 and (out or "").strip() == "enabled"), "sudo systemctl enable docker"


def on(kind, home, which=shutil.which):
    """-> (done, message)"""
    if kind != "colima":
        return False, "This Docker has its own switch: " + status(kind, home, lambda c: (1, ""))[1] + "."
    colima = which("colima", path=path_for_service(home))
    if not colima:
        return False, "Colima was not found. Install it with: brew install colima"
    os.makedirs(os.path.dirname(plist_path(home)), exist_ok=True)
    with open(plist_path(home), "w") as f:
        f.write(plist(colima, home))
    return True, "Docker (Colima) now starts by itself when you log in, and the assistant with it."


def off(home):
    """Removes our login item. -> True if there was one."""
    try:
        os.remove(plist_path(home))
        return True
    except OSError:
        return False
