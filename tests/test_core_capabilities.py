import unittest

import harness  # noqa: F401
from core.capabilities import Capabilities


class CapTests(unittest.TestCase):
    def setUp(self):
        self.c = Capabilities()
        self.up = {"ollama": True}
        self.c.register("ollama", "Ollama", lambda: self.up["ollama"], "Start Ollama.", ttl=0)
        self.c.register("calendar", "Calendar", lambda: (False, "No calendar link."), "Add it in the setup wizard.", ttl=0)
        self.c.register("odd", "Odd", lambda: 1 / 0, "Fix it.", ttl=0)

    def test_report(self):
        r = {x["name"]: x for x in self.c.all()}
        self.assertTrue(r["ollama"]["ok"])
        self.assertEqual(r["calendar"]["message"], "No calendar link. Add it in the setup wizard.")
        self.assertFalse(r["odd"]["ok"])  # a crashing check is just "not available"

    def test_degrade_runs_or_explains(self):
        self.assertEqual(self.c.degrade("ollama", lambda: "answer"), "answer")
        self.up["ollama"] = False
        self.assertEqual(self.c.degrade("ollama", lambda: "answer"), "Start Ollama.")
        self.assertEqual(self.c.degrade(["ollama", "calendar"], lambda: 1, fallback="skip"), "skip")

    def test_unknown_capability_is_missing_not_a_crash(self):
        self.assertFalse(self.c.ok("ghost"))
        self.assertIn("ghost", self.c.degrade("ghost", lambda: 1))

    def test_result_is_cached(self):
        calls = []
        self.c.register("slow", "Slow", lambda: calls.append(1) or True, "x", ttl=60)
        self.c.ok("slow"); self.c.ok("slow")
        self.assertEqual(len(calls), 1)

    def test_a_job_skips_once_per_outage(self):
        state, said = {"up": False}, []
        caps = Capabilities()
        caps.register("ollama", "AI", lambda: state["up"], "Start Ollama.", ttl=0)
        self.assertTrue(caps.skip("Summaries", "ollama", said.append))
        self.assertTrue(caps.skip("Summaries", "ollama", said.append))
        self.assertEqual(len(said), 1)
        self.assertIn("Start Ollama", said[0])
        state["up"] = True
        self.assertFalse(caps.skip("Summaries", "ollama", said.append))
        state["up"] = False
        self.assertTrue(caps.skip("Summaries", "ollama", said.append))
        self.assertEqual(len(said), 2)


if __name__ == "__main__":
    unittest.main()
