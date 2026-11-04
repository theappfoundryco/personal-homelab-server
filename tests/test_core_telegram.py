import unittest

import harness  # noqa: F401
from core.telegram.client import Telegram, split


def fake():
    sent = []
    def post(url, params, timeout):
        sent.append((url.rsplit("/", 1)[1], params))
        return {"result": {"message_id": len(sent)}}
    return Telegram("T", 42, post, log=lambda m: None), sent


class TelegramTests(unittest.TestCase):
    def test_short_message_is_one_call(self):
        t, sent = fake()
        t.send("hi", buttons=[[{"text": "ok"}]], silent=True)
        self.assertEqual(len(sent), 1)
        m, p = sent[0]
        self.assertEqual((m, p["chat_id"], p["disable_notification"]), ("sendMessage", 42, True))
        self.assertIn("inline_keyboard", p["reply_markup"])

    def test_long_message_splits_and_buttons_go_last(self):
        t, sent = fake()
        t.send("\n".join(["x" * 100] * 120), buttons=[[{"text": "ok"}]])
        self.assertGreater(len(sent), 1)
        self.assertTrue(all(len(p["text"]) <= 4000 for _, p in sent))
        self.assertNotIn("reply_markup", sent[0][1])
        self.assertIn("reply_markup", sent[-1][1])

    def test_giant_line_is_cut_as_plain_text(self):
        parts = split("<b>" + "y" * 9000 + "</b>")
        self.assertTrue(all(len(p) <= 4000 for p in parts))
        self.assertEqual(split(""), [""])

    def test_failures_return_none(self):
        logs = []
        def boom(*a): raise OSError("offline")
        t = Telegram("T", 1, boom, log=logs.append)
        self.assertIsNone(t.send("hi"))
        self.assertIn("offline", logs[0])

    def test_owner_check(self):
        t, sent = fake()
        self.assertTrue(t.is_owner({"message": {"chat": {"id": 42}}}))
        self.assertTrue(t.is_owner({"callback_query": {"from": {"id": 42}}}))
        self.assertFalse(t.is_owner({"callback_query": {"from": {"id": 7}}}))
        self.assertEqual(sent, [])
        self.assertFalse(t.is_owner({"message": {"chat": {"id": 7, "type": "private"}}}))
        self.assertIn("private assistant", sent[0][1]["text"])
        sent.clear()
        self.assertFalse(t.is_owner({"message": {"chat": {"id": -5, "type": "group"}}}))
        self.assertEqual(sent, [])

    def test_edit_without_a_message_sends(self):
        t, sent = fake()
        t.edit(None, "new")
        self.assertEqual(sent[0][0], "sendMessage")
        t.edit({"message_id": 9}, "changed")
        self.assertEqual(sent[1][0], "editMessageText")

    def test_without_token_nothing_is_sent_and_it_says_so_once(self):
        sent, logs = [], []
        t = Telegram("", 0, lambda *a: sent.append(a), log=logs.append)
        self.assertFalse(t.enabled)
        self.assertIsNone(t.send("hi"))
        self.assertIsNone(t.edit(None, "hi"))
        t.typing()
        self.assertEqual(sent, [])
        self.assertEqual(len(logs), 1)
        self.assertIn("not set up", logs[0])

    def test_app_boots_without_telegram(self):
        """No TG_TOKEN or TG_CHAT: importing the app works, chat is off and the capability explains why."""
        import os
        import subprocess
        import sys
        env = {k: v for k, v in os.environ.items() if k not in ("TG_TOKEN", "TG_CHAT")}
        env.update(HL_DATA=harness.tempfile.mkdtemp(), HL_CONFIG=os.path.join(harness.ROOT, "tests", "config.test.yaml"), PYTHONPATH=harness.ROOT)
        code = "from core import boot; print(boot.TG.enabled, boot.CAPS.items['telegram'].status()['message'])"
        r = subprocess.run([sys.executable, "-W", "ignore", "-c", code], env=env, cwd=harness.ROOT, capture_output=True, text=True, timeout=60)
        self.assertEqual(r.returncode, 0, r.stderr[-800:])
        self.assertIn("False Telegram is not connected", r.stdout)


if __name__ == "__main__":
    unittest.main()
