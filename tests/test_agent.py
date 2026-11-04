"""The host helper: it does only what its list allows, only to this project's containers, ignores old or odd requests, and installs as a user service."""
import json
import os
import shutil
import tempfile
import unittest

import harness  # noqa: F401  (puts core on the path)
from core import agent, cli


class Docker:
    def __init__(self, names=("telegram-bot", "landing"), fail=()):
        self.calls, self.names, self.fail = [], list(names), set(fail)

    def __call__(self, cmd, **kw):
        self.calls.append(cmd)
        if cmd[:2] == ["docker", "ps"]:
            return 0, "\n".join(self.names)
        if cmd[:2] == ["docker", "restart"] and cmd[2] in self.fail:
            return 1, "boom"
        return 0, ""


class Proc:
    def __init__(self, running):
        self.running = running

    def poll(self):
        return None if self.running else 0


class AgentTests(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp(prefix="hl-agent-")
        self.addCleanup(shutil.rmtree, self.d, ignore_errors=True)
        self.docker, self.t, self.lines, self.spawned = Docker(), [1000.0], [], []
        self.make()

    def make(self, **kw):
        self.a = agent.Agent(self.d, "/opt/app", run=self.docker, spawn=lambda: self.spawned.append(1) or Proc(True), log=self.lines.append, now=lambda: self.t[0], **kw)

    def drop(self, rid, text, age=0, raw=None):
        os.makedirs(self.a.req, exist_ok=True)
        p = os.path.join(self.a.req, rid)
        open(p, "w").write(text if raw is None else raw)
        os.utime(p, (self.t[0] - age, self.t[0] - age))

    def answer(self, rid):
        return json.load(open(os.path.join(self.a.res, rid + ".json")))

    def test_restart_and_start_work_only_for_this_projects_containers(self):
        self.drop("a1", "restart telegram-bot")
        self.drop("a2", "start landing")
        self.drop("a3", "restart some-other-thing")
        self.drop("a4", "restart ../../etc/passwd")
        self.drop("a5", "restart telegram-bot; reboot")
        self.assertEqual(self.a.drain(), 5)
        self.assertEqual(self.answer("a1"), {"ok": True, "msg": "telegram-bot restarted"})
        self.assertEqual(self.answer("a2"), {"ok": True, "msg": "landing started"})
        self.assertEqual(self.answer("a3"), {"ok": False, "msg": "unknown app some-other-thing"})
        for rid in ("a4", "a5"):
            self.assertFalse(self.answer(rid)["ok"])
        acted = [c for c in self.docker.calls if c[1] in ("restart", "start")]
        self.assertEqual(acted, [["docker", "restart", "telegram-bot"], ["docker", "start", "landing"]])
        self.assertIn("label=com.docker.compose.project=homelab", self.docker.calls[0])
        self.assertEqual(os.listdir(self.a.req), [])  # requests are consumed

    def test_a_failed_docker_command_is_reported_not_hidden(self):
        self.docker.fail = {"landing"}
        self.drop("b1", "restart landing")
        self.a.drain()
        self.assertEqual(self.answer("b1"), {"ok": False, "msg": "docker restart failed"})

    def test_no_docker_means_every_app_is_unknown(self):
        self.docker.names = []
        self.drop("c1", "restart telegram-bot")
        self.a.drain()
        self.assertFalse(self.answer("c1")["ok"])

    def test_unknown_actions_and_odd_files_are_refused_or_dropped(self):
        for rid, text in (("d1", "format disk"), ("d2", ""), ("d3", "update now"), ("d4", "reboot please")):
            self.drop(rid, text)
        self.drop("d5", "restart landing", raw="restart landing" + " " * 500)  # too big
        self.drop("bad id!", "restart landing")  # not a request id: dropped without an answer
        os.symlink("/etc/hostname", os.path.join(self.a.req, "d6"))
        self.a.drain()
        for rid in ("d1", "d2", "d3", "d4", "d5", "d6"):
            self.assertFalse(self.answer(rid)["ok"], rid)
        self.assertFalse(os.path.exists(os.path.join(self.a.res, "bad id!.json")))
        self.assertEqual([c for c in self.docker.calls if c[1] in ("restart", "start")], [])
        self.assertEqual(os.listdir(self.a.req), [])

    def test_old_requests_are_ignored_so_a_late_helper_never_acts_on_stale_orders(self):
        self.drop("e1", "restart landing", age=agent.MAX_AGE + 5)
        self.a.drain()
        self.assertIn("too old", self.answer("e1")["msg"])
        self.assertEqual([c for c in self.docker.calls if c[1] == "restart"], [])

    def test_reboot_is_off_unless_you_turned_it_on(self):
        self.drop("f1", "reboot")
        self.a.drain()
        self.assertFalse(self.answer("f1")["ok"])
        self.assertIn("agent install --allow-reboot", self.answer("f1")["msg"])
        self.assertFalse([c for c in self.docker.calls if c[0] in ("systemctl", "sudo")])

    def test_reboot_answers_first_then_reboots(self):
        self.make(allow_reboot=True)
        self.drop("g1", "reboot")
        self.a.drain()
        self.assertEqual(self.answer("g1"), {"ok": True, "msg": "rebooting"})
        self.assertTrue([c for c in self.docker.calls if c[0] in ("systemctl", "sudo")])

    def test_update_starts_once_and_answers_before_it_finishes(self):
        self.drop("h1", "update")
        self.drop("h2", "update")
        self.a.drain()
        self.assertTrue(self.answer("h1")["ok"])
        self.assertEqual((self.answer("h2")["ok"], self.answer("h2")["msg"]), (False, "an update is already running"))
        self.assertEqual(len(self.spawned), 1)

    def test_add_and_remove_take_one_known_app_and_run_one_at_a_time(self):
        jobs = []
        self.make(spawn_apps=lambda action, app: jobs.append((action, app)) or Proc(True))
        for rid, text in (("j1", "add ollama"), ("j2", "remove ollama"), ("j3", "add rm -rf"), ("j4", "add")):
            self.drop(rid, text)
        self.a.drain()
        self.assertTrue(self.answer("j1")["ok"])
        self.assertEqual(self.answer("j2")["msg"], "another app change is still running")
        self.assertFalse(self.answer("j3")["ok"])
        self.assertFalse(self.answer("j4")["ok"])
        self.assertEqual(jobs, [("add", "ollama")])
        jobs.clear(); self.a.apps_proc = None
        self.drop("j5", "access everyone")
        self.drop("j6", "access lan")
        self.a.drain()
        self.assertFalse(self.answer("j5")["ok"])
        self.assertEqual(jobs, [("access", "lan")])

    def test_night_jobs_run_once_a_day_after_their_time_only_when_turned_on(self):
        import time as t
        ran = []
        self.a.run = lambda cmd, cwd=None, env=None, timeout=120: ran.append(cmd[4:]) or (0, "ok    Backup saved")
        at = lambda h, m: t.struct_time((2026, 11, 3, h, m, 0, 1, 307, 0))
        self.assertEqual(self.a.night_due(at(4, 0)), [])  # nothing turned on
        json.dump({"night": {"backup": True, "backup_at": "3:30 AM", "backup_keep": 3, "github": True, "github_repo": "", "github_at": "3:45 AM"}},
                  open(os.path.join(self.d, "settings.json"), "w"))
        self.assertEqual(self.a.night_due(at(3, 0)), [])  # too early
        due = self.a.night_due(at(3, 31))
        self.assertEqual(due, [("backup", ["backup", "--keep", "3"])])  # GitHub is on but has no repository, so it waits
        self.a.night_record("backup", t.mktime(at(3, 31)), True, "done")
        self.assertEqual(self.a.night_due(at(5, 0)), [])  # once a day
        self.assertEqual(agent.clock("6:05 pm"), (18, 5))
        self.assertIsNone(agent.clock("late"))

    def test_update_that_cannot_start_says_so(self):
        def boom():
            raise OSError("no space")
        self.a.spawn = boom
        self.drop("i1", "update")
        self.a.drain()
        self.assertIn("could not start the update", self.answer("i1")["msg"])

    def test_the_heartbeat_shows_whether_it_is_running(self):
        self.assertFalse(agent.alive(self.d, now=self.t[0]))  # nothing ever ran
        self.a.beat()
        self.assertTrue(agent.alive(self.d, now=self.t[0] + 30))
        self.assertFalse(agent.alive(self.d, now=self.t[0] + agent.FRESH + 5))  # it stopped
        open(os.path.join(self.d, agent.BEAT), "w").write("garbage")
        self.assertFalse(agent.alive(self.d, now=self.t[0]))

    def test_the_older_helper_without_a_heartbeat_still_counts(self):
        os.makedirs(os.path.join(self.d, "results"))
        self.assertTrue(agent.alive(self.d))

    def test_serve_keeps_going_after_an_error_and_stops_when_asked(self):
        ticks = []
        self.a.drain = lambda: ticks.append(1) or (_ for _ in ()).throw(RuntimeError("one bad moment"))
        self.a.serve(every=0, stop=lambda: len(ticks) >= 3, sleep=lambda s: None)
        self.assertEqual(len(ticks), 3)
        self.assertTrue(any("error: one bad moment" in l for l in self.lines))
        self.assertTrue(os.path.isdir(self.a.req) and os.path.isdir(self.a.res))

    def test_old_answers_are_cleaned_up(self):
        os.makedirs(self.a.res)
        old, new = os.path.join(self.a.res, "old.json"), os.path.join(self.a.res, "new.json")
        for p in (old, new):
            open(p, "w").write("{}")
        os.utime(old, (self.t[0] - agent.KEEP_RESULTS - 10,) * 2)
        os.utime(new, (self.t[0],) * 2)
        self.a.prune()
        self.assertEqual(os.listdir(self.a.res), ["new.json"])


class Installing(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp(prefix="hl-agent-inst-")
        self.addCleanup(shutil.rmtree, self.d, ignore_errors=True)
        self.calls, self.lines, self.rc = [], [], {}

    def fake_run(self, cmd, **kw):
        self.calls.append(" ".join(cmd))
        return self.rc.get(cmd[0] if cmd[0] != "systemctl" else " ".join(cmd[:3]), 0), self.rc.get("msg", "")

    def inst(self, platform, **kw):
        return agent.install("/opt/app", os.path.join(self.d, "hl"), platform, self.d, run=self.fake_run, python="/usr/bin/python3", out=self.lines.append, uid=501, **kw)

    def test_linux_writes_a_user_service_and_enables_it(self):
        self.assertTrue(self.inst("linux"))
        path = os.path.join(self.d, ".config", "systemd", "user", agent.UNIT)
        text = open(path).read()
        self.assertIn("ExecStart=/usr/bin/python3 -W ignore -m core.cli agent run", text)
        self.assertIn("Environment=PYTHONPATH=/opt/app", text)
        self.assertNotIn("HL_AGENT_REBOOT", text)
        self.assertNotIn("User=root", text)
        self.assertEqual(self.calls, ["systemctl --user daemon-reload", f"systemctl --user enable --now {agent.UNIT}"])
        self.assertIn("enable-linger", "\n".join(self.lines))

    def test_mac_writes_a_launch_agent_with_a_path_that_finds_docker(self):
        self.assertTrue(self.inst("mac", allow_reboot=True))
        text = open(os.path.join(self.d, "Library", "LaunchAgents", agent.LABEL + ".plist")).read()
        self.assertIn("<string>agent</string><string>run</string>", text)
        self.assertIn("/opt/homebrew/bin", text)
        self.assertIn(".orbstack/bin", text)
        self.assertIn("HL_AGENT_REBOOT", text)
        self.assertIn("<key>KeepAlive</key><true/>", text)
        self.assertEqual(self.calls, [f"launchctl bootout gui/501/{agent.LABEL}", f"launchctl bootstrap gui/501 {os.path.join(self.d, 'Library', 'LaunchAgents', agent.LABEL + '.plist')}"])

    def test_a_failure_names_the_command_and_keeps_the_file(self):
        self.rc = {"systemctl --user enable": 1, "msg": "Failed to connect to bus"}
        self.assertFalse(self.inst("linux"))
        out = "\n".join(self.lines)
        self.assertIn("Failed to connect to bus", out)
        self.assertIn("homelab agent install", out)

    def test_other_systems_say_so(self):
        self.assertFalse(self.inst("wsl"))
        self.assertIn("Linux (systemd) and macOS", "\n".join(self.lines))

    def test_uninstall_removes_the_file_and_is_safe_when_nothing_is_there(self):
        self.assertTrue(agent.uninstall("linux", self.d, run=self.fake_run, out=self.lines.append, uid=501))
        self.assertIn("was not installed", "\n".join(self.lines))
        self.inst("linux")
        self.calls.clear()
        self.assertTrue(agent.uninstall("linux", self.d, run=self.fake_run, out=self.lines.append, uid=501))
        self.assertFalse(os.path.exists(os.path.join(self.d, ".config", "systemd", "user", agent.UNIT)))
        self.assertIn(f"systemctl --user disable --now {agent.UNIT}", self.calls)

    def test_the_command_line_wires_it_up(self):
        out = []
        c = cli.Ctx("/opt/app", env={"HL_HOME": os.path.join(self.d, "hl")}, out=out.append, run=lambda cmd, **kw: (0, ""), user_home=self.d, platform="linux", python="/usr/bin/python3")
        self.assertEqual(cli.main(["agent", "status"], c), 1)
        self.assertIn("not running", "\n".join(out))
        self.assertEqual(cli.main(["agent", "install", "--allow-reboot"], c), 0)
        self.assertIn("HL_AGENT_REBOOT=1", open(os.path.join(self.d, ".config", "systemd", "user", agent.UNIT)).read())
        self.assertEqual(cli.main(["agent", "uninstall"], c), 0)


if __name__ == "__main__":
    unittest.main()
