"""The command line and the update flow. git is real (a throwaway origin and clone); docker, the dashboard and the keyboard are pretend."""
import datetime
import io
import json
import os
import shutil
import stat
import subprocess
import tarfile
import tempfile
import unittest

import harness  # noqa: F401  (puts core on the path)
from core import cli, manifest, migrations

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
GIT_ENV = {"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@example.test", "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@example.test",
           "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_SYSTEM": os.devnull}

# What a new version's `python -m core migrate` does in the test repo: copies marker.txt into the data folder, or fails.
FAKE_MAIN = '''import os, sys
data = sys.argv[2]
if os.path.exists(os.path.join(os.path.dirname(__file__), "..", "BREAK_MIGRATION")):
    open(os.path.join(data, "half-migrated.txt"), "w").write("x")
    sys.exit("boom: cannot convert journal")
open(os.path.join(data, "migrated.txt"), "w").write("yes")
'''


def git(cwd, *args):
    r = subprocess.run(["git", *args], cwd=cwd, env={**os.environ, **GIT_ENV}, capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    return r.stdout.strip()


class Fake:
    """Pretend docker, dashboard, clock and keyboard. Records what it was asked."""
    def __init__(self):
        self.calls, self.probes, self.up_rc, self.answers, self.running = [], [], 0, [], True
        self.docker = True

    def run(self, cmd, cwd=None, stream=False, env=None):
        if cmd[0] == "docker":
            self.calls.append(" ".join(cmd[1:]))
            if cmd[1] == "ps":
                return 0, "telegram-bot\nlanding" if self.running else ""
            if "up" in cmd:
                return self.up_rc, ""
            if "ps" in cmd:
                return 0, "landing|running\ntelegram-bot|running"
            return 0, ""
        return cli.shell(cmd, cwd, stream, env)

    def which(self, name):
        return ("/usr/bin/docker" if self.docker else None) if name == "docker" else shutil.which(name)

    def probe(self):
        return self.probes.pop(0) if len(self.probes) > 1 else (self.probes[0] if self.probes else None)

    def prompt(self, q):
        return self.answers.pop(0) if self.answers else ""


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="hl-cli-")
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.origin, self.work, self.app = (os.path.join(self.tmp, n) for n in ("origin.git", "work", "app"))
        git(self.tmp, "init", "-q", "--bare", "-b", "main", self.origin)
        git(self.tmp, "clone", "-q", self.origin, self.work)
        os.makedirs(os.path.join(self.work, "core"))
        os.makedirs(os.path.join(self.work, "stack"))
        self.commit("v1", "VERSION", "1")
        open(os.path.join(self.work, "core", "__init__.py"), "w").close()
        open(os.path.join(self.work, "core", "__main__.py"), "w").write(FAKE_MAIN)
        shutil.copy(os.path.join(ROOT, "stack", "config.example.yaml"), os.path.join(self.work, "stack"))
        self.commit("add core", "stack/keep", "")
        git(self.work, "push", "-q", "origin", "main")
        git(self.tmp, "clone", "-q", self.origin, self.app)
        os.symlink(os.path.join(ROOT, "modules"), os.path.join(self.app, "modules"))  # untracked, so it does not count as a changed file
        self.home = os.path.join(self.tmp, "home")
        self.data = os.path.join(self.home, "data")
        os.makedirs(os.path.join(self.data, "journal"))
        open(os.path.join(self.data, "journal", "a.json"), "w").write('{"entry": "original"}')
        os.makedirs(os.path.join(self.app, "stack", "secrets"), exist_ok=True)
        open(os.path.join(self.app, "stack", "secrets", "key.txt"), "w").write("s3cret")
        with open(os.path.join(self.app, "stack", ".env"), "w") as f:
            f.write(f"HL_DATA_DIR={self.data}\nHL_STATS_DIR={self.home}/stats\nHL_PORT=3999\nTG_TOKEN=abc\n")
        os.chmod(os.path.join(self.app, "stack", ".env"), 0o600)
        shutil.copy(os.path.join(ROOT, "stack", "config.example.yaml"), os.path.join(self.app, "stack", "config.yaml"))
        self.fake = Fake()
        self.fake.probes = [{"ok": True, "modules": [{"state": "on"}]}]
        self.lines = []
        self.clock = datetime.datetime(2026, 11, 3, 16, 30, 0)
        self.ctx = self.make()
        self.ctx.platform = "linux"  # the same result on a Mac and on Linux; a test that needs a Mac sets "mac" itself

    def make(self, **over):
        c = cli.Ctx(self.app, env={"HL_HOME": self.home, "PATH": os.environ["PATH"]}, out=self.lines.append, run=self.fake.run, probe=self.fake.probe,
                    prompt=self.fake.prompt, which=self.fake.which, sleep=lambda s: None, now=self.tick, health_wait=9, **over)
        return c

    def tick(self):
        self.clock += datetime.timedelta(seconds=1)
        return self.clock

    def commit(self, msg, name, text):
        with open(os.path.join(self.work, name), "w") as f:
            f.write(text)
        git(self.work, "add", "-A")
        git(self.work, "commit", "-q", "-m", msg)

    def publish(self, tag=None, msg="next"):
        self.commit(msg, "VERSION", msg)
        git(self.work, "push", "-q", "origin", "main")
        if tag:
            git(self.work, "tag", tag)
            git(self.work, "push", "-q", "origin", tag)

    def say(self):
        return "\n".join(str(l) for l in self.lines)

    def head(self):
        return git(self.app, "rev-parse", "HEAD")

    def go(self, *argv):
        self.lines.clear()
        return cli.main(list(argv), self.ctx)


class Backups(Base):
    def test_a_backup_holds_data_settings_and_secrets_privately(self):
        self.assertEqual(self.go("backup"), 0)
        path = os.path.join(self.home, "backups", "backup-20261103-163001.tar.gz")
        self.assertTrue(os.path.isfile(path), self.say())
        self.assertEqual(stat.S_IMODE(os.stat(path).st_mode), 0o600)
        names = tarfile.open(path).getnames()
        for n in ("meta.json", "data/journal/a.json", "stack/config.yaml", "stack/.env", "stack/secrets/key.txt"):
            self.assertIn(n, names)
        self.assertIn("keep it somewhere private", self.say())

    def test_restore_puts_everything_back_and_keeps_a_safety_copy(self):
        self.go("backup")
        path = os.path.join(self.home, "backups", os.listdir(os.path.join(self.home, "backups"))[0])
        open(os.path.join(self.data, "journal", "a.json"), "w").write('{"entry": "ruined"}')
        open(os.path.join(self.data, "extra.json"), "w").write("{}")
        self.fake.answers = ["y"]
        self.assertEqual(self.go("restore", path), 0, self.say())
        self.assertEqual(json.load(open(os.path.join(self.data, "journal", "a.json"))), {"entry": "original"})
        self.assertFalse(os.path.exists(os.path.join(self.data, "extra.json")))
        self.assertTrue([f for f in os.listdir(os.path.join(self.home, "backups")) if f.startswith("before-restore-")])
        self.assertEqual(stat.S_IMODE(os.stat(os.path.join(self.app, "stack", ".env")).st_mode), 0o600)
        self.assertIn("compose stop landing telegram-bot docker-proxy", self.fake.calls)
        self.assertIn("compose up -d --build landing telegram-bot docker-proxy", self.fake.calls)

    def test_restore_asks_first_and_cancel_changes_nothing(self):
        self.go("backup")
        path = os.path.join(self.home, "backups", os.listdir(os.path.join(self.home, "backups"))[0])
        open(os.path.join(self.data, "journal", "a.json"), "w").write("changed")
        self.assertEqual(self.go("restore", path), 1)  # no answer, as in a script
        self.assertIn("Cancelled", self.say())
        self.assertEqual(open(os.path.join(self.data, "journal", "a.json")).read(), "changed")

    def test_restore_refuses_files_that_are_not_ours_or_reach_outside(self):
        evil = os.path.join(self.tmp, "evil.tar.gz")
        with tarfile.open(evil, "w:gz") as t:
            for name, body in (("meta.json", b'{"created": "2026-01-01T00:00:00"}'), ("../escape.txt", b"x")):
                i = tarfile.TarInfo(name)
                i.size = len(body)
                t.addfile(i, io.BytesIO(body))
        self.assertEqual(self.go("restore", evil, "--yes"), 1)
        self.assertIn("not a backup made by this tool", self.say())
        self.assertFalse(os.path.exists(os.path.join(self.tmp, "escape.txt")))
        junk = os.path.join(self.tmp, "junk.tar.gz")
        open(junk, "w").write("not a tar")
        self.assertEqual(self.go("restore", junk, "--yes"), 1)
        self.assertEqual(self.go("restore", os.path.join(self.tmp, "nope"), "--yes"), 1)

    def test_old_automatic_snapshots_are_pruned_but_your_own_backups_never_are(self):
        for _ in range(8):
            cli.make_backup(self.ctx, "snapshot")
            cli.make_backup(self.ctx, "backup")
        names = os.listdir(os.path.join(self.home, "backups"))
        self.assertEqual(len([n for n in names if n.startswith("snapshot-")]), cli.KEEP["snapshot"])
        self.assertEqual(len([n for n in names if n.startswith("backup-")]), 8)

    def test_an_unreadable_file_gives_a_message_not_a_crash(self):
        bad = os.path.join(self.data, "locked")
        open(bad, "w").write("x")
        os.chmod(bad, 0)
        self.addCleanup(os.chmod, bad, 0o600)
        if os.access(bad, os.R_OK):
            self.skipTest("running as a user that can read anything")
        self.assertEqual(self.go("backup"), 1)
        self.assertIn("Could not make the backup", self.say())
        self.assertEqual([f for f in os.listdir(os.path.join(self.home, "backups")) if f.endswith(".part")], [])


class Updates(Base):
    def test_up_to_date(self):
        self.assertEqual(self.go("update", "--channel", "edge"), 0)
        self.assertIn("Already up to date", self.say())

    def test_check_and_dry_run_change_nothing(self):
        self.publish("v1.0.0", "second")
        before = self.head()
        self.assertEqual(self.go("update", "--check"), 0)
        self.assertIn("Update available", self.say())
        self.assertIn("second", self.say())
        self.assertEqual(self.go("update", "--dry-run"), 0)
        self.assertIn("Dry run", self.say())
        self.assertEqual(self.head(), before)
        self.assertEqual(self.fake.calls, [])
        self.assertFalse(os.path.exists(os.path.join(self.home, "backups")))

    def test_stable_follows_the_newest_full_release_not_prereleases_or_edge(self):
        self.publish("v1.0.0", "one")
        tag1 = git(self.work, "rev-parse", "HEAD")
        self.publish("v1.1.0-rc1", "rc")
        self.publish(None, "unreleased work")
        self.fake.answers = ["y"]
        self.assertEqual(self.go("update"), 0, self.say())
        self.assertEqual(self.head(), tag1)
        self.assertTrue(os.path.exists(os.path.join(self.data, "migrated.txt")))  # the new version's data step ran
        self.assertEqual(self.go("update", "--check"), 0)
        self.assertIn("Already up to date", self.say())

    def test_edge_follows_main(self):
        self.publish(None, "unreleased work")
        self.fake.answers = ["y"]
        self.assertEqual(self.go("update", "--channel", "edge"), 0, self.say())
        self.assertEqual(self.head(), git(self.work, "rev-parse", "HEAD"))
        self.assertEqual(open(os.path.join(self.home, "channel")).read().strip(), "edge")
        self.assertEqual(cli.read_channel(self.ctx), "edge")

    def test_no_release_yet_on_stable_says_what_to_do(self):
        self.publish(None, "work")
        self.assertEqual(self.go("update"), 1)
        self.assertIn("no stable release yet", self.say())
        self.assertIn("--channel edge", self.say())

    def test_success_takes_a_snapshot_stops_updates_and_restarts_in_order(self):
        self.publish("v1.0.0", "one")
        self.assertEqual(self.go("update", "--yes"), 0, self.say())
        self.assertTrue([f for f in os.listdir(os.path.join(self.home, "backups")) if f.startswith("snapshot-")])
        stops = [i for i, c in enumerate(self.fake.calls) if c.startswith("compose stop")]
        ups = [i for i, c in enumerate(self.fake.calls) if "up -d" in c]
        self.assertTrue(stops and ups and stops[0] < ups[0])
        self.assertIn("Updated to", self.say())

    def test_it_asks_first_and_no_answer_means_no(self):
        self.publish("v1.0.0", "one")
        before = self.head()
        self.assertEqual(self.go("update"), 1)
        self.assertIn("Cancelled", self.say())
        self.assertEqual(self.head(), before)

    def test_changed_files_in_the_program_folder_block_it(self):
        self.publish("v1.0.0", "one")
        open(os.path.join(self.app, "VERSION"), "w").write("my edit")
        self.assertEqual(self.go("update", "--yes"), 1)
        self.assertIn("changed files", self.say())
        self.assertIn("M VERSION", self.say())

    def test_no_network_says_so(self):
        shutil.rmtree(self.origin)
        self.assertEqual(self.go("update", "--yes"), 1)
        self.assertIn("Could not reach", self.say())

    def test_a_copy_that_has_diverged_is_left_alone(self):
        self.publish("v1.0.0", "one")
        with open(os.path.join(self.app, "local.txt"), "w") as f:
            f.write("mine")
        git(self.app, "add", "local.txt")
        git(self.app, "commit", "-q", "-m", "local work")
        before = self.head()
        self.assertEqual(self.go("update", "--channel", "edge", "--yes"), 1)
        self.assertIn("ahead of or different", self.say())
        self.assertEqual(self.head(), before)

    def test_a_copy_without_git_cannot_update_itself(self):
        shutil.rmtree(os.path.join(self.app, ".git"))
        self.assertEqual(self.go("update"), 1)
        self.assertIn("not installed with git", self.say())

    def test_a_failed_data_step_rolls_back_code_and_data(self):
        before = self.head()
        self.commit("breaks", "BREAK_MIGRATION", "1")
        git(self.work, "push", "-q", "origin", "main")
        self.fake.answers = []
        self.assertEqual(self.go("update", "--channel", "edge", "--yes"), 1)
        out = self.say()
        self.assertIn("Updating your saved data failed", out)
        self.assertIn("boom: cannot convert journal", out)
        self.assertIn("Your data is back as it was", out)
        self.assertEqual(self.head(), before)
        self.assertFalse(os.path.exists(os.path.join(self.data, "half-migrated.txt")))  # the snapshot undid the half-done change
        self.assertEqual(json.load(open(os.path.join(self.data, "journal", "a.json"))), {"entry": "original"})
        self.assertIn("running again", out)

    def test_a_new_version_that_will_not_start_rolls_back(self):
        self.publish("v1.0.0", "one")
        before = self.head()
        self.fake.up_rc = 1
        self.assertEqual(self.go("update", "--yes"), 1)
        self.assertIn("would not start", self.say())
        self.assertEqual(self.head(), before)

    def test_a_new_version_that_fails_its_health_check_rolls_back(self):
        self.publish("v1.0.0", "one")
        before = self.head()
        self.fake.probes = [{"ok": True, "modules": []}, None, None, None]  # healthy before, silent after
        self.assertEqual(self.go("update", "--yes"), 1)
        self.assertIn("did not pass its health check", self.say())
        self.assertEqual(self.head(), before)

    def test_a_broken_module_after_the_update_counts_as_unhealthy_if_it_was_fine_before(self):
        self.publish("v1.0.0", "one")
        self.fake.probes = [{"ok": True}, {"ok": False}]
        self.assertEqual(self.go("update", "--yes"), 1)

    def test_a_system_that_was_already_unwell_only_has_to_answer(self):
        self.publish("v1.0.0", "one")
        self.fake.probes = [{"ok": False}]
        self.assertEqual(self.go("update", "--yes"), 0, self.say())


class Everyday(Base):
    def test_status_shows_version_services_and_health(self):
        self.assertEqual(self.go("status"), 0)
        out = self.say()
        self.assertIn("landing: running", out)
        self.assertIn("1 on", out)
        self.assertIn("all fine", out)
        self.fake.probes = [None]
        self.assertEqual(self.go("status"), 1)
        self.assertIn("not answering on port 3999", self.say())

    def test_without_docker_every_command_says_how_to_fix_it(self):
        self.fake.docker = False
        for cmd in ("status", "start", "stop", "restart", "doctor", "logs"):
            self.assertEqual(self.go(cmd), 1, cmd)
            self.assertIn("Docker is not installed", self.say())

    def test_start_stop_restart_logs_only_touch_our_services(self):
        for cmd in ("start", "stop", "restart"):
            self.go(cmd)
        self.go("logs", "-f")
        self.assertEqual(self.fake.calls, ["compose up -d --build landing telegram-bot docker-proxy", "compose stop landing telegram-bot docker-proxy",
                                           "compose restart landing telegram-bot docker-proxy", "compose logs --tail 100 -f telegram-bot"])

    def test_apps_add_starts_only_the_new_ones_with_what_they_need_and_start_includes_them(self):
        self.assertEqual(self.go("apps"), 0)
        self.assertIn("off  ollama", self.say())
        self.assertEqual(self.go("apps", "add", "open-webui"), 0)  # needs the AI engine, so that comes too
        self.assertEqual(self.fake.calls, ["compose up -d ollama open-webui"])
        self.assertIn("Local AI engine (Ollama), AI chat (Open WebUI) started", self.say())
        self.fake.calls.clear()
        self.go("start")
        self.assertEqual(self.fake.calls, ["compose up -d --build landing telegram-bot docker-proxy ollama open-webui"])
        self.assertEqual(self.go("apps", "add", "nope"), 2)

    def test_on_a_mac_the_ai_engine_runs_on_the_mac_itself_and_docker_leaves_it_out(self):
        import contextlib
        from unittest import mock
        self.ctx.platform = "mac"
        brew = []
        real_run, real_which = self.ctx.run, self.ctx.which
        self.ctx.run = lambda cmd, cwd=None, stream=False, env=None: brew.append(" ".join(cmd)) or (0, "") if cmd[0] == "brew" else real_run(cmd, cwd, stream, env)
        self.ctx.which = lambda n: "/opt/homebrew/bin/brew" if n == "brew" else None if n == "ollama" else real_which(n)
        with mock.patch.object(cli.urllib.request, "urlopen", lambda *a, **k: contextlib.nullcontext()):
            self.assertEqual(self.go("apps", "add", "open-webui"), 0)
        self.assertEqual(brew, ["brew install ollama", "brew services start ollama"])
        self.assertEqual(self.fake.calls, ["compose up -d open-webui"])  # no Docker AI engine
        self.assertEqual(cli._apps.native(self.data), ["ollama"])
        self.assertEqual(manifest.brew(self.home), ["ollama"])  # installed by us, so uninstall --purge and dev-reset may remove it
        self.assertIn("host.docker.internal", open(os.path.join(self.data, "settings.json")).read())
        self.assertIn("HL_OLLAMA_URL=http://host.docker.internal:11434", open(os.path.join(self.app, "stack", ".env")).read())
        self.fake.calls.clear()
        self.go("start")
        self.assertEqual(self.fake.calls, ["compose up -d --build landing telegram-bot docker-proxy open-webui"])
        self.fake.calls.clear()
        self.assertEqual(self.go("apps", "remove", "open-webui", "ollama"), 0)
        self.assertIn("brew services stop ollama", brew)
        self.assertEqual(self.fake.calls, ["compose rm -s -f open-webui"])
        self.assertEqual(cli._apps.native(self.data), [])

    def test_apps_remove_refuses_to_break_another_app_and_keeps_data(self):
        self.go("apps", "add", "open-webui")
        self.fake.calls.clear()
        self.assertEqual(self.go("apps", "remove", "ollama"), 1)
        self.assertIn("AI chat (Open WebUI) needs it", self.say())
        self.assertEqual(self.go("apps", "remove", "open-webui", "ollama"), 0)
        self.assertEqual(self.fake.calls, ["compose rm -s -f open-webui ollama"])
        self.assertEqual(cli._apps.chosen(self.data), [])

    def test_access_lan_needs_a_pin_then_opens_only_the_dashboard(self):
        self.assertEqual(self.go("access", "lan"), 1)
        self.assertIn("Set a PIN first", self.say())
        json.dump({"_pin": {"salt": "00", "hash": "x"}}, open(os.path.join(self.data, "settings.json"), "w"))
        real = self.ctx.run
        self.ctx.run = lambda cmd, cwd=None, stream=False, env=None: (0, "192.168.1.20 10.0.0.5") if cmd[0] == "hostname" else real(cmd, cwd, stream, env)
        self.assertEqual(self.go("access", "lan"), 0)
        self.assertIn("compose up -d landing", self.fake.calls)
        env = open(os.path.join(self.app, "stack", ".env")).read()
        self.assertIn("HL_BIND=0.0.0.0", env)
        self.assertIn("TG_TOKEN=abc", env)  # the rest of .env is kept
        self.assertEqual(json.load(open(os.path.join(self.data, "access.json")))["url"], "http://192.168.1.20:3999")
        self.assertEqual(self.go("access", "local"), 0)
        self.assertEqual(open(os.path.join(self.app, "stack", ".env")).read().count("HL_BIND="), 1)

    def test_nightly_backup_keeps_only_the_newest(self):
        dest = os.path.join(self.tmp, "nightly")
        for _ in range(4):
            self.assertEqual(self.go("backup", "--to", dest, "--keep", "2"), 0)
        self.assertEqual(len([f for f in os.listdir(dest) if f.startswith("nightly-")]), 2)

    def test_settings_sync_copies_settings_without_the_pin_to_your_repo(self):
        remote = os.path.join(self.tmp, "settings.git")
        git(self.tmp, "init", "-q", "--bare", "-b", "main", remote)
        json.dump({"_pin": {"hash": "x"}, "owner": {"name": "Sam"}}, open(os.path.join(self.data, "settings.json"), "w"))
        self.assertEqual(self.go("settings-sync", "not a repo"), 2)
        work = os.path.join(self.home, "settings-repo")
        git(self.tmp, "clone", "-q", remote, work)
        self.ctx.out = self.lines.append
        rc = cli.settings_sync(self.ctx, "git@example.com:you/settings.git")  # the clone is there already, so the address only names it
        self.assertEqual(rc, 0, self.say())
        saved = json.load(open(os.path.join(work, "settings.json")))
        self.assertEqual(saved, {"owner": {"name": "Sam"}})
        self.assertTrue(os.path.isfile(os.path.join(work, "config.yaml")))
        self.assertIn("Settings on", git(remote, "log", "--format=%s", "-1"))
        self.assertEqual(cli.settings_sync(self.ctx, "git@example.com:you/settings.git"), 0)
        self.assertIn("unchanged", self.say())

    def test_doctor_runs_inside_the_assistant_or_says_to_start_it(self):
        self.go("doctor")
        self.assertIn("compose exec -T telegram-bot python -m core doctor", self.fake.calls)
        self.fake.running = False
        self.assertEqual(self.go("doctor"), 1)
        self.assertIn("homelab start", self.say())

    def test_modules_list_enable_disable(self):
        self.go("modules")
        self.assertRegex(self.say(), r"on\s+gym\s")
        self.assertNotIn("_template", self.say())
        self.assertEqual(self.go("modules", "disable", "gym"), 0, self.say())
        self.assertEqual(json.load(open(os.path.join(self.data, "settings.json")))["modules"]["gym"], False)
        self.assertIn("compose restart telegram-bot", self.fake.calls)
        self.go("modules")
        self.assertRegex(self.say(), r"off\s+gym\s")
        self.assertEqual(self.go("modules", "enable", "gym"), 0)
        self.go("modules")
        self.assertRegex(self.say(), r"on\s+gym\s")
        self.assertEqual(self.go("modules", "enable", "nope"), 1)
        self.assertIn("no module called", self.say())

    def test_modules_without_a_running_assistant_says_it_applies_later(self):
        self.fake.running = False
        self.assertEqual(self.go("modules", "disable", "gym"), 0)
        self.assertIn("next time the assistant starts", self.say())

    def test_modules_when_the_folder_belongs_to_someone_else(self):
        os.chmod(self.data, 0o500)
        self.addCleanup(os.chmod, self.data, 0o700)
        if os.access(self.data, os.W_OK):
            self.skipTest("running as a user that can write anywhere")
        self.assertEqual(self.go("modules", "disable", "gym"), 1)
        self.assertIn("Could not save", self.say())

    def editor(self, body):
        p = os.path.join(self.tmp, "editor.sh")
        open(p, "w").write("#!/bin/sh\n" + body + "\n")
        os.chmod(p, 0o755)
        self.ctx.env["EDITOR"] = p

    def test_config_edit_keeps_a_good_change_and_undoes_a_bad_one(self):
        path = os.path.join(self.app, "stack", "config.yaml")
        good = open(path).read()
        self.editor('sed -i.bak "s/Alex/Sam/" "$1"; rm -f "$1.bak"')
        self.assertEqual(self.go("config", "edit"), 0, self.say())
        self.assertIn("Sam", open(path).read())
        kept = open(path).read()
        self.editor('printf "schedule:\\n  briefing: \\"25:99\\"\\n" > "$1"')
        self.assertEqual(self.go("config", "edit"), 1)
        self.assertIn("has problems", self.say())
        self.assertEqual(open(path).read(), kept)  # put back
        self.assertIn("previous version", self.say())
        self.editor('printf "owner: [\\n" > "$1"')
        self.assertEqual(self.go("config", "edit"), 1)
        self.assertEqual(open(path).read(), kept)
        self.fake.answers = ["y"]
        self.editor('printf "schedule:\\n  briefing: \\"25:99\\"\\n" > "$1"')
        self.assertEqual(self.go("config", "edit"), 0)  # you can insist
        self.assertNotEqual(good, "")

    def test_config_edit_with_no_editor_says_what_to_do(self):
        self.ctx.env.pop("EDITOR", None)
        self.ctx.which = lambda n: None
        self.assertEqual(self.go("config", "edit"), 1)
        self.assertIn("No text editor", self.say())

    def test_uninstall_keeps_data_and_asks(self):
        self.assertEqual(self.go("uninstall"), 1)
        self.assertIn("Cancelled", self.say())
        self.assertEqual(self.go("uninstall", "--yes"), 0)
        self.assertIn("compose down", " ".join(self.fake.calls))
        self.assertNotIn("-v", self.fake.calls[-1])
        self.assertTrue(os.path.isdir(self.data))
        self.assertTrue(os.path.isfile(os.path.join(self.app, "stack", ".env")))

    def test_purge_needs_the_name_typed_and_keeps_backups(self):
        self.go("backup")
        self.fake.answers = ["wrong"]
        self.assertEqual(self.go("uninstall", "--purge", "--yes"), 1)  # --yes does not skip typing the name
        self.assertTrue(os.path.isdir(self.data))
        self.fake.answers = [os.path.basename(self.home)]
        self.assertEqual(self.go("uninstall", "--purge"), 0, self.say())
        self.assertFalse(os.path.exists(self.data))
        self.assertFalse(os.path.exists(os.path.join(self.app, "stack", ".env")))
        self.assertFalse(os.path.exists(os.path.join(self.app, "stack", "secrets")))
        self.assertTrue(os.listdir(os.path.join(self.home, "backups")))
        calls = " | ".join(self.fake.calls)
        self.assertIn("compose down --rmi all", calls)  # the AI models were kept (Enter means no), so their volume stays
        self.assertIn("This will remove:", self.say())

    def test_purge_lists_what_goes_and_can_delete_the_models_too(self):
        manifest.add(self.home, "brew", "colima")
        manifest.add(self.home, "homebrew")
        self.fake.answers = [os.path.basename(self.home), "y"]
        self.assertEqual(self.go("uninstall", "--purge"), 0, self.say())
        out = self.say()
        self.assertIn("Homebrew: colima (and the Colima virtual machine)", out)
        self.assertIn("Homebrew: other programs use it, so it stays", out)
        self.assertIn("compose down -v --rmi all", " | ".join(self.fake.calls))

    def test_purge_refuses_a_dangerous_folder(self):
        self.ctx.data = os.path.expanduser("~")
        self.assertEqual(self.go("uninstall", "--purge"), 1)
        self.assertIn("Refusing", self.say())
        self.ctx.data = "/"
        self.assertEqual(self.go("uninstall", "--purge"), 1)

    def test_the_launcher_runs_through_a_link_and_prints_help(self):
        link = os.path.join(self.tmp, "homelab")
        os.symlink(os.path.join(ROOT, "bin", "homelab"), link)
        r = subprocess.run([link, "help"], capture_output=True, text=True, env={**os.environ, "HL_HOME": self.home})
        self.assertEqual(r.returncode, 0, r.stderr)
        for word in ("status", "update", "backup", "restore", "uninstall", "modules"):
            self.assertIn(word, r.stdout)
        self.assertNotIn(chr(0x2014), r.stdout)
        r = subprocess.run([link, "frobnicate"], capture_output=True, text=True)
        self.assertEqual(r.returncode, 2)

    def test_times_are_twelve_hour(self):
        self.assertEqual(cli.when(datetime.datetime(2026, 11, 3, 16, 5)), "Nov 3, 2026 4:05 PM")
        self.assertEqual(cli.when(datetime.datetime(2026, 11, 3, 0, 5)), "Nov 3, 2026 12:05 AM")


class Migrations(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp(prefix="hl-mig-")
        self.addCleanup(shutil.rmtree, self.d, ignore_errors=True)

    def test_runs_once_in_order_and_records(self):
        self.assertIn("0001_baseline", migrations.available())
        first = migrations.run_all(self.d, log=lambda m: None)
        self.assertEqual(first, migrations.available())
        self.assertEqual(migrations.run_all(self.d, log=lambda m: None), [])  # safe to run again
        self.assertEqual(migrations.pending(self.d), [])
        self.assertEqual(migrations.done(self.d), first)

    def test_a_failure_stops_there_and_is_not_recorded(self):
        import core.migrations as m
        real = m.available
        calls = []
        class Mod:
            def __init__(self, ok):
                self.ok = ok
            def run(self, d):
                calls.append(d)
                if not self.ok:
                    raise RuntimeError("bad file")
        mods = {"core.migrations.0100_ok": Mod(True), "core.migrations.0101_bad": Mod(False), "core.migrations.0102_never": Mod(True)}
        m.available = lambda: ["0100_ok", "0101_bad", "0102_never"]
        real_import = m.importlib.import_module
        m.importlib.import_module = lambda n: mods[n]
        try:
            with self.assertRaises(m.MigrationError) as e:
                m.run_all(self.d, log=lambda x: None)
        finally:
            m.available, m.importlib.import_module = real, real_import
        self.assertIn("0101_bad failed: bad file", str(e.exception))
        self.assertEqual(len(calls), 2)
        self.assertEqual(m.done(self.d), ["0100_ok"])

    def test_the_command_line_step(self):
        env = {**os.environ, "PYTHONPATH": ROOT}
        r = subprocess.run(["python3", "-W", "ignore", "-m", "core", "migrate", self.d], cwd=ROOT, env=env, capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertTrue(os.path.isfile(os.path.join(self.d, "migrations.json")))


if __name__ == "__main__":
    unittest.main()
