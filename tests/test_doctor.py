import os
import subprocess
import sys
import unittest

import harness
from core import capabilities, doctor, registry


def mod(name, optional=(), platforms=("linux", "mac", "wsl")):
    m = registry.Module.__new__(registry.Module)
    m.name, m.title, m.optional, m.platforms = name, name.title(), list(optional), list(platforms)
    return m


class DoctorTests(unittest.TestCase):
    def setUp(self):
        self.caps = capabilities.Capabilities()
        self.caps.register("ollama", "AI", lambda: False, "Start Ollama.", ttl=0)
        self.caps.register("internet", "Internet", lambda: True, "Check the connection.", ttl=0)
        self.mods = {"gym": mod("gym"), "journal": mod("journal", ["ollama", "internet"]), "netfallback": mod("netfallback", platforms=("linux",)),
                     "broken": mod("broken"), "quiet": mod("quiet"), "_template": mod("_template")}

    def rep(self, platform="mac", config=None):
        return doctor.report(self.caps, self.mods, ["gym", "journal", "broken"], ["gym", "journal"], {"quiet": "Quiet is switched off in config.yaml."}, config, platform)

    def test_every_state(self):
        by = {m["name"]: m for m in self.rep()["modules"]}
        self.assertEqual({k: v["state"] for k, v in by.items()},
                         {"gym": "on", "journal": "degraded", "netfallback": "hidden", "broken": "failed", "quiet": "off"})
        self.assertNotIn("_template", by)
        self.assertEqual([d["capability"] for d in by["journal"]["degraded"]], ["ollama"])
        self.assertIn("needs linux", by["netfallback"]["why"])
        self.assertIn("this machine is mac", by["netfallback"]["why"])

    def test_a_linux_only_module_is_not_hidden_on_linux(self):
        self.assertEqual({m["name"]: m["state"] for m in self.rep("linux")["modules"]}["netfallback"], "off")  # not switched on, but not a platform problem

    def test_ok_means_nothing_broken_not_nothing_limited(self):
        self.assertFalse(self.rep()["ok"])  # one module failed to start
        self.mods.pop("broken")
        self.assertTrue(doctor.report(self.caps, self.mods, ["gym", "journal"], ["gym", "journal"], {}, None, "mac")["ok"])
        self.assertFalse(doctor.report(self.caps, self.mods, ["gym"], ["gym"], {}, type("C", (), {"problems": ["owner.name is odd"]}), "mac")["ok"])

    def test_text_names_the_fix(self):
        text = doctor.render(self.rep())
        self.assertIn("AI: ", text)
        self.assertIn("Fix: Start Ollama.", text)
        self.assertIn("limited without AI", text)
        self.assertIn("FAIL  Broken", text)
        self.assertNotIn("—", text)

    def test_route_and_command_line(self):
        bot = harness.load_bot()
        base = harness.start_api(bot)[1]
        code, out = harness.call(base, "GET", "/doctor")
        harness._net_calls.clear()
        self.assertEqual(code, 200)
        self.assertTrue(out["ok"])
        self.assertTrue({"ollama", "telegram"} <= {c["name"] for c in out["capabilities"]})
        env = {**os.environ, "HL_DATA": harness.tempfile.mkdtemp(), "HL_CONFIG": os.path.join(harness.ROOT, "tests", "config.test.yaml"), "TG_TOKEN": "", "TG_CHAT": "", "PYTHONPATH": harness.ROOT}
        r = subprocess.run([sys.executable, "-W", "ignore", "-m", "core", "doctor"], env=env, cwd=harness.ROOT, capture_output=True, text=True, timeout=90)
        self.assertEqual(r.returncode, 0, r.stderr[-600:])
        self.assertIn("Health check", r.stdout)
        self.assertIn("Telegram", r.stdout)
        self.assertIn("Fix:", r.stdout)
        self.assertIn("Your machine:", r.stdout)
        code, hw = harness.call(base, "GET", "/hardware")
        harness._net_calls.clear()
        self.assertEqual(code, 200)
        self.assertIn(hw["recommendation"]["profile"], ("tiny", "small", "medium", "large"))
        self.assertIn("os", hw["hardware"])
        r = subprocess.run([sys.executable, "-W", "ignore", "-m", "core", "hardware"], env={**os.environ, "PYTHONPATH": harness.ROOT, "HL_DATA": "/nonexistent/data"},
                           cwd=harness.ROOT, capture_output=True, text=True, timeout=60)  # needs no config and no data folder
        self.assertEqual(r.returncode, 0, r.stderr[-600:])
        self.assertIn("This machine:", r.stdout)
        self.assertIn("Profile:", r.stdout)

    def test_the_machine_line_only_shows_when_known(self):
        self.assertNotIn("Your machine", doctor.render(self.rep()))
        rep = {**self.rep(), "machine": {"summary": "16 GB memory", "recommendation": {"title": "Everyday machine"}}}
        self.assertIn("Your machine: 16 GB memory (Everyday machine profile)", doctor.render(rep))


if __name__ == "__main__":
    unittest.main()
