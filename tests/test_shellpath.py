"""The homelab command on the PATH: the link, the one marked line in the startup file, and taking both out again."""
import os
import tempfile
import unittest

import harness  # noqa: F401  (puts core on the path)
from core import shellpath


class ShellPath(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.home = os.path.join(self.tmp.name, "home")
        self.root = os.path.join(self.tmp.name, "proj")
        os.makedirs(os.path.join(self.root, "bin"))
        os.makedirs(self.home)
        open(os.path.join(self.root, "bin", "homelab"), "w").close()
        self.link = os.path.join(self.home, ".local", "bin", "homelab")
        self.zshrc = os.path.join(self.home, ".zshrc")

    def tearDown(self):
        self.tmp.cleanup()

    def add(self, path="/usr/bin", shell="/bin/zsh", which=lambda n, path=None: None):
        return shellpath.add(self.root, self.home, path=path, shell=shell, platform="mac", which=which, env={})

    def test_links_and_adds_one_line_when_the_folder_is_not_on_the_path(self):
        open(self.zshrc, "w").write("alias ll='ls -l'")
        self.assertEqual(self.add(), ("added", self.zshrc))
        self.assertEqual(os.path.realpath(self.link), os.path.realpath(os.path.join(self.root, "bin", "homelab")))
        text = open(self.zshrc).read()
        self.assertTrue(text.startswith("alias ll='ls -l'\n"))
        self.assertEqual(text.count(shellpath.MARK), 1)
        self.assertEqual(self.add(), ("already", self.zshrc))  # running it again changes nothing
        self.assertEqual(open(self.zshrc).read(), text)

    def test_leaves_the_startup_file_alone_when_the_folder_is_already_on_the_path(self):
        state, rc = self.add(path=os.path.join(self.home, ".local", "bin") + os.pathsep + "/usr/bin")
        self.assertEqual((state, rc), ("added", None))
        self.assertFalse(os.path.exists(self.zshrc))

    def test_never_replaces_another_homelab_command(self):
        os.makedirs(os.path.dirname(self.link))
        open(self.link, "w").write("someone else's")
        self.assertEqual(self.add()[0], "clash")
        self.assertEqual(open(self.link).read(), "someone else's")
        os.remove(self.link)
        self.assertEqual(self.add(which=lambda n, path=None: "/opt/other/homelab"), ("clash", "/opt/other/homelab"))
        self.assertFalse(os.path.lexists(self.link))

    def test_remove_takes_out_only_what_it_added(self):
        open(self.zshrc, "w").write("alias ll='ls -l'\n")
        self.add()
        shellpath.remove(self.root, self.home)
        self.assertFalse(os.path.lexists(self.link))
        self.assertEqual(open(self.zshrc).read(), "alias ll='ls -l'\n")
        self.assertEqual(shellpath.remove(self.root, self.home), [])

    def test_every_state_it_can_find(self):
        chk = lambda path="/usr/bin", which=lambda n, path=None: None: shellpath.check(self.root, self.home, path=path, shell="/bin/zsh", platform="mac", which=which, env={})["state"]
        self.assertEqual(chk(), "missing")
        self.add()
        self.assertEqual(chk(), "ready")
        open(self.zshrc, "w").close()  # someone deleted our line
        self.assertEqual(chk(), "needs_line")
        self.assertEqual(self.add(), ("added", self.zshrc))  # puts only the line back
        own_bin = os.path.join(self.root, "bin")
        self.assertEqual(chk(path=own_bin, which=lambda n, path=None: os.path.join(own_bin, n)), "ready")  # the project's bin already on the PATH

    def test_an_old_download_is_replaced_and_another_live_one_only_when_forced(self):
        os.makedirs(os.path.dirname(self.link))
        os.symlink(os.path.join(self.tmp.name, "gone", "bin", "homelab"), self.link)
        state, old = self.add()
        self.assertEqual((state, old), ("replaced", os.path.join(self.tmp.name, "gone")))
        other = os.path.join(self.tmp.name, "other")
        os.makedirs(os.path.join(other, "bin"))
        open(os.path.join(other, "bin", "homelab"), "w").close()
        os.remove(self.link)
        os.symlink(os.path.join(other, "bin", "homelab"), self.link)
        self.assertEqual(self.add()[0], "other")
        self.assertEqual(shellpath.remove(self.root, self.home), [])  # never takes the other download's link away
        self.assertEqual(shellpath.add(self.root, self.home, path="/usr/bin", shell="/bin/zsh", platform="mac", which=lambda n, path=None: None, force=True, env={})[0], "replaced")
        self.assertEqual(os.path.realpath(self.link), os.path.realpath(os.path.join(self.root, "bin", "homelab")))

    def test_zsh_with_its_own_folder(self):
        self.assertEqual(shellpath.rc_file("/h", "/bin/zsh", "mac", {"ZDOTDIR": "/h/.config/zsh"}), "/h/.config/zsh/.zshrc")

    def test_picks_the_startup_file_for_each_shell(self):
        self.assertTrue(shellpath.rc_file("/h", "/bin/bash", "mac").endswith(".bash_profile"))
        self.assertTrue(shellpath.rc_file("/h", "/bin/bash", "linux").endswith(".bashrc"))
        self.assertTrue(shellpath.rc_file("/h", "/usr/bin/fish", "linux").endswith("config.fish"))
        self.assertTrue(shellpath.rc_file("/h", "", "linux").endswith(".profile"))


if __name__ == "__main__":
    unittest.main()
