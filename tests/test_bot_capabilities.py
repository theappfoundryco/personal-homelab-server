import unittest

import harness
from harness import call, load_bot, start_api


class BotCaps(unittest.TestCase):
    def test_capabilities_route(self):
        bot = load_bot()
        srv, base = start_api(bot)
        code, body = call(base, "GET", "/capabilities")
        harness._net_calls.clear()  # the checks try the network; the golden test asserts routes do not
        srv.shutdown()
        self.assertEqual(code, 200)
        names = {c["name"]: c for c in body["capabilities"]}
        self.assertEqual(set(names), {"ollama", "internet", "calendar", "gmail", "telegram", "whisper", "docker_reader", "host_agent", "push", "offsite", "homeassistant"})
        self.assertFalse(names["ollama"]["ok"])
        self.assertIn("Ollama", names["ollama"]["message"])

    def test_an_unreachable_ollama_on_this_machine_says_how_to_let_docker_in(self):
        bot = load_bot()
        old = bot.OLLAMA
        self.addCleanup(setattr, bot, "OLLAMA", old)
        bot.OLLAMA = "http://host.docker.internal:11434"
        ok, why = bot._ollama_check()
        harness._net_calls.clear()
        self.assertFalse(ok)
        self.assertIn("OLLAMA_HOST=0.0.0.0", why)
        bot.OLLAMA = "http://ollama:11434"  # the one in Docker: the hint would only confuse
        self.assertNotIn("OLLAMA_HOST", bot._ollama_check()[1])
        harness._net_calls.clear()

    def test_optional_names_are_known(self):
        """A module's optional: list may only name a capability or another module, so every entry gets a degrade test."""
        import glob
        import os
        import yaml
        root = os.path.join(harness.ROOT, "modules")
        mods = {os.path.basename(os.path.dirname(f)) for f in glob.glob(f"{root}/*/module.yaml")}
        caps = {"ollama", "internet", "calendar", "gmail", "telegram", "whisper", "docker_reader", "host_agent"}
        for f in glob.glob(f"{root}/*/module.yaml"):
            for n in yaml.safe_load(open(f)).get("optional") or []:
                self.assertIn(n, caps | mods, f"{f}: optional '{n}' is not a capability or a module")


if __name__ == "__main__":
    unittest.main()
