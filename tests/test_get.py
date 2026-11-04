"""get.sh, the one-line installer, against a throwaway "remote" repository made on this machine.
Real git is used, a pretend install.sh records how it was called. Nothing on the internet is touched and nothing real is installed."""
import os
import shutil
import stat
import subprocess
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TOOLS = "bash env sh cat grep ls tr sed printf dirname mkdir rm head tail chmod".split()
FAKE_INSTALL = '#!/bin/sh\necho "ran in $(pwd) with: $*" > "$OUT"\n'


def git(*args, cwd=None):
    subprocess.run(["git", "-c", "commit.gpgsign=false", "-c", "tag.gpgsign=false", "-c", "user.name=t", "-c", "user.email=t@example.com", *args], cwd=cwd, check=True, capture_output=True)


class GetScript(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="hl-get-")
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.remote = os.path.join(self.tmp, "remote")
        os.makedirs(self.remote)
        git("init", "-q", "-b", "main", cwd=self.remote)
        self.publish("one")
        self.bin = os.path.join(self.tmp, "bin")
        os.makedirs(self.bin)
        for t in TOOLS:
            real = shutil.which(t)
            if real:
                os.symlink(real, os.path.join(self.bin, t))
        self.stub("uname", 'echo "${FAKE_OS:-Linux}"')
        self.stub("git", 'exec "%s" "$@"' % shutil.which("git"))
        self.dir = os.path.join(self.tmp, "program")
        self.home = os.path.join(self.tmp, "data")
        self.out = os.path.join(self.tmp, "out.txt")

    def stub(self, name, body):
        p = os.path.join(self.bin, name)
        with open(p, "w") as f:
            f.write("#!/bin/sh\n" + body + "\n")
        os.chmod(p, os.stat(p).st_mode | stat.S_IXUSR)

    def publish(self, note, tag=None):
        p = os.path.join(self.remote, "install.sh")
        with open(p, "w") as f:
            f.write(FAKE_INSTALL)
        os.chmod(p, 0o755)
        with open(os.path.join(self.remote, "note.txt"), "w") as f:
            f.write(note)
        git("add", "-A", cwd=self.remote)
        git("commit", "-q", "-m", note, cwd=self.remote)
        if tag:
            git("tag", tag, cwd=self.remote)

    def run_it(self, *args, **env):
        e = {"PATH": self.bin, "HOME": self.tmp, "HL_DIR": self.dir, "HL_HOME": self.home, "HL_REPO": self.remote, "OUT": self.out, **env}
        r = subprocess.run(["bash", os.path.join(ROOT, "get.sh"), *args], env=e, capture_output=True, text=True, timeout=60, stdin=subprocess.DEVNULL)
        return r.returncode, r.stdout + r.stderr

    def ran(self):
        return open(self.out).read() if os.path.exists(self.out) else ""

    def note(self):
        return open(os.path.join(self.dir, "note.txt")).read()

    def test_downloads_and_runs_the_installer_with_the_options(self):
        rc, out = self.run_it("--yes", "--no-open")
        self.assertEqual(rc, 0, out)
        self.assertIn("Downloading into", out)
        self.assertIn("with: --yes --no-open", self.ran())
        self.assertIn(os.path.basename(self.dir), self.ran())

    def test_stable_starts_at_the_newest_release_and_skips_pre_releases(self):
        self.publish("release one", tag="v0.1.0")
        self.publish("release two", tag="v0.2.0")
        self.publish("not ready", tag="v0.3.0-rc1")
        self.publish("newer work on main")
        rc, out = self.run_it()
        self.assertEqual(rc, 0, out)
        self.assertIn("Version v0.2.0", out)
        self.assertEqual(self.note(), "release two")

    def test_stable_with_no_release_yet_stays_on_main(self):
        rc, out = self.run_it()
        self.assertEqual(rc, 0, out)
        self.assertNotIn("Version", out)
        self.assertEqual(self.note(), "one")

    def test_edge_follows_main_and_remembers_the_choice(self):
        self.publish("release", tag="v0.1.0")
        self.publish("newer work on main")
        rc, out = self.run_it(HL_CHANNEL="edge")
        self.assertEqual(rc, 0, out)
        self.assertEqual(self.note(), "newer work on main")
        self.assertEqual(open(os.path.join(self.home, "channel")).read().strip(), "edge")

    def test_a_second_run_installs_again_without_touching_the_copy(self):
        self.run_it()
        os.remove(self.out)
        with open(os.path.join(self.dir, "note.txt"), "w") as f:
            f.write("mine")
        rc, out = self.run_it("--yes")
        self.assertEqual(rc, 0, out)
        self.assertIn("Already downloaded", out)
        self.assertIn("homelab update", out)
        self.assertEqual(self.note(), "mine")
        self.assertIn("with: --yes", self.ran())

    def test_it_does_not_use_a_folder_that_is_not_its_own(self):
        os.makedirs(self.dir)
        with open(os.path.join(self.dir, "keep.txt"), "w") as f:
            f.write("x")
        rc, out = self.run_it()
        self.assertNotEqual(rc, 0)
        self.assertIn("not this project", out)
        self.assertEqual(self.ran(), "")

    def test_a_mac_without_git_opens_the_tools_installer_and_stops(self):
        os.remove(os.path.join(self.bin, "git"))
        self.stub("xcode-select", 'echo "xcode-select $*" > "$OUT.x"')
        rc, out = self.run_it(FAKE_OS="Darwin")
        self.assertNotEqual(rc, 0)
        self.assertIn("git is needed", out)
        self.assertIn("xcode-select --install", open(self.out + ".x").read())
        self.assertEqual(self.ran(), "")

    def test_linux_without_git_or_a_package_manager_says_what_to_do(self):
        os.remove(os.path.join(self.bin, "git"))
        rc, out = self.run_it(FAKE_OS="Linux")
        self.assertNotEqual(rc, 0)
        self.assertIn("Install git with your package manager", out)

    def test_linux_without_git_installs_it_with_apt(self):
        os.remove(os.path.join(self.bin, "git"))
        real = shutil.which("git")
        self.stub("apt-get", 'echo "apt-get $*" >> "$OUT.apt"; case "$*" in *install*) printf \'#!/bin/sh\\nexec %s "$@"\\n\' > "%s/git"; chmod +x "%s/git";; esac' % (real, self.bin, self.bin))
        self.stub("sudo", 'exec "$@"')
        rc, out = self.run_it(FAKE_OS="Linux")
        self.assertEqual(rc, 0, out)
        self.assertIn("Installing git", out)
        self.assertIn("apt-get install", open(self.out + ".apt").read())
        self.assertIn("Downloading into", out)

    def test_other_systems_are_refused(self):
        os.remove(os.path.join(self.bin, "git"))
        rc, out = self.run_it(FAKE_OS="MINGW64_NT-10.0")
        self.assertNotEqual(rc, 0)
        self.assertIn("not supported yet", out)

    def test_a_download_that_fails_stops_without_running_the_installer(self):
        rc, out = self.run_it(HL_REPO=os.path.join(self.tmp, "nowhere"))
        self.assertNotEqual(rc, 0)
        self.assertEqual(self.ran(), "")


if __name__ == "__main__":
    unittest.main()
