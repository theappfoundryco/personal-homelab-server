"""News setup: your topics, your feeds, your own AI key and model, and headlines without any AI (network blocked)."""
import os, shutil, tempfile, time, unittest
from urllib.error import HTTPError

import harness
from harness import load_bot


class NewsSetup(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.bot = load_bot()

    def patch(self, mod, **attrs):
        for k, v in attrs.items():
            self.addCleanup(setattr, mod, k, getattr(mod, k))
            setattr(mod, k, v)

    def setUp(self):
        import modules.news as m
        self.m = m
        self.d = tempfile.mkdtemp(prefix="hl-news-")
        self.addCleanup(shutil.rmtree, self.d, ignore_errors=True)
        self.patch(m, DATA=self.d)
        self.addCleanup(self.bot.SETTINGS.reset)
        self.base = harness.start_api(self.bot)[1]

    def test_keys_are_checked_kept_private_and_never_sent_back(self):
        from core import ai_keys

        def fetch(url, headers, timeout=10):
            if headers.get("x-api-key") != "sk-good":
                raise HTTPError(url, 401, "no", {}, None)
            return {"data": [{"id": "claude-sonnet-5-5"}, {"id": "claude-haiku-5-5"}]}
        real = ai_keys.models
        self.patch(ai_keys, models=lambda p, k, fetch=fetch: real(p, k, fetch))
        code, out = harness.call(self.base, "POST", "/news/key", {"provider": "claude", "key": "sk-bad"})
        self.assertEqual(code, 400)
        self.assertIn("not accepted", out["error"])
        code, out = harness.call(self.base, "POST", "/news/key", {"provider": "claude", "key": "sk-good"})
        self.assertEqual((code, out["suggested"]), (200, "claude-haiku-5-5"))
        p = ai_keys.path(self.d, "claude")
        self.assertEqual(oct(os.stat(p).st_mode & 0o777), "0o600")
        code, out = harness.call(self.base, "GET", "/news/setup")
        self.assertEqual(out["keys"]["claude"], True)
        self.assertNotIn("sk-good", str(out))
        self.assertEqual(out["using"]["provider"], "claude")

    def test_choices_are_saved_and_wrong_ones_refused(self):
        code, out = harness.call(self.base, "POST", "/news/setup", {"topics": ["world", "science"], "ai": "none", "briefing": "6:45 AM",
                                                                     "feeds": [{"url": "https://example.com/feed.xml", "topic": "Cycling"}]})
        self.assertEqual(code, 200, out)
        n = self.bot.SETTINGS.merged()["news"]
        self.assertEqual((n["topics"], n["ai"], n["feeds"][0]["topic"]), (["world", "science"], "none", "Cycling"))
        self.assertEqual(self.bot.SETTINGS.merged()["schedule"]["briefing"], "6:45 AM")
        self.assertEqual(harness.call(self.base, "POST", "/news/setup", {"ai": "skynet"})[0], 400)
        self.assertEqual(harness.call(self.base, "POST", "/news/setup", {"briefing": "late"})[0], 400)
        self.assertEqual(harness.call(self.base, "POST", "/news/feed/check", {"url": "ftp://x"})[0], 400)

    def test_without_any_ai_the_digest_is_the_headlines_not_a_promise(self):
        self.patch(self.m, news_ai=lambda: (None, ""), headlines_for=lambda t, n=7: [{"link": f"https://x/{k}", "title": f"Story {k}", "ts": time.time()} for k in range(1, 8)],
                   DIGEST_FILE=os.path.join(self.d, "d.json"))
        self.m.make_digest("world", 3)
        d = self.m.digests["world"]
        self.assertEqual([b for b, _ in d["bullets"]], ["Story 1.", "Story 2.", "Story 3."])
        self.assertTrue(d["plain"])


if __name__ == "__main__":
    unittest.main()
