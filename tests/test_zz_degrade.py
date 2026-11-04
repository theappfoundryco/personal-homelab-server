"""Every capability switched off in turn: no 500, no crash, no 'something went wrong', and the reply says what to fix.

The cases come from module.yaml: a module that lists a capability under optional: is exercised with that capability gone,
over every dashboard route and every phrase in phrases.py (plus the buttons that act on the server).
The file name sorts last on purpose: these runs write to the shared demo data the golden tests compare against.
"""
import unittest

import harness
from harness import call, load_bot, start_api
from phrases import PHRASES

CAPS = ("ollama", "internet", "calendar", "gmail", "telegram", "whisper", "docker_reader", "host_agent")
GET_ROUTES = ["/config", "/modules", "/capabilities", "/sg", "/sg/ai", "/gym", "/journal", "/journal/now", "/journal/weekly",
              "/journal/deep", "/journal/month?m=2026-10", "/runs", "/past", "/notes", "/brief", "/news", "/extras", "/settings"]
BUTTONS = ["restart!:n8n", "reboot!", "start!:n8n", "logs:n8n", "noop"]
BAD = "Something went wrong"
# what the scheduler calls on its own: none may raise (the loop would log a traceback every tick)
JOBS = ["fire_reminders", "check_journal", "check_server", "check_sg", "check_meds", "refresh_location", "write_extras", "warm_briefing", "check_f1",
        "check_flights", "ai_warm", "journal_morning_run", "insights_due", "recap_due"]


class Degrade(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.bot = load_bot()
        cls.srv, cls.base = start_api(cls.bot)

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()

    def off(self, names):
        """Force these capabilities down (the rest stay as the test machine has them: no network, no services)."""
        saved = {}
        for n in names:
            c = self.bot.CAPS.items[n]
            saved[n] = (c.check, c.ttl, c._val)
            c.check, c.ttl, c._val = (lambda: (False, "")), 0, None
        self.addCleanup(lambda: [setattr(self.bot.CAPS.items[n], a, v) for n, t in saved.items() for a, v in zip(("check", "ttl", "_val"), t)])
        bot = self.bot
        sent = []
        real = bot.TG._post
        bot.TG._post = lambda url, params, timeout: (sent.append((url.rsplit("/", 1)[1], params)) or {"result": {"message_id": len(sent)}})
        self.addCleanup(lambda: setattr(bot.TG, "_post", real))
        return sent

    def run_case(self, names):
        sent = self.off(names)
        bad = []
        for path in GET_ROUTES:
            code, body = call(self.base, "GET", path)
            if code >= 500:
                bad.append(f"GET {path} -> {code}")
        harness._net_calls.clear()
        for text, _ in PHRASES:
            sent.clear()
            self.bot.handle({"message": {"chat": {"id": 1, "type": "private"}, "text": text}})
            texts = " ".join(str(p.get("text", "")) for m, p in sent)
            if BAD in texts:
                bad.append(f"{text!r}: {texts[:120]}")
        for data in BUTTONS:
            sent.clear()
            self.bot.handle({"callback_query": {"id": "1", "from": {"id": 1}, "data": data, "message": {"message_id": 5, "chat": {"id": 1}}}})
            if BAD in " ".join(str(p.get("text", "")) for m, p in sent):
                bad.append(f"button {data}")
        for kind in ({"voice": {"file_id": "x"}}, {"photo": [{"file_id": "x"}]}):
            sent.clear()
            self.bot.handle({"message": {"chat": {"id": 1, "type": "private"}, **kind}})
            if BAD in " ".join(str(p.get("text", "")) for m, p in sent):
                bad.append(f"{list(kind)[0]} note")
        for name in JOBS:
            try:
                getattr(self.bot, name)()
            except Exception as e:
                bad.append(f"job {name}: {type(e).__name__}: {e}"[:160])
        for name, fn in (("scheduled_briefing", lambda: self.bot.scheduled_briefing(False)), ("evening", lambda: self.bot.evening(scheduled=True)),
                         ("weekly", self.bot.weekly), ("refresh_digests", lambda: self.bot.refresh_digests(wait=True))):
            try:
                fn()
            except Exception as e:
                bad.append(f"job {name}: {type(e).__name__}: {e}"[:160])
        harness._net_calls.clear()  # the golden no-network test counts calls made by routes, not by these probes
        self.assertEqual(bad, [], "\n" + "\n".join(bad[:30]))

    def test_each_capability_off(self):
        for n in CAPS:
            with self.subTest(capability=n):
                self.run_case([n])

    def test_everything_off(self):
        self.run_case(CAPS)


if __name__ == "__main__":
    unittest.main()
