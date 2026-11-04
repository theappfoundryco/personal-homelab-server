"""scripts/dev-reset.sh against a pretend machine: fake docker and launchctl, a throwaway repo copy and data folder."""
import os
import shutil
import stat
import subprocess
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TOOLS = "bash env sh cat sed grep awk tr head mkdir cp chmod dirname rm find ls id uname printf".split()
DOCKER = '''echo "docker $*" >> "$FAKE_LOG"
case "$1 $2" in
  "info "*) exit 0;;
  "ps "*) echo "c1"; echo "c2";;
  "volume ls") echo "v1";;
  "network ls") echo "n1";;
esac
exit 0'''


class DevReset(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="hl-reset-")
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.repo, self.home, self.bin = (os.path.join(self.tmp, n) for n in ("repo", "data", "bin"))
        os.makedirs(os.path.join(self.repo, "stack", "secrets"))
        os.makedirs(os.path.join(self.repo, "scripts"))
        os.makedirs(self.home)
        os.makedirs(self.bin)
        shutil.copy(os.path.join(ROOT, "scripts", "dev-reset.sh"), os.path.join(self.repo, "scripts"))
        shutil.copy(os.path.join(ROOT, "stack", "compose.yaml"), os.path.join(self.repo, "stack"))
        for f in ("install.sh",):
            open(os.path.join(self.repo, f), "w").write("#!/bin/sh\necho installed >> \"$FAKE_LOG\"\n")
            os.chmod(os.path.join(self.repo, f), 0o755)
        for f in (".env", "config.yaml"):
            open(os.path.join(self.repo, "stack", f), "w").write("x")
        open(os.path.join(self.repo, "stack", "secrets", "tg"), "w").write("x")
        open(os.path.join(self.home, "journal.json"), "w").write("{}")
        self.keep = os.path.join(self.tmp, "keep.txt")
        open(self.keep, "w").write("mine")
        for t in TOOLS:
            if shutil.which(t):
                os.symlink(shutil.which(t), os.path.join(self.bin, t))
        self.log = os.path.join(self.tmp, "calls.log")
        open(self.log, "w").close()
        for n, body in (("docker", DOCKER), ("launchctl", 'echo "launchctl $*" >> "$FAKE_LOG"'), ("systemctl", 'echo "systemctl $*" >> "$FAKE_LOG"')):
            p = os.path.join(self.bin, n)
            open(p, "w").write("#!/bin/sh\n" + body + "\n")
            os.chmod(p, os.stat(p).st_mode | stat.S_IXUSR)

    def run_it(self, *args, **env):
        e = {"PATH": self.bin, "HOME": self.tmp, "HL_HOME": self.home, "FAKE_LOG": self.log, **env}
        r = subprocess.run(["bash", os.path.join(self.repo, "scripts", "dev-reset.sh"), *args], env=e, capture_output=True, text=True, timeout=60, stdin=subprocess.DEVNULL)
        return r.returncode, r.stdout + r.stderr

    def test_a_dry_run_changes_nothing(self):
        rc, out = self.run_it("--dry-run")
        self.assertEqual(rc, 0, out)
        self.assertTrue(os.path.exists(os.path.join(self.home, "journal.json")))
        self.assertTrue(os.path.exists(os.path.join(self.repo, "stack", ".env")))
        self.assertNotIn("docker rm", open(self.log).read())

    def test_it_will_not_delete_without_a_person_or_a_yes(self):
        rc, out = self.run_it()
        self.assertEqual(rc, 1)
        self.assertIn("--yes", out)
        self.assertTrue(os.path.exists(self.home))

    def test_yes_removes_this_project_and_nothing_else(self):
        rc, out = self.run_it("--yes")
        self.assertEqual(rc, 0, out)
        self.assertFalse(os.path.exists(self.home))
        self.assertFalse(os.path.exists(os.path.join(self.repo, "stack", ".env")))
        self.assertFalse(os.path.exists(os.path.join(self.repo, "stack", "config.yaml")))
        self.assertEqual(os.listdir(os.path.join(self.repo, "stack", "secrets")), [])
        self.assertTrue(os.path.exists(os.path.join(self.repo, "install.sh")))
        self.assertTrue(os.path.exists(self.keep))
        calls = open(self.log).read()
        self.assertIn("docker rm -f c1 c2", calls)
        self.assertIn("docker volume rm v1", calls)
        self.assertIn("label=com.docker.compose.project=homelab", calls)
        self.assertIn("docker rmi homelab-telegram-bot:local", calls)
        self.assertNotIn("prom/prometheus", calls)  # pulled images stay unless asked

    def test_images_removes_the_pulled_ones_too(self):
        self.run_it("--yes", "--images")
        self.assertIn("docker rmi prom/prometheus:v3.15.1", open(self.log).read())

    def test_a_dangerous_data_folder_is_refused(self):
        for bad in (self.tmp, "/"):
            rc, out = self.run_it("--yes", HL_HOME=bad)
            self.assertEqual(rc, 1, bad)
            self.assertIn("not a folder that is safe", out)
        self.assertTrue(os.path.exists(self.keep))

    def test_reinstall_runs_the_installer_afterwards(self):
        rc, out = self.run_it("--yes", "--reinstall")
        self.assertEqual(rc, 0, out)
        self.assertIn("installed", open(self.log).read())

    def test_a_stopped_docker_is_skipped_with_a_warning(self):
        os.remove(os.path.join(self.bin, "docker"))
        rc, out = self.run_it("--yes")
        self.assertEqual(rc, 0, out)
        self.assertIn("Docker is not running", out)
        self.assertFalse(os.path.exists(self.home))


if __name__ == "__main__":
    unittest.main()
