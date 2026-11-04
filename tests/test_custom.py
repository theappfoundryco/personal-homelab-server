"""Apps you add yourself: what is accepted, the compose file written for it, and the command line, host helper and uninstall around it."""
import json
import os
import re
import shutil
import tempfile
import unittest
from unittest import mock

import harness  # noqa: F401  (puts core on the path)
from core import agent, cli, custom
from test_agent import Docker, Proc
from test_cli import Base

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
GOOD = {"title": "Media server", "image": "jellyfin/jellyfin:10.10.7", "port": "8096", "keep": "/config"}


class Checks(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp(prefix="hl-custom-")
        self.addCleanup(shutil.rmtree, self.d, ignore_errors=True)

    def test_a_good_app_is_cleaned_up_and_saved(self):
        app, why = custom.check(self.d, GOOD)
        self.assertIsNone(why)
        self.assertEqual(app, {"id": "media-server", "title": "Media server", "image": "jellyfin/jellyfin:10.10.7", "port": 8096, "inside": 8096,
                               "keep": "/config", "group": "apps"})
        custom.add(self.d, app)
        self.assertEqual(custom.ids(self.d), ["media-server"])
        self.assertIn("is taken", custom.check(self.d, GOOD)[1])
        self.assertIn("already used", custom.check(self.d, {**GOOD, "title": "Other"})[1])

    def test_images_must_be_pinned(self):
        for ok in ("jellyfin/jellyfin:10.10.7", "ghcr.io/owner/app:v1.2", "registry.example.test:5000/team/app:2", "nginx@sha256:" + "a" * 64):
            self.assertTrue(custom.pinned(ok), ok)
        for bad in ("jellyfin/jellyfin", "jellyfin/jellyfin:latest", "nginx:LATEST", "Bad/Name:1", "x:1 --privileged", "a:b/c", "", "nginx@sha256:short"):
            self.assertFalse(custom.pinned(bad), bad)

    def test_what_is_refused_and_why(self):
        cases = [({**GOOD, "title": ""}, "name"), ({**GOOD, "title": "Ollama"}, "taken"), ({**GOOD, "title": "landing"}, "taken"),
                 ({**GOOD, "image": "jellyfin/jellyfin"}, "Pin"), ({**GOOD, "image": ""}, "image"), ({**GOOD, "port": "80"}, "1024"),
                 ({**GOOD, "port": "3000"}, "already used"), ({**GOOD, "port": "abc"}, "number"), ({**GOOD, "inside": "99999"}, "inside"),
                 ({**GOOD, "keep": "/../etc"}, "folder"), ({**GOOD, "keep": "config"}, "folder"), ({**GOOD, "keep": "/"}, "folder"),
                 ({**GOOD, "group": "x"}, "Tools")]
        for spec, word in cases:
            self.assertIn(word, custom.check(self.d, spec)[1] or "", spec)
        self.assertIn("already used", custom.check(self.d, GOOD, taken={8096})[1])
        self.assertIn("already exists", custom.check(self.d, GOOD, containers={"media-server"})[1])

    def test_the_compose_file_is_its_own_project_with_no_extra_powers(self):
        app = custom.check(self.d, {**GOOD, "inside": "8920"})[0]
        text = custom.compose_text(app)
        self.assertIn('name: "homelab-custom-media-server"', text)
        self.assertIn('ports: ["${HL_BIND:-127.0.0.1}:8096:8920"]', text)
        self.assertIn('volumes: ["homelab-custom-media-server:/config"]', text)
        self.assertIn('"homelab.custom": "media-server"', text)
        for word in ("privileged", "docker.sock", "network_mode", "cap_add", "devices"):
            self.assertNotIn(word, text)
        self.assertNotIn("volumes", custom.compose_text({**app, "keep": ""}))

    def test_builtin_ports_cover_every_port_compose_publishes(self):
        text = open(os.path.join(ROOT, "stack", "compose.yaml")).read()
        published = {int(m) for m in re.findall(r'"[^"\n]*?:(\d+):\d+"', text)}
        self.assertTrue(published)
        self.assertLessEqual(published, set(custom.BUILTIN_PORTS))

    def test_a_broken_or_tampered_file_reads_as_nothing_bad(self):
        os.makedirs(self.d, exist_ok=True)
        open(custom.path(self.d), "w").write(json.dumps({"apps": [{"id": "ollama"}, {"id": "../x"}, "junk", {"id": "fine-app", "port": 9000}]}))
        self.assertEqual(custom.ids(self.d), ["fine-app"])
        open(custom.path(self.d), "w").write("{")
        self.assertEqual(custom.ids(self.d), [])


class CommandLine(Base):
    def go(self, *argv):
        self.lines.clear()
        return cli.main(list(argv), self.ctx)

    def test_add_list_and_remove_your_own_app(self):
        with mock.patch.object(cli, "_port_free", lambda p: True):
            self.assertEqual(self.go("apps", "custom", "add", "Media server", "jellyfin/jellyfin:10.10.7", "8096", "--keep", "/config", "--tools"), 0)
        f = custom.compose_path(self.data, "media-server")
        self.assertTrue(os.path.exists(f))
        env = os.path.join(self.app, "stack", ".env")
        self.assertEqual(self.fake.calls, [f"compose -p homelab-custom-media-server -f {f} --env-file {env} up -d"])
        self.assertIn("Media server started on port 8096", self.say())
        self.assertEqual(custom.get(self.data, "media-server")["group"], "tools")
        self.go("apps")
        self.assertIn("media-server", self.say())
        self.fake.calls.clear()
        self.go("start")
        self.assertNotIn("media-server", " ".join(self.fake.calls))  # the main stack never touches it
        self.fake.calls.clear()
        self.assertEqual(self.go("apps", "remove", "media-server"), 0)
        self.assertEqual(self.fake.calls[0], f"compose -p homelab-custom-media-server -f {f} --env-file {env} down")
        self.assertEqual(custom.ids(self.data), [])
        self.assertFalse(os.path.exists(f))

    def test_refusals_say_why_and_start_nothing(self):
        self.assertEqual(self.go("apps", "custom", "add", "Media", "jellyfin/jellyfin:latest", "8096"), 2)
        self.assertIn("Pin the image", self.say())
        with mock.patch.object(cli, "_port_free", lambda p: False):
            self.assertEqual(self.go("apps", "custom", "add", "Media", "jellyfin/jellyfin:10.10.7", "8096"), 2)
        self.assertIn("already used", self.say())
        self.assertEqual(self.go("apps", "custom", "add", "Media"), 2)
        self.assertEqual(self.fake.calls, [])
        self.assertEqual(custom.ids(self.data), [])

    def test_uninstall_lists_and_takes_down_your_apps(self):
        custom.add(self.data, custom.check(self.data, GOOD)[0])
        custom.write(self.data, custom.get(self.data, "media-server"))
        self.fake.answers = ["y"]
        self.assertEqual(self.go("uninstall"), 0)
        self.assertIn("Your own apps: media-server (their data is kept)", self.say())
        self.assertTrue(any(c.startswith("compose -p homelab-custom-media-server") and c.endswith(" down") for c in self.fake.calls))
        self.assertEqual(custom.ids(self.data), ["media-server"])


class Helper(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp(prefix="hl-agent-")
        self.addCleanup(shutil.rmtree, self.d, ignore_errors=True)

    def test_the_helper_adds_and_restarts_your_apps_but_nothing_unknown(self):
        jobs = []
        a = agent.Agent(self.d, "/opt/app", run=Docker(names=("media-server",)), spawn_apps=lambda act, app: jobs.append((act, app)) or Proc(False), log=lambda m: None)
        self.assertFalse(a.handle("add media-server")[0])
        custom.add(self.d, custom.check(self.d, GOOD)[0])
        self.assertTrue(a.handle("add media-server")[0])
        self.assertEqual(jobs, [("add", "media-server")])
        self.assertTrue(a.handle("restart media-server")[0])
        self.assertIn("label=homelab.custom", " ".join(" ".join(c) for c in a.run.calls))


if __name__ == "__main__":
    unittest.main()
