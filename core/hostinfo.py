"""What this machine is and how it is doing, for the Server page: written by the host helper (which runs on the machine itself,
so it sees the real Mac or PC, not Docker's small VM) to host.json in the stats folder.

specs() is slow-changing (chip, memory, disks, battery) and is read every few minutes; live() is cheap and read every few seconds.
Every field is optional: a reading that fails is left out, and the page shows what is there. Standard library only."""
import json
import os
import re
import subprocess
import time as _time

SKIP_FS = {"tmpfs", "devtmpfs", "overlay", "squashfs", "efivarfs", "devfs", "autofs", "proc", "sysfs", "nullfs", "ramfs", "fuse.lxcfs"}


def sh(cmd, timeout=20):
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return r.stdout.strip() if r.returncode == 0 else ""
    except (OSError, subprocess.SubprocessError):
        return ""


def rd(path):
    try:
        with open(path) as f:
            return f.read().strip()
    except OSError:
        return ""


def _num(text, default=None):
    m = re.search(r"[\d.]+", str(text or ""))
    try:
        return float(m.group(0)) if m else default
    except ValueError:
        return default


def _clean(d):
    """Drops empty values, so the page never shows a label with nothing after it."""
    if isinstance(d, dict):
        out = {k: _clean(v) for k, v in d.items()}
        return {k: v for k, v in out.items() if v not in (None, "", [], {})}
    if isinstance(d, list):
        return [x for x in (_clean(v) for v in d) if x not in (None, "", [], {})]
    return d


# ---------- disks: every real volume, internal and external

def volumes(platform, run=sh):
    """[{name, mount, size, free, external}] from df, leaving out system and virtual mounts."""
    out, seen = [], set()
    for line in run(["df", "-kP"]).splitlines()[1:]:
        parts = line.split()
        if len(parts) < 6:
            continue
        dev, size, _used, free, mount = parts[0], parts[1], parts[2], parts[3], " ".join(parts[5:])
        if platform == "mac":
            if mount == "/System/Volumes/Data":
                name, ext = "Macintosh HD", False  # the data half of the startup disk holds the space you use
            elif mount.startswith("/Volumes/"):
                name, ext = mount[len("/Volumes/"):], True
            else:
                continue
        else:
            if not dev.startswith("/dev/") or dev.startswith(("/dev/loop", "/dev/zram")) or mount.startswith(("/boot", "/snap", "/var/lib/docker")):
                continue
            name, ext = ("System" if mount == "/" else os.path.basename(mount) or mount), mount.startswith(("/media/", "/mnt/", "/run/media/"))
        if dev in seen and platform != "mac":
            continue
        seen.add(dev)
        try:
            if int(size) * 1024 >= 2 ** 30:  # anything under 1 GB is a tool's own small mount, not storage you use
                out.append({"name": name, "mount": mount, "size": int(size) * 1024, "free": int(free) * 1024, "external": ext})
        except ValueError:
            continue
    return out


# ---------- slow facts

def _mac_profile(run):
    try:
        return json.loads(run(["system_profiler", "-json", "SPHardwareDataType", "SPDisplaysDataType", "SPMemoryDataType", "SPPowerDataType",
                               "SPSoftwareDataType", "SPNVMeDataType", "SPStorageDataType"], ) or "{}")
    except ValueError:
        return {}


def mac_specs(run=sh):
    p = _mac_profile(run)
    hw = (p.get("SPHardwareDataType") or [{}])[0]
    sysctl = lambda k: run(["sysctl", "-n", k])
    chip = hw.get("chip_type") or sysctl("machdep.cpu.brand_string")
    procs = re.findall(r"\d+", hw.get("number_processors") or "")  # "proc 12:6:6" -> all, performance, efficiency
    perf, eff = sysctl("hw.perflevel0.physicalcpu"), sysctl("hw.perflevel1.physicalcpu")
    gpu = next((g for g in p.get("SPDisplaysDataType") or [] if g.get("sppci_model")), {})
    mem = (p.get("SPMemoryDataType") or [{}])[0]
    power = next((x for x in p.get("SPPowerDataType") or [] if x.get("sppower_battery_health_info")), {})
    health, charge = power.get("sppower_battery_health_info") or {}, power.get("sppower_battery_charge_info") or {}
    sw = (p.get("SPSoftwareDataType") or [{}])[0]
    drives = []
    for d in (p.get("SPNVMeDataType") or []):
        for x in d.get("_items") or []:
            drives.append({"model": x.get("device_model") or x.get("_name"), "size": x.get("size_in_bytes"), "kind": "NVMe SSD",
                           "health_ok": (x.get("smart_status") or "").lower() in ("verified", ""), "internal": True})
    if not drives:
        for v in p.get("SPStorageDataType") or []:
            pd = v.get("physical_drive") or {}
            if pd.get("is_internal_disk") == "yes" and pd.get("device_name") and pd["device_name"] not in [x["model"] for x in drives]:
                drives.append({"model": pd["device_name"], "kind": f"{pd.get('medium_type', '').upper()} {pd.get('protocol', '')}".strip(),
                               "health_ok": (pd.get("smart_status") or "").lower() in ("verified", ""), "internal": True})
    total = _num(hw.get("physical_memory")) or round(int(sysctl("hw.memsize") or 0) / 2 ** 30)
    docker = re.search(r"version ([\d.]+)", run(["docker", "--version"]))
    return {
        "device": {"name": hw.get("machine_name") or "Mac", "model": hw.get("machine_model") or sysctl("hw.model"), "maker": "Apple",
                   "firmware": hw.get("boot_rom_version")},
        "cpu": {"model": chip, "cores": int(procs[0]) if procs else int(sysctl("hw.physicalcpu") or 0) or None,
                "threads": int(sysctl("hw.logicalcpu") or 0) or None,
                "perf_cores": int(procs[1]) if len(procs) > 1 else int(perf or 0) or None, "eff_cores": int(procs[2]) if len(procs) > 2 else int(eff or 0) or None},
        "gpu": {"model": gpu.get("sppci_model"), "cores": int(gpu["sppci_cores"]) if str(gpu.get("sppci_cores", "")).isdigit() else None},
        "memory": {"total_gb": int(total) if total else None, "type": mem.get("dimm_type"), "maker": mem.get("dimm_manufacturer"), "unified": bool(chip and "Apple" in chip)},
        "drives": drives,
        "battery": {"cycles": health.get("sppower_battery_cycle_count"), "condition": health.get("sppower_battery_health"),
                    "max_pct": _num(health.get("sppower_battery_health_maximum_capacity")), "charge_pct": charge.get("sppower_battery_state_of_charge"),
                    "charging": charge.get("sppower_battery_is_charging") == "TRUE"} if power else None,
        "software": {"os": (sw.get("os_version") or "macOS " + run(["sw_vers", "-productVersion"])).split(" (")[0], "kernel": os.uname().release,
                     "docker": docker.group(1) if docker else None},
    }


def linux_specs(run=sh, read=rd):
    lscpu = run(["lscpu"])
    get = lambda k: (re.search(rf"^{re.escape(k)}:\s*(.+)$", lscpu, re.M) or [None, ""])[1].strip()
    name = get("Model name")
    sockets = int(get("Socket(s)") or 1)
    cores = int(get("Core(s) per socket") or 0) * sockets or None
    gpu = (re.search(r"(?:VGA compatible controller|3D controller)[^:]*: (.+)", run(["lspci"])) or [None, ""])[1]
    gpu = re.sub(r"\s*\(rev \w+\)", "", (re.search(r"\[(.+)\]", gpu) or [None, gpu])[1]).strip()
    meminfo = read("/proc/meminfo")
    kb = int((re.search(r"MemTotal:\s+(\d+)", meminfo) or [0, 0])[1])
    drives = []
    try:
        for b in json.loads(run(["lsblk", "-J", "-b", "-d", "-o", "NAME,MODEL,SIZE,ROTA,TRAN,TYPE,RM"]) or "{}").get("blockdevices", []):
            if b.get("type") != "disk" or str(b.get("name", "")).startswith(("loop", "zram", "ram")) or int(b.get("size") or 0) < 2 ** 30:
                continue
            kind = "NVMe SSD" if b.get("tran") == "nvme" or str(b["name"]).startswith("nvme") else "USB drive" if b.get("tran") == "usb" else "Hard drive" if b.get("rota") in (True, "1", 1) else "SSD"
            drives.append({"model": (b.get("model") or b["name"]).strip(), "size": b.get("size"), "kind": kind, "internal": not b.get("rm") and b.get("tran") != "usb"})
    except ValueError:
        pass
    osr = dict(re.findall(r'^(\w+)="?([^"\n]*)"?$', read("/etc/os-release"), re.M))
    docker = re.search(r"version ([\d.]+)", run(["docker", "--version"]))
    bat = "/sys/class/power_supply/BAT0"
    full, design = _num(read(f"{bat}/energy_full") or read(f"{bat}/charge_full")), _num(read(f"{bat}/energy_full_design") or read(f"{bat}/charge_full_design"))
    return {
        "device": {"name": read("/sys/class/dmi/id/product_name"), "maker": read("/sys/class/dmi/id/sys_vendor"),
                   "firmware": " ".join(x for x in (read("/sys/class/dmi/id/bios_version"), read("/sys/class/dmi/id/bios_date")) if x)},
        "cpu": {"model": " ".join(re.sub(r"\(R\)|\(TM\)|CPU|@.*", "", name).split()), "cores": cores, "threads": int(get("CPU(s)") or 0) or None,
                "max_ghz": round(float(get("CPU max MHz") or 0) / 1000, 1) or None, "cache": get("L3 cache").split(" (")[0],
                "virt": get("Virtualization")},
        "gpu": {"model": gpu},
        "memory": {"total_gb": round(kb / 2 ** 20) if kb else None},
        "drives": drives,
        "battery": {"cycles": _num(read(f"{bat}/cycle_count")), "max_pct": round(full / design * 100) if full and design else None,
                    "charge_pct": _num(read(f"{bat}/capacity")), "charging": read(f"{bat}/status") == "Charging"} if os.path.isdir(bat) else None,
        "software": {"os": osr.get("PRETTY_NAME"), "kernel": os.uname().release, "docker": docker.group(1) if docker else None},
    }


def network(platform, run=sh):
    if platform == "mac":
        iface = (re.search(r"interface:\s*(\S+)", run(["route", "-n", "get", "default"])) or [None, ""])[1]
        ip = run(["ipconfig", "getifaddr", iface]) if iface else ""
    else:
        r = run(["ip", "-4", "route", "get", "1.1.1.1"])
        iface, ip = (re.search(r"dev (\S+)", r) or [None, ""])[1], (re.search(r"src ([\d.]+)", r) or [None, ""])[1]
    port = ""
    if platform == "mac" and iface:  # blocks of "Hardware Port: Wi-Fi / Device: en0"
        port = (re.search(rf"Hardware Port: ([^\n]+)\nDevice: {re.escape(iface)}\n", run(["networksetup", "-listallhardwareports"])) or [None, ""])[1]
    kind = "Wi-Fi" if iface.startswith(("wl", "wlan")) or port == "Wi-Fi" else "Ethernet" if iface else ""
    return {"connection": kind, "lan_ip": ip, "tailnet_ip": run(["tailscale", "ip", "-4"]).split("\n")[0]}


def specs(platform, run=sh, read=rd):
    s = mac_specs(run) if platform == "mac" else linux_specs(run, read)
    s["network"] = network(platform, run)
    s["platform"] = platform
    return _clean(s)


# ---------- live numbers

class Live:
    """CPU use needs two readings; this keeps the last one between calls."""
    def __init__(self, platform, run=sh, read=rd, now=_time.time):
        self.platform, self.run, self.read, self.now, self.last = platform, run, read, now, None

    def cpu_pct(self):
        if self.platform == "mac":
            m = re.findall(r"CPU usage:.*?([\d.]+)% idle", self.run(["top", "-l", "2", "-n", "0", "-s", "1"]))
            return round(100 - float(m[-1]), 1) if m else None
        nums = [int(x) for x in (self.read("/proc/stat").splitlines() or [""])[0].split()[1:]]
        if len(nums) < 4:
            return None
        idle, total = nums[3] + (nums[4] if len(nums) > 4 else 0), sum(nums)
        last, self.last = self.last, (idle, total)
        if not last or total <= last[1]:
            return None
        return round(100 * (1 - (idle - last[0]) / (total - last[1])), 1)

    def memory(self):
        """(used bytes, total bytes), counting used the way the system's own monitor does."""
        if self.platform == "mac":
            vm, total = self.run(["vm_stat"]), int(self.run(["sysctl", "-n", "hw.memsize"]) or 0)
            page = int((re.search(r"page size of (\d+)", vm) or [0, 16384])[1])
            pages = lambda k: int((re.search(rf"{k}:\s+(\d+)", vm) or [0, 0])[1])
            app = pages("Anonymous pages") - pages("Pages purgeable") if "Anonymous pages" in vm else pages("Pages active")
            used = (app + pages("Pages wired down") + pages("Pages occupied by compressor")) * page
            return (used if used > 0 else None), total or None
        mi = self.read("/proc/meminfo")
        kb = lambda k: int((re.search(rf"{k}:\s+(\d+)", mi) or [0, 0])[1]) * 1024
        return (kb("MemTotal") - kb("MemAvailable")) or None, kb("MemTotal") or None

    def uptime(self):
        if self.platform == "mac":
            boot = re.search(r"sec = (\d+)", self.run(["sysctl", "-n", "kern.boottime"]))
            return int(self.now() - int(boot.group(1))) if boot else None
        up = _num(self.read("/proc/uptime"))
        return int(up) if up else None

    def temp(self):
        if self.platform == "mac":
            return None  # macOS only shares temperatures with root; the page leaves it out
        best = None
        for zone in sorted(os.listdir("/sys/class/thermal")) if os.path.isdir("/sys/class/thermal") else []:
            if "x86_pkg" in self.read(f"/sys/class/thermal/{zone}/type") or "cpu" in self.read(f"/sys/class/thermal/{zone}/type"):
                t = _num(self.read(f"/sys/class/thermal/{zone}/temp"))
                best = max(best or 0, t / 1000) if t else best
        return round(best) if best else None

    def read_all(self):
        used, total = self.memory()
        return _clean({"cpu_pct": self.cpu_pct(), "mem_used": used, "mem_total": total, "uptime": self.uptime(), "temp": self.temp(),
                       "load": (os.getloadavg()[0] if hasattr(os, "getloadavg") else None), "volumes": volumes(self.platform, self.run)})


def write(path, data):
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        json.dump(data, f)
    os.chmod(tmp, 0o644)
    os.replace(tmp, path)


def loop(stats_dir, platform, stop=lambda: False, every=15, specs_every=600, log=print, sleep=_time.sleep, now=_time.time):
    """Writes <stats>/host.json: the specs (refreshed every specs_every seconds) and the live numbers (every `every` seconds)."""
    os.makedirs(stats_dir, exist_ok=True)
    live, s, s_at = Live(platform), None, 0
    while not stop():
        try:
            if s is None or now() - s_at >= specs_every:
                s, s_at = specs(platform), now()
            write(os.path.join(stats_dir, "host.json"), {"generated": int(now()), "specs": s, "live": live.read_all()})
        except Exception as e:  # a reading that breaks must not stop the others next time
            log(f"host info: {e}")
        sleep(every)
