"""What the host helper writes for the Server page: real Mac and Linux command output in, only the readings that worked out."""
import json
import unittest

import harness  # noqa: F401  (puts core on the path)
from core import hostinfo

MAC_DF = """Filesystem     1024-blocks      Used Available Capacity  Mounted on
/dev/disk3s1s1   482797652  10000000 175781250     6%    /
devfs                  200       200         0   100%    /dev
/dev/disk3s5     482797652 300000000 175781250    64%    /System/Volumes/Data
/dev/disk3s6     482797652   2000000 175781250     2%    /System/Volumes/VM
map auto_home            0         0         0   100%    /System/Volumes/Data/home
/dev/disk5s1     976562500 390625000 585937500    40%    /Volumes/Backup Drive
/dev/disk6s1        102400     51200     51200    50%    /Volumes/Tiny Installer"""
VM_STAT = """Mach Virtual Memory Statistics: (page size of 16384 bytes)
Pages free:                               10000.
Pages active:                            300000.
Pages wired down:                        100000.
Pages purgeable:                          20000.
Anonymous pages:                         400000.
Pages occupied by compressor:             50000."""
PROFILE = {"SPHardwareDataType": [{"machine_name": "MacBook Pro", "machine_model": "Mac15,6", "chip_type": "Apple M3 Pro", "number_processors": "proc 12:6:6",
                                   "physical_memory": "18 GB", "boot_rom_version": "1.0"}],
           "SPDisplaysDataType": [{"sppci_model": "Apple M3 Pro", "sppci_cores": "18"}], "SPMemoryDataType": [{"dimm_type": "LPDDR5", "dimm_manufacturer": "Micron"}],
           "SPPowerDataType": [{"sppower_battery_health_info": {"sppower_battery_cycle_count": 112, "sppower_battery_health": "Normal", "sppower_battery_health_maximum_capacity": "96%"},
                                "sppower_battery_charge_info": {"sppower_battery_state_of_charge": 80, "sppower_battery_is_charging": "TRUE"}}],
           "SPSoftwareDataType": [{"os_version": "macOS 15.1 (24B83)"}],
           "SPNVMeDataType": [{"_items": [{"device_model": "APPLE SSD AP0512Z", "size_in_bytes": 500277790720, "smart_status": "Verified"}]}]}


def fake(outputs):
    def run(cmd, timeout=20):
        for key, out in outputs.items():
            if " ".join(cmd).startswith(key):
                return out
        return ""
    return run


class Mac(unittest.TestCase):
    sh = staticmethod(fake({"system_profiler": json.dumps(PROFILE), "df": MAC_DF, "vm_stat": VM_STAT, "sysctl -n hw.memsize": "19327352832",
                             "sysctl -n kern.boottime": "{ sec = 1000, usec = 0 } Thu", "top": "CPU usage: 1% user, 1% sys, 98% idle\nCPU usage: 10.0% user, 5.0% sys, 85.0% idle",
                             "route -n get default": "   interface: en0", "ipconfig getifaddr en0": "192.0.2.10",
                             "networksetup": "Hardware Port: Wi-Fi\nDevice: en0\nEthernet Address: x\n", "docker --version": "Docker version 27.3.1, build x"}))

    def test_specs_name_the_machine_chip_memory_drive_and_battery(self):
        s = hostinfo.specs("mac", self.sh)
        self.assertEqual((s["device"]["name"], s["cpu"]["model"], s["cpu"]["perf_cores"], s["cpu"]["eff_cores"]), ("MacBook Pro", "Apple M3 Pro", 6, 6))
        self.assertEqual((s["memory"]["total_gb"], s["memory"]["type"], s["gpu"]["cores"]), (18, "LPDDR5", 18))
        self.assertEqual(s["drives"][0]["model"], "APPLE SSD AP0512Z")
        self.assertEqual((s["battery"]["max_pct"], s["battery"]["charging"]), (96, True))
        self.assertEqual((s["software"]["os"], s["network"]["connection"], s["network"]["lan_ip"]), ("macOS 15.1", "Wi-Fi", "192.0.2.10"))
        self.assertNotIn("tailnet_ip", s["network"])  # a reading that is not there is left out, never shown empty

    def test_volumes_are_your_data_and_external_drives_not_system_mounts(self):
        v = hostinfo.volumes("mac", self.sh)
        self.assertEqual([(x["name"], x["external"]) for x in v], [("Macintosh HD", False), ("Backup Drive", True)])
        self.assertEqual(v[0]["free"], 175781250 * 1024)

    def test_live_numbers(self):
        live = hostinfo.Live("mac", self.sh, now=lambda: 1000 + 86400).read_all()
        self.assertEqual((live["cpu_pct"], live["uptime"], live["mem_total"]), (15.0, 86400, 19327352832))
        self.assertEqual(live["mem_used"], (400000 - 20000 + 100000 + 50000) * 16384)
        self.assertNotIn("temp", live)


class Linux(unittest.TestCase):
    def test_cpu_use_comes_from_two_readings_and_memory_from_what_is_available(self):
        stats = iter(["cpu 100 0 100 800 0 0 0 0", "cpu 150 0 150 900 0 0 0 0"])
        files = {"/proc/meminfo": "MemTotal: 1000 kB\nMemAvailable: 250 kB", "/proc/uptime": "3600.5 100"}
        live = hostinfo.Live("linux", fake({}), read=lambda p: next(stats) if p == "/proc/stat" else files.get(p, ""))
        self.assertIsNone(live.cpu_pct())
        self.assertEqual(live.cpu_pct(), 50.0)
        self.assertEqual(live.memory(), (750 * 1024, 1000 * 1024))
        self.assertEqual(live.uptime(), 3600)

    def test_volumes_skip_virtual_and_tiny_mounts(self):
        df = """Filesystem 1024-blocks Used Available Capacity Mounted on
/dev/nvme0n1p2 488000000 100000000 388000000 21% /
tmpfs 8000000 0 8000000 0% /run
/dev/nvme0n1p1 524288 6000 518288 2% /boot/efi
/dev/loop3 65536 65536 0 100% /snap/core/1
/dev/sda1 976000000 500000000 476000000 52% /mnt/backup"""
        v = hostinfo.volumes("linux", fake({"df": df}))
        self.assertEqual([(x["name"], x["external"]) for x in v], [("System", False), ("backup", True)])


if __name__ == "__main__":
    unittest.main()
