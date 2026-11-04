"""install.sh against pretend systems: fake uname, docker, df, lsof and curl on an otherwise empty PATH, in a throwaway copy of the folder.
Nothing real is started. What it cannot show is a real Docker on a real Linux box."""
import json, os
import shutil
import stat
import subprocess
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REAL_TOOLS = "bash env sh cat sed grep awk tr head mkdir cp chmod dirname readlink seq date python3 rm mv printf ln touch id tail".split()

STUBS = {
    "uname": 'case "$1" in -s) echo "${FAKE_OS:-Linux}";; -r) echo "${FAKE_REL:-6.8.0}";; -m) echo x86_64;; *) echo "${FAKE_OS:-Linux}";; esac',
    "docker": '''echo "docker $*" >> "$FAKE_LOG"
case "$1 $2" in
  "compose version") exit "${FAKE_COMPOSE:-0}";;
  "info "*) [ -f "$FAKE_LOG.up" ] && exit 0; exit "${FAKE_RUNNING:-0}";;
  "ps "*) echo "${FAKE_PS:-}";;
esac
exit 0''',
    "df": 'echo "Filesystem 1024-blocks Used Available Capacity Mounted"; echo "/dev/x 100 1 $(( ${FAKE_FREE_GB:-100} * 1048576 )) 1% /"',
    "lsof": 'exit "${FAKE_BUSY:-1}"',
    "curl": 'echo "curl $*" >> "$FAKE_LOG"; exit "${FAKE_CURL:-0}"',
    "sleep": "exit 0",
    "open": 'echo "open $*" >> "$FAKE_LOG"',
    "xdg-open": 'echo "xdg-open $*" >> "$FAKE_LOG"',
}

# tools that only exist on some machines; a test adds the ones it wants with self.stub(..., table=EXTRA)
EXTRA = {
    "brew": '''echo "brew $*" >> "$FAKE_LOG"
case "$1" in --prefix) echo "$FAKE_PREFIX";; list) exit 1;; install) cp "$FAKE_DOCKER_SRC" "$FAKE_BIN/docker";; esac''',
    "colima": 'echo "colima $*" >> "$FAKE_LOG"; [ "$1" = start ] && touch "$FAKE_LOG.up"; exit 0',
    "orbctl": 'echo "orbctl $*" >> "$FAKE_LOG"; [ "$1" = start ] && touch "$FAKE_LOG.up"; exit 0',
    "sudo": 'echo "sudo $*" >> "$FAKE_LOG"; exit 0',
}


class Installer(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="hl-install-")
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.app = os.path.join(self.tmp, "app")
        os.makedirs(os.path.join(self.app, "stack"))
        shutil.copy(os.path.join(ROOT, "install.sh"), self.app)
        for f in ("compose.yaml", "config.example.yaml", ".env.example"):
            shutil.copy(os.path.join(ROOT, "stack", f), os.path.join(self.app, "stack"))
        os.symlink(os.path.join(ROOT, "core"), os.path.join(self.app, "core"))
        self.bin = os.path.join(self.tmp, "bin")
        os.makedirs(self.bin)
        for t in REAL_TOOLS:
            real = shutil.which(t)
            if real:
                os.symlink(real, os.path.join(self.bin, t))
        self.log = os.path.join(self.tmp, "calls.log")
        open(self.log, "w").close()
        self.home = os.path.join(self.tmp, "home")
        self.stub(*STUBS)

    def stub(self, *names, table=STUBS):
        for n in names:
            p = os.path.join(self.bin, n)
            if os.path.lexists(p):
                os.remove(p)
            with open(p, "w") as f:
                f.write("#!/bin/sh\n" + table[n] + "\n")
            os.chmod(p, os.stat(p).st_mode | stat.S_IXUSR)

    def without(self, *names):
        for n in names:
            os.remove(os.path.join(self.bin, n))

    def run_it(self, *args, **env):
        e = {"PATH": self.bin, "HOME": self.tmp, "HL_HOME": self.home, "FAKE_LOG": self.log, "FAKE_BIN": self.bin, "FAKE_PREFIX": os.path.join(self.tmp, "brew"),
             "FAKE_DOCKER_SRC": os.path.join(self.tmp, "docker.src"), **env}
        r = subprocess.run(["bash", os.path.join(self.app, "install.sh"), *args], env=e, capture_output=True, text=True, timeout=60, stdin=subprocess.DEVNULL)
        return r.returncode, r.stdout + r.stderr

    def calls(self):
        return open(self.log).read()

    def test_chosen_apps_are_saved_and_started_and_kept_on_a_second_run(self):
        rc, out = self.run_it("--no-open", HL_APPS="open-webui monitoring")
        self.assertEqual(rc, 0, out)
        self.assertIn("docker compose up -d --build landing telegram-bot docker-proxy ollama open-webui prometheus node-exporter cadvisor grafana", self.calls())
        self.assertEqual(json.load(open(os.path.join(self.home, "data", "apps.json"))), {"apps": ["open-webui", "monitoring"]})
        rc, out = self.run_it("--no-open", HL_APPS="")
        self.assertIn("apps kept: open-webui, monitoring", out)

    def test_happy_path_on_linux(self):
        rc, out = self.run_it("--no-open")
        self.assertEqual(rc, 0, out)
        self.assertIn("docker compose up -d --build landing telegram-bot docker-proxy", self.calls())
        for d in ("data", "stats"):
            self.assertTrue(os.path.isdir(os.path.join(self.home, d)), d)
        env = open(os.path.join(self.app, "stack", ".env")).read()
        self.assertNotIn("change-me", env)
        self.assertIn(f"HL_DATA_DIR={self.home}/data", env)
        self.assertIn("TG_TOKEN=\n", env)
        self.assertEqual(oct(os.stat(os.path.join(self.app, "stack", ".env")).st_mode & 0o777), "0o600")
        self.assertTrue(os.path.isfile(os.path.join(self.app, "stack", "config.yaml")))
        self.assertNotIn("—", out)

    def test_a_second_run_changes_nothing(self):
        self.run_it("--no-open")
        first = open(os.path.join(self.app, "stack", ".env")).read()
        with open(os.path.join(self.app, "stack", "config.yaml"), "a") as f:
            f.write("# mine\n")
        rc, out = self.run_it("--no-open")
        self.assertEqual(rc, 0, out)
        self.assertEqual(open(os.path.join(self.app, "stack", ".env")).read(), first)
        self.assertIn("# mine", open(os.path.join(self.app, "stack", "config.yaml")).read())
        self.assertIn(".env kept", out)

    def test_passwords_are_different_each_time_and_each_other(self):
        self.run_it("--no-open")
        pw = [l.split("=", 1)[1] for l in open(os.path.join(self.app, "stack", ".env")) if l.startswith(("GF_SECURITY", "HOMEPAGE_VAR_GRAFANA_PASS", "WEBUI"))]
        self.assertEqual(len(set(pw)), len(pw))
        self.assertTrue(all(len(p.strip()) == 24 for p in pw), pw)

    def test_dry_run_changes_nothing(self):
        rc, out = self.run_it("--dry-run")
        self.assertEqual(rc, 0, out)
        self.assertFalse(os.path.exists(self.home))
        self.assertFalse(os.path.exists(os.path.join(self.app, "stack", ".env")))
        self.assertNotIn("compose up", self.calls())
        self.assertIn("would run", out)

    def test_no_docker_and_no_homebrew_on_a_mac_installs_both_without_asking(self):
        self.without("docker")  # Docker is needed to run at all, so it is installed, not offered (CLAUDE.md)
        rc, out = self.run_it("--no-open", FAKE_OS="Darwin")
        self.assertIn("Installing Homebrew first", out)
        self.assertIn("raw.githubusercontent.com/Homebrew/install", self.calls())
        self.assertNotIn("[y/N]", out)

    def test_docker_installed_but_not_running(self):
        rc, out = self.run_it(FAKE_RUNNING="1", FAKE_OS="Darwin")
        self.assertEqual(rc, 1)
        self.assertIn("colima start", out)
        rc, out = self.run_it(FAKE_RUNNING="1")
        self.assertIn("systemctl start docker", out)

    def test_a_mac_without_docker_gets_colima_from_the_terminal(self):
        shutil.copy(os.path.join(self.bin, "docker"), os.path.join(self.tmp, "docker.src"))
        self.without("docker")
        self.stub("brew", "colima", table=EXTRA)
        for pl in ("docker-compose", "docker-buildx"):  # what brew would have put in its prefix
            path = os.path.join(self.tmp, "brew", "opt", pl, "bin", pl)
            os.makedirs(os.path.dirname(path))
            open(path, "w").write("#!/bin/sh\n")
            os.chmod(path, 0o755)
        rc, out = self.run_it("--no-open", FAKE_OS="Darwin", FAKE_RUNNING="1", HL_NAME="Sam")
        self.assertEqual(rc, 0, out)
        calls = self.calls()
        self.assertIn("brew install colima docker docker-compose", calls)
        self.assertIn("brew colima", open(os.path.join(self.home, "installed.txt")).read())  # recorded, so uninstall --purge removes only what it added
        self.assertIn("colima start --cpu 4 --memory", calls)
        for pl in ("docker-compose", "docker-buildx"):
            self.assertTrue(os.path.islink(os.path.join(self.tmp, ".docker", "cli-plugins", pl)))
        self.assertIn("compose up", calls)

    def test_a_mac_with_a_leftover_docker_command_and_nothing_to_run_it_gets_colima(self):
        self.stub("brew", table=EXTRA)  # the docker command is there (a previous Colima was removed), but no Colima, OrbStack or Docker Desktop
        brew = os.path.join(self.bin, "brew")
        open(brew, "a").write('\ncase "$1" in install) cp "$FAKE_BIN/../colima.src" "$FAKE_BIN/colima";; esac\n')  # brew install now brings Colima too
        open(os.path.join(self.tmp, "colima.src"), "w").write("#!/bin/sh\n" + EXTRA["colima"] + "\n")
        os.chmod(os.path.join(self.tmp, "colima.src"), 0o755)
        for pl in ("docker-compose", "docker-buildx"):
            path = os.path.join(self.tmp, "brew", "opt", pl, "bin", pl)
            os.makedirs(os.path.dirname(path))
            open(path, "w").write("#!/bin/sh\n")
            os.chmod(path, 0o755)
        rc, out = self.run_it("--no-open", FAKE_OS="Darwin", FAKE_RUNNING="1", HL_NAME="Sam")
        self.assertEqual(rc, 0, out)
        self.assertIn("nothing to run it", out)
        calls = self.calls()
        self.assertIn("brew install colima", calls)
        self.assertIn("colima start --cpu 4 --memory", calls)

    def test_a_stopped_docker_on_a_mac_is_started_from_the_terminal(self):
        self.stub("colima", table=EXTRA)
        rc, out = self.run_it("--no-open", FAKE_OS="Darwin", FAKE_RUNNING="1")
        self.assertEqual(rc, 0, out)
        self.assertIn("colima start", self.calls())
        self.stub("orbctl", table=EXTRA)
        os.remove(self.log + ".up")
        rc, out = self.run_it("--no-open", FAKE_OS="Darwin", FAKE_RUNNING="1")
        self.assertIn("orbctl start", self.calls())

    def test_linux_without_docker_uses_the_official_installer(self):
        self.without("docker")
        self.stub("sudo", table=EXTRA)
        self.run_it("--no-open")
        calls = self.calls()
        self.assertIn("get.docker.com", calls)
        self.assertIn("sudo systemctl enable --now docker", calls)
        self.assertIn("sudo usermod -aG docker", calls)

    def test_your_name_and_time_zone_are_written_the_first_time_only(self):
        rc, out = self.run_it("--no-open", HL_NAME='Sa"m \\ Lee')
        self.assertEqual(rc, 0, out)
        cfg = open(os.path.join(self.app, "stack", "config.yaml")).read()
        self.assertIn('name: "Sam  Lee"', cfg)
        self.assertRegex(cfg, r'(?m)^timezone: "[A-Za-z_/+-]+"')
        self.assertIn("Hello, Sam  Lee", out)
        rc, out = self.run_it("--no-open", HL_NAME="Someone Else")
        self.assertIn('name: "Sam  Lee"', open(os.path.join(self.app, "stack", "config.yaml")).read())
        self.assertNotIn("Hello", out)

    def test_no_name_given_keeps_the_example_and_says_where_to_set_it(self):
        rc, out = self.run_it("--no-open")
        self.assertEqual(rc, 0, out)
        self.assertIn("No name given", out)

    def test_old_docker_without_compose(self):
        rc, out = self.run_it(FAKE_COMPOSE="1")
        self.assertEqual(rc, 1)
        self.assertIn("compose", out)

    def test_low_disk_stops_and_medium_disk_warns(self):
        rc, out = self.run_it("--no-open", FAKE_FREE_GB="2")
        self.assertEqual(rc, 1)
        self.assertIn("Only 2 GB free", out)
        rc, out = self.run_it("--no-open", FAKE_FREE_GB="10")
        self.assertEqual(rc, 0, out)
        self.assertIn("a local AI model needs", out)

    def test_busy_port_stops_unless_it_is_ours(self):
        rc, out = self.run_it("--no-open", FAKE_BUSY="0")
        self.assertEqual(rc, 1)
        self.assertIn("HL_PORT=3100", out)
        rc, out = self.run_it("--no-open", FAKE_BUSY="0", FAKE_PS="landing")  # our own dashboard already runs there: fine
        self.assertEqual(rc, 0, out)

    def test_windows_wsl_is_refused_politely(self):
        rc, out = self.run_it(FAKE_REL="5.15.0-microsoft-standard-WSL2")
        self.assertEqual(rc, 1)
        self.assertIn("not supported yet", out)

    def test_unknown_system_and_unknown_option(self):
        rc, out = self.run_it(FAKE_OS="FreeBSD")
        self.assertEqual(rc, 1)
        self.assertIn("not supported", out)
        self.assertEqual(self.run_it("--wat")[0], 2)

    def test_it_must_run_from_the_downloaded_folder(self):
        os.remove(os.path.join(self.app, "stack", "compose.yaml"))
        rc, out = self.run_it()
        self.assertEqual(rc, 1)
        self.assertIn("inside the downloaded folder", out)

    def test_gives_up_with_a_pointer_when_it_never_comes_up(self):
        rc, out = self.run_it("--no-open", FAKE_CURL="1")
        self.assertEqual(rc, 1)
        self.assertIn("docker compose logs", out)

    def test_opens_the_browser_on_a_mac(self):
        rc, out = self.run_it(FAKE_OS="Darwin")
        self.assertEqual(rc, 0, out)
        self.assertIn("open http://localhost:3095", self.calls())

    def test_the_port_can_be_changed(self):
        rc, out = self.run_it("--no-open", HL_PORT="3100")
        self.assertEqual(rc, 0, out)
        self.assertIn("HL_PORT=3100", open(os.path.join(self.app, "stack", ".env")).read())

    def env(self):
        return open(os.path.join(self.app, "stack", ".env")).read()

    def test_opening_it_to_the_network_needs_a_pin_first(self):
        rc, out = self.run_it("--no-open", "--lan")
        self.assertEqual(rc, 1)
        self.assertIn("Set a PIN first", out)
        self.assertNotIn("HL_BIND=0.0.0.0", self.env() if os.path.exists(os.path.join(self.app, "stack", ".env")) else "")
        self.assertNotIn("compose up", self.calls())

    def test_lan_with_a_pin_then_back_to_local(self):
        os.makedirs(os.path.join(self.home, "data"))
        with open(os.path.join(self.home, "data", "settings.json"), "w") as f:
            f.write('{\n "_pin": {"salt": "00", "hash": "00"}\n}')
        rc, out = self.run_it("--no-open", "--lan")
        self.assertEqual(rc, 0, out)
        self.assertIn("HL_BIND=0.0.0.0\n", self.env())
        self.assertIn("your network", out)
        self.assertEqual(self.run_it("--no-open", "--local")[0], 0)
        self.assertEqual([l for l in self.env().splitlines() if l.startswith("HL_BIND=")], ["HL_BIND=127.0.0.1"])
        self.assertIn("HL_BIND=127.0.0.1\n", self.env())


class ComposePaths(unittest.TestCase):
    def test_the_live_servers_paths_are_still_the_defaults(self):
        text = open(os.path.join(ROOT, "stack", "compose.yaml")).read()
        self.assertIn("${HL_DATA_DIR:-/var/lib/homelab-bot}:/data", text)
        self.assertIn("${HL_STATS_DIR:-/var/lib/homelab-stats}:/srv/stats:ro", text)
        self.assertIn("${HL_BIND:-127.0.0.1}:${HL_PORT:-3095}:80", text)  # this machine only, unless --lan
        self.assertNotIn("- /var/lib/homelab", text)  # every mount goes through a variable


if __name__ == "__main__":
    unittest.main()
