"""Docker starting by itself after a restart: our Colima login item, and pointing the other Docker apps to their own switch."""
import os
import tempfile
import unittest

import harness  # noqa: F401  (puts core on the path)
from core import autostart


class Autostart(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.home = self.tmp.name

    def test_knows_the_docker_from_its_context(self):
        for ctx, kind in (("colima", "colima"), ("colima-work", "colima"), ("orbstack", "orbstack"), ("desktop-linux", "desktop")):
            self.assertEqual(autostart.runtime(lambda cmd, c=ctx: (0, c + "\n")), kind)

    def test_colima_gets_a_login_item_that_runs_start_once_and_comes_out_again(self):
        done, msg = autostart.on("colima", self.home, which=lambda n, path=None: "/opt/homebrew/bin/colima")
        self.assertTrue(done)
        text = open(autostart.plist_path(self.home)).read()
        self.assertIn("<string>/opt/homebrew/bin/colima</string><string>start</string>", text)
        self.assertIn("<key>KeepAlive</key><false/>", text)  # once at login; keeping it alive would rerun start in a loop
        self.assertEqual(autostart.status("colima", self.home, None)[0], True)
        self.assertTrue(autostart.off(self.home))
        self.assertFalse(os.path.exists(autostart.plist_path(self.home)))
        self.assertFalse(autostart.off(self.home))

    def test_other_dockers_are_pointed_to_their_own_switch_and_nothing_is_written(self):
        done, msg = autostart.on("orbstack", self.home)
        self.assertFalse(done)
        self.assertIn("Start at login", msg)
        self.assertFalse(os.path.exists(autostart.plist_path(self.home)))
        self.assertEqual(autostart.status("linux", self.home, lambda c: (0, "enabled\n")), (True, "sudo systemctl enable docker"))

    def test_says_what_is_missing_when_colima_is_not_found(self):
        self.assertEqual(autostart.on("colima", self.home, which=lambda n, path=None: None)[0], False)


if __name__ == "__main__":
    unittest.main()
