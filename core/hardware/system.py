"""Which platform is this machine: distribution, init system, Docker flavour, SELinux, container or VM, laptop or always on.
The installer runs detect() on the real machine and saves it with the hardware (host-hardware.json, key "platform"),
because the app inside Docker only sees its own container. checks() turns those facts into plain rows for the doctor:
works, limited (why) or unavailable here (why, and what would make it work). Something normal for a platform is never a problem.
Every reader is passed in, so the tests describe any machine from recorded files and command output."""
import os
import re
import shutil
import subprocess

# Distributions Docker's own installer (get.docker.com) supports, by os-release ID. It maps almalinux to alma and ol to oracle itself.
# Source: docker/docker-install install.sh, get_distribution() and the case in do_install(). It stops on everything else.
DOCKER_SCRIPT = {"ubuntu", "debian", "raspbian", "centos", "rhel", "rocky", "almalinux", "fedora", "ol"}

# Older releases get.docker.com still installs on, after a 10 second "end of life" warning (do_install, deprecation_notice). Fedora below 43 too.
DOCKER_EOL = {("debian", "11"), ("debian", "10"), ("ubuntu", "20.04"), ("ubuntu", "18.04"), ("centos", "8"), ("centos", "7"), ("rhel", "7")}

# Where Docker comes from when get.docker.com does not support the distribution: the distribution's own packages.
# family -> (packages command, start-at-boot command). Package names checked in each distribution's container (docs/research/platform-matrix.md).
DISTRO_DOCKER = {
    "arch": ("sudo pacman -S --needed --noconfirm docker docker-compose docker-buildx", "sudo systemctl enable --now docker"),
    "alpine": ("sudo apk add docker docker-cli-compose", "sudo rc-update add docker default && sudo rc-service docker start"),
    "suse": ("sudo zypper --non-interactive install docker docker-compose", "sudo systemctl enable --now docker"),
    "void": ("sudo xbps-install -Sy docker docker-compose", "sudo ln -sf /etc/sv/docker /var/service/"),
}
# No package we can install for you: say exactly what to do instead.
DOCKER_BY_HAND = {
    "nixos": "Docker is set up in your NixOS configuration: add  virtualisation.docker.enable = true;  then run  sudo nixos-rebuild switch",
    "gentoo": "Install Docker with:  sudo emerge --ask app-containers/docker app-containers/docker-compose  then start it with your init system.",
    "amzn": "Amazon Linux has Docker (sudo dnf install docker) but not its compose part. Install the compose plugin from https://docs.docker.com/compose/install/linux/",
}

# PyYAML from the system's own packages: pip is refused for the system Python on Ubuntu 23.04+, Debian 12+ and Fedora 38+.
PYYAML = {
    "debian": "sudo apt-get install -y python3-yaml", "rhel": "sudo dnf install -y python3-pyyaml", "fedora": "sudo dnf install -y python3-pyyaml",
    "amzn": "sudo dnf install -y python3-pyyaml", "suse": "sudo zypper install python3-PyYAML", "arch": "sudo pacman -S python-yaml",
    "alpine": "sudo apk add py3-yaml", "void": "sudo xbps-install -S python3-yaml",
}


def pyyaml_fix(read=None, system=None):
    """The command that installs PyYAML on this machine: the distribution's package on Linux, pip for the user elsewhere."""
    import platform as _platform
    system = system or _platform.system()
    if system == "Linux":
        cmd = PYYAML.get(family(parse_os_release((read or _read)("/etc/os-release"))))
        if cmd:
            return cmd
    return "python3 -m pip install --user pyyaml"


def parse_os_release(text):
    """/etc/os-release as a dict of its keys, quotes removed. ID_LIKE becomes a list. Empty dict for no text."""
    out = {}
    for line in (text or "").splitlines():
        m = re.match(r"\s*([A-Z_]+)=(.*)$", line)
        if m:
            v = m.group(2).strip()
            if len(v) >= 2 and v[0] == v[-1] and v[0] in "\"'":
                v = v[1:-1]
            out[m.group(1)] = v
    out["ID_LIKE"] = (out.get("ID_LIKE") or "").split()
    return out


def family(osr):
    """debian, rhel, fedora, suse, arch, alpine, void, gentoo, nixos, amzn or other: decides the package manager and the Docker source."""
    ids = [osr.get("ID", "")] + list(osr.get("ID_LIKE") or [])
    for i in ids:
        if i in ("debian", "ubuntu", "raspbian"):
            return "debian"
        if i == "amzn":
            return "amzn"
        if i == "fedora" and ids[0] == "fedora":
            return "fedora"
        if i in ("rhel", "centos", "rocky", "almalinux", "ol", "fedora"):
            return "rhel"
        if i.startswith("opensuse") or i in ("suse", "sles"):
            return "suse"
        if i in ("arch", "archarm", "manjaro"):
            return "arch"
        if i in ("alpine", "postmarketos"):
            return "alpine"
        if i in ("void", "gentoo", "nixos"):
            return i
    return "other"


def init_system(exists):
    """systemd, openrc, runit, launchd or none. Checks what is running, not what is installed (a container often has systemctl but no systemd)."""
    if exists("/System/Library/CoreServices/launchd") or exists("/sbin/launchd"):
        return "launchd"
    if exists("/run/systemd/system"):
        return "systemd"
    if exists("/run/openrc") or exists("/sbin/openrc-run") and exists("/run/openrc/softlevel"):
        return "openrc"
    if exists("/run/runit") or exists("/etc/runit/runsvdir"):
        return "runit"
    return "none"


def selinux(read):
    """enforcing, permissive or off."""
    v = (read("/sys/fs/selinux/enforce") or "").strip()
    return "enforcing" if v == "1" else "permissive" if v == "0" else "off"


def where(read, exists):
    """container, wsl or machine (a real machine or a full VM: both run everything)."""
    if "microsoft" in (read("/proc/sys/kernel/osrelease") or "").lower():
        return "wsl"
    if exists("/.dockerenv") or exists("/run/.containerenv"):
        return "container"
    cg = read("/proc/1/cgroup") or ""
    if re.search(r"/(docker|lxc|kubepods|containerd)[/-]", cg):
        return "container"
    return "machine"


LAPTOP_CHASSIS = {"8", "9", "10", "11", "14", "30", "31", "32"}  # SMBIOS chassis types: portable, laptop, notebook, hand held, sub notebook, tablet, convertible, detachable


def laptop(read, exists, listdir, sh=None, system="Linux"):
    """True when this machine has a battery or a laptop case: it may sleep, so timed jobs can be missed."""
    if system == "Darwin":
        out = (sh(["pmset", "-g", "batt"]) if sh else None) or ""
        return "InternalBattery" in out
    if (read("/sys/class/dmi/id/chassis_type") or "").strip() in LAPTOP_CHASSIS:
        return True
    try:
        return any(n.startswith("BAT") for n in listdir("/sys/class/power_supply"))
    except OSError:
        return False


def docker_flavour(info):
    """From `docker info` text: docker-desktop, orbstack, colima, podman, rootless, engine, or none when Docker did not answer."""
    if not info:
        return "none"
    if re.search(r"Operating System:\s*Docker Desktop", info):
        return "docker-desktop"
    if re.search(r"Operating System:\s*OrbStack", info) or re.search(r"Name:\s*orbstack", info):
        return "orbstack"
    if re.search(r"Name:\s*colima", info):
        return "colima"
    if re.search(r"podman", info, re.I):
        return "podman"
    if re.search(r"rootless", info):
        return "rootless"
    return "engine"


def docker_source(osr, system="Linux"):
    """How Docker gets onto this machine when it is missing: (how, command, note).
    how is script (get.docker.com), package (the distribution's own), by-hand (we say what to do) or mac (Colima with Homebrew)."""
    if system == "Darwin":
        return "mac", "", ""
    ident, fam, ver = osr.get("ID", ""), family(osr), osr.get("VERSION_ID", "")
    if (ident, ver) == ("ubuntu", "20.04"):  # get.docker.com stops here: it wants docker-model-plugin, which is not published for 20.04
        return "package", "sudo apt-get update -qq && sudo apt-get install -y docker.io docker-compose-v2 && sudo systemctl enable --now docker", \
            f"{osr.get('PRETTY_NAME') or 'Ubuntu 20.04'} has reached its end of life, and Docker's own installer no longer works on it, so Docker comes from Ubuntu's packages."
    if ident in DOCKER_SCRIPT:
        eol = (ident, ver.split(".")[0] if ident in ("debian", "centos", "rhel") else ver) in DOCKER_EOL or (ident == "fedora" and ver.isdigit() and int(ver) < 43)
        note = f"{osr.get('PRETTY_NAME') or ident} has reached its end of life. Docker still installs, but plan to upgrade." if eol else ""
        return "script", "curl -fsSL https://get.docker.com | sudo sh", note
    if fam in DISTRO_DOCKER:
        pkgs, boot = DISTRO_DOCKER[fam]
        return "package", f"{pkgs} && {boot}", ""
    for key in (ident, fam):
        if key in DOCKER_BY_HAND:
            return "by-hand", "", DOCKER_BY_HAND[key]
    if fam == "debian" and osr.get("UBUNTU_CODENAME"):  # built on Ubuntu, but get.docker.com does not know it by name (Mint, Pop!_OS, elementary, Zorin ...)
        return "package", "sudo apt-get update -qq && sudo apt-get install -y docker.io docker-compose-v2 && sudo systemctl enable --now docker", \
            "Docker comes from your distribution's packages, because Docker's own installer does not know this distribution by name."
    if fam == "debian":  # built on Debian: Debian 12 packages only the old docker-compose 1, without the  docker compose  command this needs
        return "by-hand", "", "Docker's installer does not know this distribution by name. Install Docker Engine and its compose plugin with Docker's Debian steps: https://docs.docker.com/engine/install/debian/"
    return "by-hand", "", f"Docker's installer does not support {osr.get('PRETTY_NAME') or ident or 'this system'}. Install Docker and its compose plugin with your package manager, then run install.sh again."


def _sh(cmd, timeout=8):
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return r.stdout if r.returncode == 0 else None
    except (OSError, subprocess.SubprocessError):
        return None


def _read(path):
    try:
        with open(path, errors="replace") as f:
            return f.read()
    except OSError:
        return None


def detect(read=_read, exists=os.path.exists, listdir=os.listdir, sh=_sh, which=shutil.which, system=None, user=None):
    """Everything above, for this machine. Never raises: a fact that cannot be read is empty or "unknown"."""
    import platform as _platform
    system = system or _platform.system()
    user = user or os.environ.get("USER") or ""
    osr = parse_os_release(read("/etc/os-release")) if system == "Linux" else {}
    info = sh(["docker", "info"]) if which("docker") else None
    compose = (sh(["docker", "compose", "version", "--short"]) or "").strip() if which("docker") else ""
    groups = (sh(["id", "-nG"]) or "").split()
    how, command, note = docker_source(osr, system)
    return {
        "system": "mac" if system == "Darwin" else system.lower(),
        "distro": osr.get("ID", ""), "like": osr.get("ID_LIKE", []), "version": osr.get("VERSION_ID", ""), "variant": osr.get("VARIANT_ID", ""),
        "pretty": osr.get("PRETTY_NAME", "") or ("macOS" if system == "Darwin" else system),
        "family": "mac" if system == "Darwin" else family(osr),
        "init": init_system(exists),
        "where": where(read, exists) if system == "Linux" else "machine",
        "selinux": selinux(read) if system == "Linux" else "off",
        "docker": docker_flavour(info), "compose": compose,
        "docker_group": "docker" in groups or system == "Darwin",
        "docker_source": {"how": how, "command": command, "note": note},
        "linger": bool(user) and exists(f"/var/lib/systemd/linger/{user}") if system == "Linux" else None,
        "laptop": laptop(read, exists, listdir, sh, system),
    }


def _row(name, title, state, why="", fix=""):
    return {"name": name, "title": title, "state": state, "why": why, "fix": fix}


def checks(p):
    """The platform as doctor rows: [{name, title, state (works, limited, unavailable), why, fix}]. p is detect() as saved by the installer, or None."""
    if not p:
        return [_row("platform", "This machine", "limited", "The installer has not recorded this machine's platform yet.", "Run install.sh again. It is safe to repeat.")]
    rows, mac = [], p.get("system") == "mac"
    init = p.get("init")
    if mac or init == "systemd":
        rows.append(_row("autostart", "Host helper and autostart", "works"))
    elif init == "openrc":
        rows.append(_row("autostart", "Host helper and autostart", "unavailable", "This machine uses OpenRC. The host helper is a systemd user service.",
                         "Start it after a restart with: homelab start. Restart and Update in the dashboard need the helper, so use homelab restart and homelab update."))
    else:
        rows.append(_row("autostart", "Host helper and autostart", "unavailable", "No systemd or launchd is running here" + (" (this is a container)" if p.get("where") == "container" else "") + ".",
                         "Start it with: homelab start. Restart and Update in the dashboard need the helper, so use homelab restart and homelab update."))
    if init == "systemd" and p.get("linger") is False:
        rows.append(_row("linger", "Keep running after you log out", "limited", "When you log out, systemd stops your services, the host helper with them.",
                         "Run once: sudo loginctl enable-linger $USER"))
    if p.get("where") == "wsl":
        rows.append(_row("wsl", "Windows (WSL2)", "unavailable", "Windows is not supported yet.", "Run it on a Linux machine or a Mac."))
    if not p.get("docker_group", True) and p.get("docker") == "none":
        rows.append(_row("docker_group", "Docker for your user", "limited", "You were added to the docker group, but this login started before that.",
                         "Log out and back in (or restart), then run the command again."))
    if p.get("docker") == "podman":
        rows.append(_row("docker", "Docker", "limited", "This is Podman with Docker's commands. The core apps run, but the host helper, Restart and the Docker reader expect Docker Engine.",
                         "Install Docker Engine for everything to work."))
    elif p.get("docker") == "rootless":
        rows.append(_row("docker", "Docker", "limited", "Docker runs rootless here. Apps that read the whole machine (node-exporter, cAdvisor) show less.", ""))
    if p.get("selinux") == "enforcing":
        rows.append(_row("selinux", "SELinux", "limited", "SELinux is enforcing, so containers may be refused access to the project's folders.",
                         "If an app cannot read its config, see docs/research/platform-matrix.md (SELinux). Do not turn SELinux off for this."))
    if p.get("laptop"):
        rows.append(_row("always_on", "Always on", "limited", "This looks like a laptop. While it sleeps, reminders, the morning briefing and backups wait.",
                         "Keep it plugged in with sleep off, or run it on a machine that stays on."))
    src = p.get("docker_source") or {}
    if src.get("note"):
        rows.append(_row("distro", p.get("pretty") or "Distribution", "limited", src["note"], ""))
    return rows
