import unittest

import harness  # noqa: F401
from core import config, notify
from core.notify import Notifier


def fake(conf=None, telegram_ready=True, fail=(), token=""):
    """A Notifier whose sends are recorded instead of made. fail: channel urls that raise."""
    posts, chats, logs = [], [], []

    def post(url, payload, headers, timeout):
        if any(url.startswith(f) for f in fail):
            raise OSError("connection refused")
        posts.append((url, payload, headers))

    def telegram(text, buttons, keyboard, silent):
        chats.append((text, buttons, silent))

    n = Notifier(conf, telegram, lambda: telegram_ready, token, post, logs.append)
    return n, posts, chats, logs


class Addresses(unittest.TestCase):
    def test_topic_address_splits_into_server_and_topic(self):
        self.assertEqual(notify.ntfy_parts("https://ntfy.sh/alex-alerts"), ("https://ntfy.sh", "alex-alerts"))
        self.assertEqual(notify.ntfy_parts("http://10.0.0.5:8090/ntfy/alex_alerts/"), ("http://10.0.0.5:8090/ntfy", "alex_alerts"))

    def test_addresses_that_are_not_a_topic_are_refused(self):
        for bad in ("", "ntfy.sh/alex", "https://ntfy.sh/", "https://ntfy.sh/a b", "ftp://ntfy.sh/alex", "https://ntfy.sh/alex?auth=x"):
            self.assertIsNone(notify.ntfy_parts(bad), bad)

    def test_problems_are_plain_sentences(self):
        self.assertEqual(notify.problems({}), [])
        self.assertEqual(notify.problems({"ntfy": "https://ntfy.sh/alex-alerts", "apprise": "http://apprise:8000/notify/homelab"}), [])
        self.assertIn("topic address", notify.problems({"ntfy": "alex-alerts"})[0])
        self.assertIn("Apprise API address", notify.problems({"apprise": "apprise:8000"})[0])
        self.assertIn("go nowhere", notify.problems({"telegram": False})[0])

    def test_config_knows_the_section(self):
        self.assertEqual(config.check({"notify": {"telegram": True, "ntfy": "https://ntfy.sh/alex-alerts", "apprise": ""}}), [])
        self.assertTrue(config.check({"notify": {"ntfy_topic": "x"}}))  # a typo is reported


class Sending(unittest.TestCase):
    def test_without_notify_settings_only_telegram_gets_it(self):
        n, posts, chats, _ = fake()
        self.assertEqual(n.send("⏰ <b>Reminder</b>\nCall Sam", silent=True), {"telegram": True})
        self.assertEqual(chats, [("⏰ <b>Reminder</b>\nCall Sam", None, True)])
        self.assertEqual(posts, [])
        self.assertEqual(n.extra(), [])

    def test_telegram_that_is_not_set_up_is_skipped(self):
        n, _, chats, _ = fake({"ntfy": "https://ntfy.sh/alex-alerts"}, telegram_ready=False)
        self.assertEqual(n.send("hi"), {"ntfy": True})
        self.assertEqual(chats, [])

    def test_telegram_can_be_turned_off_for_alerts(self):
        n, _, chats, _ = fake({"telegram": False, "ntfy": "https://ntfy.sh/alex-alerts"})
        self.assertEqual(set(n.send("hi")), {"ntfy"})
        self.assertEqual(chats, [])

    def test_ntfy_gets_plain_text_a_title_and_the_link_buttons(self):
        n, posts, _, _ = fake({"ntfy": "https://ntfy.sh/alex-alerts"})
        buttons = [[{"text": "Live score", "url": "https://example.com/score"}, {"text": "✅ Done", "callback_data": "remdone:1"}]]
        n.send("🏏 <b>Testville match is on</b>\nTestville 120/3 &amp; rising", buttons, silent=True)
        url, msg, headers = posts[0]
        self.assertEqual(url, "https://ntfy.sh/")
        self.assertEqual(msg["topic"], "alex-alerts")
        self.assertEqual(msg["title"], "🏏 Testville match is on")
        self.assertEqual(msg["message"], "Testville 120/3 & rising")
        self.assertEqual(msg["priority"], 2)  # a quiet message stays quiet
        self.assertEqual(msg["click"], "https://example.com/score")
        self.assertEqual(msg["actions"], [{"action": "view", "label": "Live score", "url": "https://example.com/score"}])  # bot-only buttons left out
        self.assertEqual(headers, {})

    def test_one_line_has_no_title(self):
        n, posts, _, _ = fake({"ntfy": "https://ntfy.sh/alex-alerts"})
        n.send("💾 Storage is 90% full. Time to clean up.")
        msg = posts[0][1]
        self.assertNotIn("title", msg)
        self.assertEqual((msg["message"], msg["priority"]), ("💾 Storage is 90% full. Time to clean up.", 3))

    def test_private_ntfy_server_gets_the_token(self):
        n, posts, _, _ = fake({"ntfy": "https://ntfy.example.com/alex-alerts"}, token="tk_fake")
        n.send("hi")
        self.assertEqual(posts[0][2], {"Authorization": "Bearer tk_fake"})

    def test_apprise_gets_title_body_and_links(self):
        n, posts, _, _ = fake({"apprise": "http://apprise:8000/notify/homelab"})
        n.send("⏰ <b>Reminder</b>\nCall Sam", [[{"text": "Open", "url": "https://example.com"}]])
        url, msg, _ = posts[0]
        self.assertEqual(url, "http://apprise:8000/notify/homelab")
        self.assertEqual(msg, {"title": "⏰ Reminder", "body": "Call Sam\n\nOpen: https://example.com", "type": "info", "format": "text"})

    def test_a_broken_channel_never_stops_the_others(self):
        n, posts, chats, logs = fake({"ntfy": "https://ntfy.sh/alex-alerts", "apprise": "http://apprise:8000/notify/homelab"},
                                     fail=("https://ntfy.sh",), token="tk_fake")
        self.assertEqual(n.send("hi"), {"telegram": True, "ntfy": False, "apprise": True})
        self.assertEqual(len(chats), 1)
        self.assertEqual([p[0] for p in posts], ["http://apprise:8000/notify/homelab"])
        self.assertEqual(logs, ["notify ntfy: connection refused"])  # no address, no token
        ok, why = n.status()
        self.assertFalse(ok)
        self.assertIn("ntfy did not go through", why)

    def test_errors_are_said_plainly(self):
        n, _, _, logs = fake({"ntfy": "https://ntfy.sh/alex-alerts"})
        n.post = lambda *a: (_ for _ in ()).throw(OSError(-2, "Name or service not known"))
        n.send("hi")
        self.assertEqual(logs, ["notify ntfy: Name or service not known"])

    def test_status_recovers_after_a_good_send(self):
        n, _, _, _ = fake({"ntfy": "https://ntfy.sh/alex-alerts"})
        n.last["ntfy"] = "connection refused"
        n.send("hi")
        self.assertEqual(n.status(), (True, ""))

    def test_a_bad_address_is_not_used(self):
        n, posts, _, _ = fake({"ntfy": "alex-alerts", "apprise": "apprise:8000"})
        self.assertEqual(n.extra(), [])
        n.send("hi")
        self.assertEqual(posts, [])

    def test_long_messages_are_cut_for_ntfy(self):
        n, posts, _, _ = fake({"ntfy": "https://ntfy.sh/alex-alerts"})
        n.send("x" * 9000)
        self.assertEqual(len(posts[0][1]["message"]), notify.LIMIT)


if __name__ == "__main__":
    unittest.main()
