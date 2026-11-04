"""Backups (0.3.0): the list, the copy to your own drive or folder with its states (not plugged in, blocked, full, not a safe place),
locking with a passphrase, the host helper's alerts at most once a day, and the Settings, Backups API."""
import errno, json, os, shutil, stat, subprocess, tarfile, tempfile, unittest

import harness
from core import agent, backups


def fake_backup(folder, name, size=10):
    os.makedirs(folder, exist_ok=True)
    p = os.path.join(folder, name)
    with open(p, "wb") as f:
        f.write(b"x" * size)
    return p


class Copies(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp(prefix="hl-bk-")
        self.addCleanup(shutil.rmtree, self.d, ignore_errors=True)
        self.home = os.path.join(self.d, "home")
        os.makedirs(self.home)

    def test_the_list_is_newest_first_and_only_our_files(self):
        f = os.path.join(self.home, "backups")
        fake_backup(f, "nightly-20261101-033000.tar.gz"); os.utime(os.path.join(f, "nightly-20261101-033000.tar.gz"), (1, 1))
        fake_backup(f, "backup-20261103-120000.tar.gz")
        fake_backup(f, "notes.txt")
        self.assertEqual([b["name"] for b in backups.listing(f)], ["backup-20261103-120000.tar.gz", "nightly-20261101-033000.tar.gz"])
        self.assertEqual(backups.listing(os.path.join(self.d, "nope")), [])

    def test_where_a_copy_may_go(self):
        self.assertEqual(backups.check_target("", self.home, "linux"), "off")
        self.assertEqual(backups.check_target(os.path.join(self.home, "backups"), self.home, "linux"), "inside")  # same place as the original
        self.assertEqual(backups.check_target("/Volumes/NotPluggedIn/Homelab", self.home, "mac"), "missing")
        self.assertEqual(backups.check_target(os.path.join(self.d, "drive", "Homelab"), self.home, "linux"), "ok")
        open(os.path.join(self.d, "afile"), "w").close()
        self.assertIn(backups.check_target(os.path.join(self.d, "afile"), self.home, "linux"), ("notdir", "failed"))
        for code, state in ((errno.EPERM, "blocked"), (errno.EACCES, "denied"), (errno.EROFS, "denied"), (errno.ENOSPC, "full"), (errno.EIO, "failed")):
            self.assertEqual(backups._state(OSError(code, "x")), state)
        self.assertEqual(backups.mount_of("/Volumes/Drive/a/b", "mac"), "/Volumes/Drive")
        self.assertEqual(backups.mount_of("/media/sam/Drive/x", "linux"), "/media/sam/Drive")
        self.assertEqual(backups.mount_of("/run/media/sam/Drive/x", "linux"), "/run/media/sam/Drive")
        self.assertIsNone(backups.mount_of("/home/sam/Dropbox", "linux"))
        for s in ("missing", "blocked", "full", "inside", "nolock"):
            self.assertTrue(backups.STATES[s])

    def test_copies_keep_only_the_newest_and_a_missing_drive_is_said_plainly(self):
        src = fake_backup(os.path.join(self.home, "backups"), "nightly-20261103-033000.tar.gz")
        to = os.path.join(self.d, "drive", "Homelab")
        for day in ("01", "02"):
            fake_backup(to, f"nightly-202611{day}-033000.tar.gz")
        self.assertEqual(backups.copy_out(src, to, 2, self.home, "linux"), ("ok", "nightly-20261103-033000.tar.gz"))
        self.assertEqual(sorted(os.listdir(to)), ["nightly-20261102-033000.tar.gz", "nightly-20261103-033000.tar.gz"])  # keep 2
        self.assertEqual(backups.copy_out(src, "/Volumes/NotPluggedIn/Homelab", 2, self.home, "mac"), ("missing", None))

    @unittest.skipUnless(shutil.which("openssl") and backups.can_lock(), "openssl with PBKDF2 is not here")
    def test_a_passphrase_locks_copies_and_only_it_opens_them(self):
        self.assertEqual(backups.set_passphrase(self.home, "short")[0], False)
        self.assertTrue(backups.set_passphrase(self.home, "correct horse battery")[0])
        self.assertEqual(stat.S_IMODE(os.stat(os.path.join(self.home, backups.PASSFILE)).st_mode), 0o600)
        src = fake_backup(os.path.join(self.home, "backups"), "backup-20261103-120000.tar.gz", 4000)
        to = os.path.join(self.d, "drive")
        state, name = backups.copy_out(src, to, 7, self.home, "linux")
        self.assertEqual((state, name), ("ok", "backup-20261103-120000.tar.gz.enc"))
        self.assertNotEqual(open(os.path.join(to, name), "rb").read()[:20], b"x" * 20)  # not readable as it was
        out = os.path.join(self.d, "back.tar.gz")
        self.assertTrue(backups.unlock(os.path.join(to, name), out, os.path.join(self.home, backups.PASSFILE)))
        self.assertEqual(open(out, "rb").read(), b"x" * 4000)
        wrong = os.path.join(self.d, "wrong")
        open(wrong, "w").write("not it at all")
        self.assertFalse(backups.unlock(os.path.join(to, name), os.path.join(self.d, "w.tar.gz"), wrong))
        self.assertTrue(backups.set_passphrase(self.home, "")[0])
        self.assertFalse(os.path.exists(os.path.join(self.home, backups.PASSFILE)))

    def test_an_alert_is_said_at_most_once_a_day(self):
        self.assertTrue(backups.once_a_day(self.d, "disk-90", 1000.0))
        self.assertFalse(backups.once_a_day(self.d, "disk-90", 1001.0))
        self.assertTrue(backups.once_a_day(self.d, "disk-90", 1000.0 + 2 * 86400))

    def test_telegram_needs_the_bot_and_never_raises(self):
        self.assertFalse(backups.telegram({}, "hi"))
        sent = []
        self.assertTrue(backups.telegram({"TG_TOKEN": "t", "TG_CHAT": "1"}, "hi", http=lambda url, body: sent.append((url, body)) or True))
        self.assertIn("/bott/sendMessage", sent[0][0])
        self.assertFalse(backups.telegram({"TG_TOKEN": "t", "TG_CHAT": "1"}, "hi", http=lambda url, body: (_ for _ in ()).throw(OSError("offline"))))


class Helper(unittest.TestCase):
    """The host helper's side: Back up now, the copy after a backup, a copy waiting for its drive, alerts, the assistant being down."""
    def setUp(self):
        self.d = tempfile.mkdtemp(prefix="hl-bkh-")
        self.addCleanup(shutil.rmtree, self.d, ignore_errors=True)
        self.home, self.sent, self.calls = os.path.join(self.d, "home"), [], []
        self.data = os.path.join(self.home, "data")
        os.makedirs(self.data)
        self.t = [100000.0]
        self.disk = [100, 50]  # total, free
        real = agent.shutil.disk_usage
        agent.shutil.disk_usage = lambda p: type("U", (), {"total": self.disk[0], "free": self.disk[1], "used": self.disk[0] - self.disk[1]})()
        self.addCleanup(setattr, agent.shutil, "disk_usage", real)
        self.a = agent.Agent(self.data, self.d, run=self.fake, log=lambda *a: None, now=lambda: self.t[0], home=self.home, platform="linux", notify=self.sent.append)

    def fake(self, cmd, **kw):
        self.calls.append(cmd)
        if cmd[:2] == ["docker", "inspect"]:
            return 0, getattr(self, "running", "true")
        return 0, ""

    def night(self, **kw):
        json.dump({"night": {"backup": True, **kw}}, open(os.path.join(self.data, "settings.json"), "w"))

    def status(self):
        return backups.read_status(self.data)

    def test_a_backup_is_recorded_then_copied_and_a_failure_is_said_once(self):
        to = os.path.join(self.d, "drive")
        self.night(offsite_to=to, offsite_keep=3)
        fake_backup(self.a.backups, "nightly-20261103-033000.tar.gz")
        self.a.after_backup(True, "  ok    Backup saved", "nightly")
        st = self.status()
        self.assertTrue(st["last"]["ok"])
        self.assertEqual((st["offsite"]["state"], st["offsite"]["file"]), ("ok", "nightly-20261103-033000.tar.gz"))
        self.assertTrue(os.path.isfile(os.path.join(to, "nightly-20261103-033000.tar.gz")))
        self.a.after_backup(False, "  stop  Could not make the backup (disk full).", "nightly")
        self.a.after_backup(False, "  stop  Could not make the backup (disk full).", "nightly")
        self.assertEqual(len(self.sent), 1)
        self.assertIn("did not work", self.sent[0])
        self.assertIn("disk full", self.status()["last"]["msg"])

    def test_a_copy_waits_for_its_drive_and_goes_once_it_is_back(self):
        drive = os.path.join(self.d, "Drive")
        to = os.path.join(drive, "Homelab")
        self.night(offsite_to=to)
        real = backups.mount_of
        backups.mount_of = lambda path, platform: drive if path.startswith(drive) else real(path, platform)
        self.addCleanup(setattr, backups, "mount_of", real)
        fake_backup(self.a.backups, "nightly-20261103-033000.tar.gz")
        self.a.after_backup(True, "ok", "nightly")
        self.assertEqual(self.status()["offsite"]["state"], "missing")
        self.assertIn("not plugged in", self.sent[0])
        os.makedirs(drive)  # plugged in
        self.a.watch()
        self.assertEqual(self.status()["offsite"]["state"], "ok")
        self.assertTrue(os.path.isfile(os.path.join(to, "nightly-20261103-033000.tar.gz")))

    def test_the_assistant_being_down_for_ten_minutes_is_said_once_unless_you_stopped_it(self):
        self.running = "false"
        self.a.watch()
        self.assertEqual(self.sent, [])  # just stopped: wait
        self.t[0] += 601
        self.a.watch()
        self.assertEqual(len(self.sent), 1)
        self.assertIn(["docker", "start", "telegram-bot"], self.calls)
        self.sent.clear()
        open(os.path.join(self.data, "stopped-by-you.json"), "w").write("{}")
        self.t[0] += 86400 * 2
        self.a.watch(); self.t[0] += 601; self.a.watch()
        self.assertEqual(self.sent, [])

    def test_a_nearly_full_disk_is_said_once_a_day(self):
        self.disk = [100, 8]
        self.a.watch(); self.a.watch()
        self.assertEqual(len(self.sent), 1)
        self.assertIn("92% full", self.sent[0])
        self.assertEqual(self.status()["disk"]["pct"], 92)

    def test_alerts_can_be_turned_off(self):
        self.night(alerts=False)
        self.a.after_backup(False, "stop  broken", "nightly")
        self.assertEqual(self.sent, [])

    def test_requests_for_backups_are_checked(self):
        self.assertEqual(self.a.handle("restore ../../etc/passwd"), (False, "that backup is not in the backups folder"))
        self.assertEqual(self.a.handle("restore nightly-20261103-033000.tar.gz")[0], False)  # not there
        self.assertEqual(self.a.handle("passphrase zz")[0], False)
        ok, msg = self.a.handle("passphrase " + "long enough pass".encode().hex())
        self.assertTrue(ok)
        self.assertTrue(self.status()["passphrase"])
        self.assertTrue(self.a.handle("passphrase -")[0])
        self.assertFalse(self.status()["passphrase"])
        self.assertTrue(self.a.handle("drives")[0])
        self.assertIn("drives", self.status())
        self.assertEqual(self.a.handle("backup extra")[0], False)


class Api(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.bot = harness.load_bot()
        cls.base = harness.start_api(cls.bot)[1]

    def setUp(self):
        import modules.server as m
        self.m, self.asked = m, []
        for k, v in {"host_action": lambda act, name="": self.asked.append((act, name)) or {"ok": True, "msg": "fine"},
                     "CAPS": type("C", (), {"missing": lambda self, caps: []})()}.items():
            self.addCleanup(setattr, m, k, getattr(m, k)); setattr(m, k, v)

    def test_the_page_reads_the_status_and_saves_settings(self):
        json.dump({"last": {"ok": True, "at": 1.0, "size": 5}}, open(f"{self.m.DATA}/backup-status.json", "w"))
        code, out = harness.call(self.base, "GET", "/server/backups")
        self.assertEqual((code, out["helper"], out["status"]["last"]["ok"]), (200, True, True))
        code, out = harness.call(self.base, "POST", "/server/backups/settings", {"backup": True, "backup_at": "2:00 AM", "offsite_to": "/Volumes/Backup/Homelab"})
        self.assertEqual(code, 200, out)
        self.assertEqual((out["night"]["backup"], out["night"]["backup_at"], out["night"]["offsite_to"]), (True, "2:00 AM", "/Volumes/Backup/Homelab"))
        self.assertIn(("offsite", ""), self.asked)  # the helper checks the folder at once
        self.assertEqual(harness.call(self.base, "POST", "/server/backups/settings", {"offsite_to": "relative/folder"})[0], 400)
        self.assertEqual(harness.call(self.base, "POST", "/server/backups/settings", {"backup_keep": 0})[0], 400)
        self.assertEqual(harness.call(self.base, "POST", "/server/backups/settings", {"backup": "yes"})[0], 400)
        self.assertEqual(harness.call(self.base, "POST", "/server/backups/passphrase", {"passphrase": "short"})[0], 400)
        harness.call(self.base, "POST", "/server/backups/passphrase", {"passphrase": "long enough here"})
        self.assertIn(("passphrase", "long enough here".encode().hex()), self.asked)  # hex, so spaces survive the request file
        harness.call(self.base, "POST", "/server/backups/restore", {"name": "nightly-20261103-033000.tar.gz"})
        self.assertIn(("restore", "nightly-20261103-033000.tar.gz"), self.asked)
        harness.call(self.base, "POST", "/server/backups/settings", {"backup": False, "offsite_to": ""})


if __name__ == "__main__":
    unittest.main()
