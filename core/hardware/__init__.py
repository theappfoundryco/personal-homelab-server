"""What machine is this? Reads CPU, memory, disk, graphics card and OS, so the setup can suggest models that fit.
It only reads. Every command is optional: a tool that is missing or fails gives "unknown" for that field, never an error.
Tests pass their own `sh` and `read` to describe any machine without having it."""
import json
import os
import platform
import re
import shutil
import subprocess
import sys

GB = 1024 ** 3


def _sh(cmd, timeout=8):
    """Output of a command, or None if it is missing, fails or hangs."""
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


def _num(text, default=None):
    try:
        return int(text.strip())
    except (AttributeError, ValueError):
        return default


def _arch(machine):
    m = (machine or "").lower()
    return "arm64" if m in ("arm64", "aarch64") else "amd64" if m in ("x86_64", "amd64") else m or "unknown"


def _os(system, release):
    if system == "Darwin":
        return "mac"
    if system == "Linux":
        return "wsl" if "microsoft" in (release or "").lower() else "linux"
    return "other"


def _cores_ram_linux(read, sh):
    cpu, mem = read("/proc/cpuinfo") or "", read("/proc/meminfo") or ""
    cores = len(re.findall(r"^processor\s*:", cpu, re.M)) or _num(sh(["nproc"]))
    m = re.search(r"^MemTotal:\s+(\d+) kB", mem, re.M)
    model = re.search(r"^(?:Model|model name)\s*:\s*(.+)$", cpu, re.M)
    return cores, int(m.group(1)) * 1024 if m else None, (model.group(1).strip() if model else None)


def _cores_ram_mac(sh):
    ram = _num(sh(["sysctl", "-n", "hw.memsize"]))
    return _num(sh(["sysctl", "-n", "hw.ncpu"])), ram, (sh(["sysctl", "-n", "machdep.cpu.brand_string"]) or "").strip() or None


def _gpu_linux(sh):
    out = sh(["nvidia-smi", "--query-gpu=name,memory.total", "--format=csv,noheader,nounits"])
    if out and out.strip():
        name, _, mb = out.strip().splitlines()[0].partition(",")
        return {"kind": "nvidia", "name": name.strip(), "vram_gb": round((_num(mb, 0) or 0) / 1024)}
    out = sh(["lspci"])
    if out is None:
        return {"kind": "unknown", "name": None, "vram_gb": None}
    for line in out.splitlines():
        if re.search(r"VGA|3D|Display", line):
            kind = "nvidia" if re.search(r"nvidia", line, re.I) else "amd" if re.search(r"AMD|ATI|Radeon", line) else "intel" if "Intel" in line else "other"
            return {"kind": kind, "name": line.split(": ", 1)[-1].strip(), "vram_gb": None}
    return {"kind": "none", "name": None, "vram_gb": None}


def _gpu_mac(sh, arch):
    out = sh(["system_profiler", "SPDisplaysDataType"]) or ""
    m = re.search(r"Chipset Model:\s*(.+)", out)
    name = m.group(1).strip() if m else None
    if arch == "arm64":  # the graphics chip shares the main memory
        return {"kind": "apple", "name": name or "Apple silicon", "vram_gb": None}
    return {"kind": "amd" if name and re.search("AMD|Radeon", name) else "intel" if name else "unknown", "name": name, "vram_gb": None}


def probe(sh=_sh, read=_read, system=None, release=None, machine=None, disk_path=None, which=shutil.which):
    """A dict: os (linux/mac/wsl/other), arch, model, cores, ram_gb, disk_free_gb, gpu {kind,name,vram_gb}, docker, ollama.
    A field that could not be read is None."""
    system = system or platform.system()
    release = release if release is not None else platform.release()
    arch = _arch(machine or platform.machine())
    os_ = _os(system, release)
    if os_ == "mac":
        cores, ram, model = _cores_ram_mac(sh)
        gpu = _gpu_mac(sh, arch)
    elif os_ in ("linux", "wsl"):
        cores, ram, model = _cores_ram_linux(read, sh)
        gpu = _gpu_linux(sh)
        board = (read("/proc/device-tree/model") or "").strip("\x00\n ")
        model = board or model
    else:
        cores, ram, model, gpu = os.cpu_count(), None, None, {"kind": "unknown", "name": None, "vram_gb": None}
    try:
        free = round(shutil.disk_usage(disk_path or os.path.expanduser("~")).free / GB)
    except OSError:
        free = None
    return {"os": os_, "arch": arch, "model": model, "cores": cores, "ram_gb": round(ram / GB) if ram else None,
            "disk_free_gb": free, "gpu": gpu, "docker": bool(which("docker")), "ollama": bool(which("ollama"))}


def describe(hw):
    """One line for people: '16 GB memory, 8 cores, Apple silicon, 180 GB free'."""
    bits = [f"{hw['ram_gb']} GB memory" if hw["ram_gb"] else "memory unknown", f"{hw['cores']} cores" if hw["cores"] else None,
            hw["gpu"]["name"] if hw["gpu"]["kind"] not in ("none", "unknown") and hw["gpu"]["name"] else None,
            f"{hw['disk_free_gb']} GB free" if hw["disk_free_gb"] is not None else None]
    return ", ".join(b for b in bits if b)


def render(view):
    """The probe and its suggestions as plain text for a terminal. `view` is boot.hardware_view()."""
    r = view["recommendation"]
    out = [f"This machine: {view['summary']}", f"Profile: {r['title']}. {r['about']}"]
    if (view.get("hardware") or {}).get("ram_gb") is None:
        out.append("Memory could not be read, so the safest profile is shown. Nothing is switched off because of it.")
    out.append("")
    if r["models"]:
        out.append("Suggested AI models")
        for m in r["models"]:
            out.append(f"  {m['name']} ({m['role']}, {m['size_gb']} GB download)")
            out += [f"    Warning: {w}" for w in m["warnings"]]
        out.append(f"  Total download: about {r['download_gb']} GB")
    else:
        out.append("Local AI is not suggested on this machine. You can skip it, or point to another machine's Ollama.")
    out.append(f"Speech to text: {r['whisper']}. Keep {r['metrics_days']} days of metrics.")
    return "\n".join(out)


FILE = "host-hardware.json"  # written by the installer on the real machine; inside a container the probe only sees the container's small virtual machine
_OS = ("linux", "mac", "wsl", "other")


def save(data_dir, hw=None):
    """Remembers the machine as the installer saw it, so the app can show the real hardware. Returns the path, or None if it could not be written."""
    path = os.path.join(data_dir, FILE)
    try:
        os.makedirs(data_dir, exist_ok=True)
        with open(path + ".tmp", "w") as f:
            json.dump(hw or probe(), f)
        os.replace(path + ".tmp", path)
        return path
    except OSError:
        return None


def load_host(data_dir):
    """The saved host probe, or None when it is missing or does not look right (then the app probes for itself)."""
    try:
        with open(os.path.join(data_dir, FILE)) as f:
            hw = json.load(f)
        num = lambda v: v is None or (isinstance(v, (int, float)) and not isinstance(v, bool))
        gpu = hw["gpu"]
        ok = (hw["os"] in _OS and isinstance(hw["arch"], str) and all(num(hw[k]) for k in ("cores", "ram_gb", "disk_free_gb"))
              and isinstance(gpu, dict) and isinstance(gpu.get("kind"), str) and num(gpu.get("vram_gb")))
        return {**hw, "docker": bool(hw.get("docker")), "ollama": bool(hw.get("ollama"))} if ok else None
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        return None


def view(disk_path=None, data_dir=None):
    """The probe plus a one-line summary and the profile with its suggestions: what the CLI, /hardware and the doctor show.
    A probe saved by the installer wins over probing from inside a container."""
    from core.hardware import profiles
    hw = (load_host(data_dir) if data_dir else None) or probe(disk_path=disk_path)
    return {"hardware": hw, "summary": describe(hw), "recommendation": profiles.recommend(hw)}
