"""The hardware probe against recorded output from four kinds of machine, plus tools that are missing or broken."""
import unittest

from harness import ROOT  # noqa: F401  (puts the repo on sys.path)
from core import hardware

KB = 1024


def machine(files=None, cmds=None):
    files, cmds = files or {}, cmds or {}
    return dict(sh=lambda c: cmds.get(c[0]) if c[0] not in cmds or not callable(cmds[c[0]]) else cmds[c[0]](c), read=files.get,
                which=lambda n: "/usr/bin/" + n if n in (cmds.get("_which") or ()) else None, disk_path="/")


PI = dict(system="Linux", release="6.1.0-rpi", machine="aarch64", **machine(
    {"/proc/cpuinfo": "processor : 0\nprocessor : 1\nprocessor : 2\nprocessor : 3\nModel : Raspberry Pi 4 Model B Rev 1.4\n",
     "/proc/meminfo": f"MemTotal:  {3800 * 1024} kB\n", "/proc/device-tree/model": "Raspberry Pi 4 Model B Rev 1.4\x00"},
    {"lspci": "", "_which": ("docker",)}))
NVIDIA = dict(system="Linux", release="6.8.0-generic", machine="x86_64", **machine(
    {"/proc/cpuinfo": "".join(f"processor : {i}\nmodel name : Fake CPU 9000\n" for i in range(16)), "/proc/meminfo": f"MemTotal: {32 * 1024 * 1024} kB\n"},
    {"nvidia-smi": "Fake RTX 4070, 12282\n", "_which": ("docker", "ollama")}))
M2 = dict(system="Darwin", release="24.6.0", machine="arm64", **machine(
    None, {"sysctl": lambda c: {"hw.memsize": str(16 * 1024 ** 3), "hw.ncpu": "8", "machdep.cpu.brand_string": "Apple M2"}[c[2]],
           "system_profiler": "Graphics/Displays:\n    Apple M2:\n      Chipset Model: Apple M2\n", "_which": ("docker",)}))
LAPTOP = dict(system="Linux", release="5.15.0-microsoft-standard-WSL2", machine="x86_64", **machine(
    {"/proc/cpuinfo": "".join(f"processor : {i}\nmodel name : Fake CPU 1\n" for i in range(4)), "/proc/meminfo": f"MemTotal: {8 * 1024 * 1024} kB\n"},
    {"lspci": "00:02.0 VGA compatible controller: Intel Corporation Fake Graphics\n"}))


class Probe(unittest.TestCase):
    def test_raspberry_pi(self):
        r = hardware.probe(**PI)
        self.assertEqual((r["os"], r["arch"], r["cores"], r["ram_gb"], r["gpu"]["kind"]), ("linux", "arm64", 4, 4, "none"))
        self.assertIn("Raspberry Pi", r["model"])
        self.assertTrue(r["docker"])
        self.assertFalse(r["ollama"])

    def test_nvidia_desktop(self):
        r = hardware.probe(**NVIDIA)
        self.assertEqual((r["arch"], r["cores"], r["ram_gb"], r["gpu"]["kind"], r["gpu"]["vram_gb"]), ("amd64", 16, 32, "nvidia", 12))
        self.assertTrue(r["ollama"])

    def test_apple_silicon(self):
        r = hardware.probe(**M2)
        self.assertEqual((r["os"], r["arch"], r["cores"], r["ram_gb"], r["gpu"]["kind"]), ("mac", "arm64", 8, 16, "apple"))

    def test_wsl_laptop_with_integrated_graphics(self):
        r = hardware.probe(**LAPTOP)
        self.assertEqual((r["os"], r["gpu"]["kind"], r["ram_gb"]), ("wsl", "intel", 8))

    def test_missing_tools_give_unknown_not_errors(self):
        r = hardware.probe(system="Linux", release="6", machine="x86_64", sh=lambda c: None, read=lambda p: None, which=lambda n: None, disk_path="/")
        self.assertEqual((r["cores"], r["ram_gb"], r["gpu"]["kind"], r["docker"]), (None, None, "unknown", False))
        self.assertIsInstance(hardware.describe(r), str)

    def test_a_missing_command_is_not_an_error(self):
        self.assertIsNone(hardware._sh(["definitely-not-a-command-xyz"]))

    def test_the_real_machine_can_be_probed(self):
        r = hardware.probe()
        self.assertIn(r["os"], ("linux", "mac", "wsl", "other"))

    def test_describe(self):
        self.assertEqual(hardware.describe(hardware.probe(**M2)).split(",")[0], "16 GB memory")


class SavedByTheInstaller(unittest.TestCase):
    """Inside Docker the probe sees the container's small virtual machine, so the installer saves what the real machine is."""

    def setUp(self):
        import tempfile, shutil
        self.d = tempfile.mkdtemp(prefix="hl-hw-")
        self.addCleanup(shutil.rmtree, self.d, ignore_errors=True)

    def test_the_saved_machine_wins_over_the_containers_view(self):
        hardware.save(self.d, hardware.probe(**M2))
        v = hardware.view(data_dir=self.d)
        self.assertEqual((v["hardware"]["os"], v["hardware"]["ram_gb"]), ("mac", 16))
        self.assertTrue(v["summary"].startswith("16 GB memory"))

    def test_nothing_saved_or_a_damaged_file_means_probe_for_itself(self):
        self.assertIsNone(hardware.load_host(self.d))
        open(f"{self.d}/{hardware.FILE}", "w").write("garbage")
        self.assertIsNone(hardware.load_host(self.d))
        open(f"{self.d}/{hardware.FILE}", "w").write('{"os": "plan9", "arch": "x", "cores": 1, "ram_gb": 1, "disk_free_gb": 1, "gpu": {"kind": "none"}}')
        self.assertIsNone(hardware.load_host(self.d))
        open(f"{self.d}/{hardware.FILE}", "w").write('{"os": "mac", "arch": "arm64", "cores": "lots", "ram_gb": 1, "disk_free_gb": 1, "gpu": {"kind": "none"}}')
        self.assertIsNone(hardware.load_host(self.d))
        self.assertIn(hardware.view(data_dir=self.d)["hardware"]["os"], ("linux", "mac", "wsl", "other"))

    def test_saving_to_an_unwritable_place_is_not_an_error(self):
        self.assertIsNone(hardware.save("/proc/definitely/not/here", hardware.probe(**M2)))


if __name__ == "__main__":
    unittest.main()
