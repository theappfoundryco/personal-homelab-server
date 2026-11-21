"""The platform profile (core/hardware/system.py): distribution, init system, Docker flavour and source, and the doctor rows.
Every distribution case reads a real /etc/os-release recorded from that distribution's official container image (tests/fixtures/os-release)."""
import os
import unittest

import harness  # noqa: F401  (puts core on the path)
from core.hardware import system

FIX = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures")


def osr(name):
    with open(os.path.join(FIX, "os-release", name)) as f:
        return system.parse_os_release(f.read())


def info(name):
    with open(os.path.join(FIX, "docker-info", name)) as f:
        return f.read()


def files(*present):
    return lambda p: p in present


class Distributions(unittest.TestCase):
    def test_every_recorded_distribution_gets_the_right_family(self):
        want = {"debian-11": "debian", "debian-12": "debian", "debian-13": "debian", "ubuntu-20.04": "debian", "ubuntu-22.04": "debian", "ubuntu-24.04": "debian",
                "fedora-40": "fedora", "fedora-41": "fedora", "rockylinux-9": "rhel", "almalinux-8": "rhel", "amazonlinux-2023": "amzn",
                "opensuse-leap-15.6": "suse", "opensuse-tumbleweed": "suse", "archlinux": "arch", "alpine-3.18": "alpine", "alpine-3.20": "alpine", "void": "void"}
        self.assertEqual(sorted(want), sorted(os.listdir(os.path.join(FIX, "os-release"))))
        for name, fam in want.items():
            self.assertEqual(system.family(osr(name)), fam, name)

    def test_docker_s_own_installer_only_where_it_supports_the_distribution(self):
        for name in ("debian-12", "debian-13", "ubuntu-22.04", "ubuntu-24.04", "fedora-40", "fedora-41", "rockylinux-9", "almalinux-8"):
            how, cmd, _ = system.docker_source(osr(name))
            self.assertEqual((how, cmd), ("script", "curl -fsSL https://get.docker.com | sudo sh"), name)

    def test_end_of_life_releases_install_with_a_note(self):
        for name in ("debian-11", "fedora-40", "fedora-41"):
            how, _, note = system.docker_source(osr(name))
            self.assertEqual(how, "script", name)
            self.assertIn("end of life", note, name)
        self.assertEqual(system.docker_source(osr("debian-12"))[2], "")

    def test_distributions_docker_does_not_support_use_their_own_packages(self):
        self.assertEqual(system.docker_source(osr("archlinux"))[:2], ("package", "sudo pacman -S --needed --noconfirm docker docker-compose docker-buildx && sudo systemctl enable --now docker"))
        for name in ("alpine-3.18", "alpine-3.20"):  # no systemd: OpenRC starts it
            self.assertEqual(system.docker_source(osr(name))[:2], ("package", "sudo apk add docker docker-cli-compose && sudo rc-update add docker default && sudo rc-service docker start"))
        for name in ("opensuse-leap-15.6", "opensuse-tumbleweed"):
            self.assertIn("zypper --non-interactive install docker docker-compose", system.docker_source(osr(name))[1], name)
        self.assertIn("xbps-install -Sy docker docker-compose", system.docker_source(osr("void"))[1])

    def test_ubuntu_20_04_uses_ubuntu_packages_because_docker_s_installer_fails_there(self):
        how, cmd, note = system.docker_source(osr("ubuntu-20.04"))  # seen 2026-11-21: "Unable to locate package docker-model-plugin"
        self.assertEqual(how, "package")
        self.assertIn("docker.io docker-compose-v2", cmd)
        self.assertIn("end of life", note)

    def test_amazon_linux_says_the_compose_part_is_missing(self):
        how, cmd, note = system.docker_source(osr("amazonlinux-2023"))
        self.assertEqual((how, cmd), ("by-hand", ""))
        self.assertIn("not its compose part", note)

    def test_an_ubuntu_based_distribution_it_does_not_know_uses_ubuntu_packages(self):
        mint = {**osr("ubuntu-22.04"), "ID": "linuxmint", "ID_LIKE": ["ubuntu", "debian"], "PRETTY_NAME": "Linux Mint 21.3"}
        how, cmd, note = system.docker_source(mint)
        self.assertEqual(how, "package")
        self.assertIn("docker.io docker-compose-v2", cmd)
        self.assertIn("does not know this distribution", note)

    def test_a_debian_based_one_is_sent_to_docker_s_steps_because_debian_12_has_only_compose_1(self):
        fork = {**osr("debian-12"), "ID": "example-os", "ID_LIKE": ["debian"]}
        how, cmd, note = system.docker_source(fork)
        self.assertEqual((how, cmd), ("by-hand", ""))
        self.assertIn("docs.docker.com/engine/install/debian", note)

    def test_nixos_and_unknown_systems_are_refused_with_what_to_do(self):
        self.assertIn("virtualisation.docker.enable = true;", system.docker_source({"ID": "nixos", "ID_LIKE": []})[2])
        how, _, note = system.docker_source({"ID": "", "ID_LIKE": []})
        self.assertEqual(how, "by-hand")
        self.assertIn("compose plugin", note)

    def test_a_mac_installs_docker_its_own_way(self):
        self.assertEqual(system.docker_source({}, system="Darwin")[0], "mac")

    def test_parse_handles_quotes_and_empty_text(self):
        self.assertEqual(osr("rockylinux-9")["ID_LIKE"], ["rhel", "centos", "fedora"])
        self.assertEqual(system.parse_os_release(None), {"ID_LIKE": []})


class Machine(unittest.TestCase):
    def test_init_system_is_what_runs_not_what_is_installed(self):
        self.assertEqual(system.init_system(files("/run/systemd/system")), "systemd")
        self.assertEqual(system.init_system(files("/run/openrc")), "openrc")
        self.assertEqual(system.init_system(files("/run/runit")), "runit")
        self.assertEqual(system.init_system(files("/sbin/launchd")), "launchd")
        self.assertEqual(system.init_system(files()), "none")  # a container with systemctl installed but no systemd running

    def test_selinux(self):
        self.assertEqual(system.selinux(lambda p: "1"), "enforcing")
        self.assertEqual(system.selinux(lambda p: "0\n"), "permissive")
        self.assertEqual(system.selinux(lambda p: None), "off")

    def test_container_wsl_or_machine(self):
        self.assertEqual(system.where(lambda p: None, files("/.dockerenv")), "container")
        self.assertEqual(system.where(lambda p: None, files("/run/.containerenv")), "container")  # Podman
        self.assertEqual(system.where(lambda p: "6.6.87-microsoft-standard-WSL2" if p.endswith("osrelease") else None, files()), "wsl")
        self.assertEqual(system.where(lambda p: "0::/\n", files()), "machine")

    def test_laptop_from_battery_or_case(self):
        self.assertTrue(system.laptop(lambda p: "10\n", files(), lambda d: []))
        self.assertTrue(system.laptop(lambda p: "3\n", files(), lambda d: ["AC", "BAT0"]))
        self.assertFalse(system.laptop(lambda p: "3\n", files(), lambda d: ["AC"]))
        self.assertFalse(system.laptop(lambda p: None, files(), lambda d: (_ for _ in ()).throw(OSError())))
        self.assertTrue(system.laptop(None, None, None, sh=lambda c: "Now drawing from 'AC Power'\n -InternalBattery-0 (id=1)\t100%;", system="Darwin"))

    def test_docker_flavour_from_recorded_docker_info(self):
        self.assertEqual(system.docker_flavour(info("engine.txt")), "engine")
        self.assertEqual(system.docker_flavour(None), "none")
        self.assertEqual(system.docker_flavour(" Operating System: Docker Desktop\n"), "docker-desktop")
        self.assertEqual(system.docker_flavour(" Security Options:\n  seccomp\n  rootless\n"), "rootless")

    def test_detect_never_raises_on_a_bare_machine(self):
        p = system.detect(read=lambda p: None, exists=files(), listdir=lambda d: [], sh=lambda c: None, which=lambda n: None, system="Linux", user="alex")
        self.assertEqual((p["family"], p["init"], p["docker"], p["where"], p["linger"]), ("other", "none", "none", "machine", False))
        self.assertEqual(p["docker_source"]["how"], "by-hand")


class Doctor(unittest.TestCase):
    def base(self, **over):
        return {"system": "linux", "init": "systemd", "where": "machine", "selinux": "off", "docker": "engine", "docker_group": True, "linger": True,
                "laptop": False, "pretty": "Ubuntu 24.04 LTS", "docker_source": {"how": "script", "command": "", "note": ""}, **over}

    def rows(self, **over):
        return {r["name"]: r for r in system.checks(self.base(**over))}

    def test_a_normal_server_has_nothing_to_say(self):
        self.assertEqual(list(self.rows()), ["autostart"])
        self.assertEqual(self.rows()["autostart"]["state"], "works")

    def test_nothing_recorded_asks_for_the_installer(self):
        self.assertIn("Run install.sh again", system.checks(None)[0]["fix"])

    def test_alpine_and_containers_say_autostart_is_unavailable_and_what_to_type(self):
        r = self.rows(init="openrc")["autostart"]
        self.assertEqual(r["state"], "unavailable")
        self.assertIn("OpenRC", r["why"])
        self.assertIn("homelab start", r["fix"])
        self.assertIn("this is a container", self.rows(init="none", where="container")["autostart"]["why"])

    def test_linger_laptop_selinux_podman_and_eol_each_get_a_reason_and_a_fix(self):
        self.assertIn("enable-linger", self.rows(linger=False)["linger"]["fix"])
        self.assertNotIn("linger", self.rows(init="openrc", linger=False))  # only a systemd question
        self.assertIn("morning briefing", self.rows(laptop=True)["always_on"]["why"])
        self.assertIn("Do not turn SELinux off", self.rows(selinux="enforcing")["selinux"]["fix"])
        self.assertEqual(self.rows(docker="podman")["docker"]["state"], "limited")
        self.assertIn("end of life", self.rows(docker_source={"note": "Debian 11 has reached its end of life."})["distro"]["why"])

    def test_a_mac_is_fine_without_systemd(self):
        self.assertEqual(self.rows(system="mac", init="launchd", linger=None)["autostart"]["state"], "works")
        self.assertNotIn("linger", self.rows(system="mac", init="launchd", linger=None))


if __name__ == "__main__":
    unittest.main()
