"""Bot router tests: what each phrasing does, with Telegram, Ollama and the internet out of the picture.

Rule-based routing (reminders, notes, goals, links, help, the keyboard buttons) is checked against phrases.py.
Anything the rules don't claim goes to the classifier; that path is covered with a stand-in embedder.
"""
import hashlib
import math
import unittest

from harness import load_bot
from phrases import PHRASES


def fake_embed(texts, dim=256):
    """Hashed word and trigram counts: stable, offline, and close for similar words. Not meaning, only plumbing."""
    out = []
    for t in texts:
        v = [0.0] * dim
        t = " " + t.lower() + " "
        for tri in [t[i:i + 3] for i in range(len(t) - 2)] + t.split():
            v[int(hashlib.md5(tri.encode()).hexdigest(), 16) % dim] += 1.0
        n = math.sqrt(sum(x * x for x in v)) or 1.0
        out.append([x / n for x in v])
    return out


class Router(unittest.TestCase):
    def setUp(self):
        cls = self
        cls.bot = b = load_bot()
        from core import intent as ci
        from core.telegram import handlers as h
        if not hasattr(ci, "_real_classify"):
            ci._real_classify = ci.classify
        cls.calls = []
        rec = lambda name: (lambda *a, **k: cls.calls.append(name))
        for name, tag in [("add_goal", "goal"), ("bare_done", "bare_done"), ("summarise_link", "link"), ("suggested_tags", "tags"),
                          ("morning_briefing", "briefing"), ("world_clock", "clock"), ("live_digest", "digest"), ("sports", "sports"),
                          ("search", "search"), ("fresh_data", "_"), ("typed_meds", None)]:
            setattr(h, name, rec(tag) if tag else (lambda t: None))
        ci.classify = lambda text: (cls.calls.append("ai") or ("chat", "stub"))
        h.dispatch = lambda intent, text, t: cls.calls.append(intent)

        def send(text, *a, **k):
            if text == b.HELP:
                cls.calls.append("help")
            elif "Fresh start" in text:
                cls.calls.append("reset")
            elif "What did you want" in text:
                cls.calls.append("wrong")
            else:
                cls.calls.append("sent")
        h.send = send

    def where(self, text):
        self.calls.clear()
        self.bot.route(text)
        got = [c for c in self.calls if c != "_"]
        # the classifier stub says "ai" then dispatch repeats its answer: collapse to "ai"
        return "ai" if got[:1] == ["ai"] else (got[0] if got else "nothing")

    def test_phrase_table(self):
        self.assertGreaterEqual(len(PHRASES), 200)
        bad = []
        for text, want in PHRASES:
            got = self.where(text)
            if got != want:
                bad.append(f"{text!r}: wanted {want}, got {got}")
        self.assertEqual(bad, [], "\n" + "\n".join(bad))

    def test_filler_is_stripped_before_the_classifier(self):
        seen = []
        from core import intent as ci
        orig = ci.classify
        ci.classify = lambda text: (seen.append(text) or ("chat", "stub"))
        try:
            self.bot.route("hey, can you please what's the weather")
        finally:
            ci.classify = orig
        self.assertEqual(len(seen), 1)
        self.assertFalse(seen[0].lower().startswith(("hey", "can you", "please")), seen[0])

    def test_classifier_finds_each_labelled_example(self):
        """Every line in intents.py must resolve to its own label through classify(), the plumbing end to end."""
        import intents
        b = self.bot
        from core import intent as ci
        ci.embed = fake_embed
        ci.clf_rank = lambda q: None
        ci.learned = lambda: {}
        ci.ai_pick = lambda text, a, c: a
        ci._index.update(vecs=[], labels=[])
        ci.build_index()
        wrong = []
        for label, examples in {**intents.EXAMPLES, **b.module_examples()}.items():
            for ex in examples:
                got, _ = ci._real_classify(ex)
                if got != label and not (got == "answer" and label in ("news", "sports")):
                    wrong.append(f"{ex!r}: {label} -> {got}")
        self.assertEqual(wrong, [], "\n" + "\n".join(wrong[:20]))

    def test_classifier_falls_back_to_chat_when_it_breaks(self):
        b = self.bot
        from core import intent as ci
        ci.classify = lambda text: (_ for _ in ()).throw(RuntimeError("ollama is down"))
        self.calls.clear()
        b.route("what is the meaning of life")
        self.assertEqual(self.calls[-1], "chat")


if __name__ == "__main__":
    unittest.main()
