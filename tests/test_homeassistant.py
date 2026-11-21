"""Home Assistant: quiet until connected, plain sentences to the right device, a Yes or No before every change, no unlocking unless allowed,
and the module hooks in the bot and the brief. Home Assistant is a small pretend server on this machine that checks the token."""
import json
import threading
import types
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import harness
from core import app as core_app
from core import capabilities

STATES = [
    {"entity_id": "light.kitchen_ceiling", "state": "on", "attributes": {"friendly_name": "Kitchen ceiling light"}},
    {"entity_id": "light.kitchen_counter", "state": "off", "attributes": {"friendly_name": "Kitchen counter light"}},
    {"entity_id": "light.bedroom", "state": "off", "attributes": {"friendly_name": "Bedroom lamp"}},
    {"entity_id": "switch.coffee", "state": "off", "attributes": {"friendly_name": "Coffee machine"}},
    {"entity_id": "lock.front_door", "state": "locked", "attributes": {"friendly_name": "Front door"}},
    {"entity_id": "cover.garage", "state": "closed", "attributes": {"friendly_name": "Garage door", "device_class": "garage"}},
    {"entity_id": "cover.blinds", "state": "closed", "attributes": {"friendly_name": "Living room blinds", "device_class": "blind"}},
    {"entity_id": "binary_sensor.bath_window", "state": "on", "attributes": {"friendly_name": "Bathroom window", "device_class": "window"}},
    {"entity_id": "sensor.bedroom_temperature", "state": "19.5", "attributes": {"friendly_name": "Bedroom temperature", "device_class": "temperature", "unit_of_measurement": "°C"}},
    {"entity_id": "climate.hall", "state": "heat", "attributes": {"friendly_name": "Hall", "current_temperature": 20.5, "temperature": 21}},
    {"entity_id": "script.wipe_everything", "state": "off", "attributes": {"friendly_name": "Wipe everything script"}},
]


class FakeHA:
    def __init__(self, token="good-token"):
        self.calls, outer = [], self

        class H(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def _go(self):
                if self.headers.get("Authorization") != f"Bearer {token}":
                    self.send_response(401); self.end_headers(); return
                n = int(self.headers.get("Content-Length") or 0)
                body = json.loads(self.rfile.read(n)) if n else None
                outer.calls.append((self.command, self.path, body))
                out = {"message": "API running."} if self.path == "/api/" else STATES if self.path == "/api/states" else []
                data = json.dumps(out).encode()
                self.send_response(200); self.send_header("Content-Type", "application/json"); self.end_headers(); self.wfile.write(data)
            do_GET = do_POST = _go
        self.srv = ThreadingHTTPServer(("127.0.0.1", 0), H)
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()
        self.url = f"http://127.0.0.1:{self.srv.server_address[1]}"

    def services(self):
        return [(p, b) for m, p, b in self.calls if m == "POST"]


class Module(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        harness.load_bot()  # provides send, edit, B and esc
        cls.ha = FakeHA()

    def setUp(self):
        self.ha.calls.clear()

    def start(self, url=None, token="good-token", allow_unlock=False):
        import importlib
        import os
        import modules.homeassistant as m
        m = importlib.reload(m)
        os.environ["HL_HA_TOKEN"] = token
        self.addCleanup(os.environ.pop, "HL_HA_TOKEN", None)
        conf = {"homeassistant.url": self.ha.url if url is None else url, "homeassistant.allow_unlock": allow_unlock}
        routes = {}
        app = types.SimpleNamespace(config=types.SimpleNamespace(get=lambda k, d=None: conf.get(k, d)), caps=capabilities.Capabilities(),
                                    router=types.SimpleNamespace(get=lambda p: lambda f: routes.setdefault(p, f)), text_hooks=[], taps={}, brief_lines=[])
        m.register(app)
        self.sent, self.edits = [], []
        m.send = lambda text, buttons=None, **k: self.sent.append((text, buttons)) or {"message_id": len(self.sent)}
        m.edit = lambda msg, text, buttons=None, **k: self.edits.append(text)
        self.m, self.app, self.routes = m, app, routes
        return app

    def say(self, text):
        return any(h(text, text.lower()) for h in self.app.text_hooks)

    def press(self, i=0, row=0):
        data = self.sent[-1][1][row][i]["callback_data"]
        prefix = next(p for p in self.app.taps if data.startswith(p))
        return self.app.taps[prefix](data, {"message_id": 1})

    def test_quiet_until_connected(self):
        app = self.start(url="")
        self.assertFalse(self.say("turn off the kitchen lights"))
        self.assertEqual(app.brief_lines[0](), [])
        st = app.caps.items["homeassistant"].status()
        self.assertTrue(st.get("off"))
        self.assertIn("HL_HA_TOKEN", st["message"])
        self.assertEqual(self.routes["/homeassistant"](None)["connected"], False)
        self.assertEqual(self.ha.calls, [])

    def test_a_wrong_token_is_said_plainly_and_nothing_is_taken(self):
        app = self.start(token="wrong")
        self.assertIn("refused the token", app.caps.items["homeassistant"].status()["message"])
        self.assertFalse(self.say("turn off the kitchen ceiling light"))  # the rest of the bot answers instead

    def test_a_change_asks_first_then_calls_the_one_service(self):
        self.start()
        self.assertTrue(self.say("turn off the kitchen ceiling light"))
        self.assertIn("Turn off <b>Kitchen ceiling light</b>? It is on now.", self.sent[-1][0])
        self.assertEqual(self.ha.services(), [])  # nothing yet
        self.press()
        self.assertEqual(self.ha.services(), [("/api/services/light/turn_off", {"entity_id": "light.kitchen_ceiling"})])
        self.assertEqual(self.edits[-1], "✅ Kitchen ceiling light is off.")
        self.press()  # the same button again
        self.assertEqual(self.edits[-1], "That question is old. Ask again.")
        self.assertEqual(len(self.ha.services()), 1)

    def test_more_than_one_match_asks_which_then_yes_or_no(self):
        self.start()
        self.assertTrue(self.say("switch on the kitchen lights"))
        self.assertEqual([r[0]["text"] for r in self.sent[-1][1][:2]], ["Kitchen ceiling light", "Kitchen counter light"])
        self.press(row=1)
        self.assertIn("Turn on <b>Kitchen counter light</b>? It is off now.", self.sent[-1][0])
        self.press()
        self.assertEqual(self.ha.services(), [("/api/services/light/turn_on", {"entity_id": "light.kitchen_counter"})])

    def test_unlocking_and_opening_the_garage_need_permission_but_blinds_do_not(self):
        self.start()
        self.assertTrue(self.say("unlock the front door"))
        self.assertIn("I don't unlock or open Front door", self.sent[-1][0])
        self.assertTrue(self.say("open the garage"))
        self.assertIn("allow_unlock", self.sent[-1][0])
        self.assertTrue(self.say("open the living room blinds"))
        self.assertIn("Open <b>Living room blinds</b>?", self.sent[-1][0])
        self.assertTrue(self.say("lock the front door"))
        self.assertIn("Lock <b>Front door</b>?", self.sent[-1][0])
        self.start(allow_unlock=True)
        self.assertTrue(self.say("unlock the front door"))
        self.assertIn("Unlock <b>Front door</b>?", self.sent[-1][0])  # still asks first
        self.assertEqual(self.ha.services(), [])

    def test_scripts_and_unknown_things_are_left_to_the_rest_of_the_bot(self):
        self.start()
        self.assertFalse(self.say("turn on the wipe everything script"))
        self.assertFalse(self.say("turn off the spaceship"))
        self.assertFalse(self.say("open the news"))
        self.assertFalse(self.say("what's the temperature in London"))
        self.assertEqual(self.sent, [])

    def test_questions_and_the_home_line(self):
        app = self.start()
        self.assertTrue(self.say("is the front door locked?"))
        self.assertIn("Front door: <b>locked</b>", self.sent[-1][0])
        self.assertTrue(self.say("what's the temperature in the bedroom"))
        self.assertIn("Bedroom temperature: <b>19.5°C</b>", self.sent[-1][0])
        self.assertTrue(self.say("how warm is it in the hall"))
        self.assertIn("Hall: <b>20.5°</b>", self.sent[-1][0])
        line = "1 open: Bathroom window • 1 light on • Hall 20.5° (set to 21°)"
        self.assertTrue(self.say("/home"))
        self.assertIn(line, self.sent[-1][0])
        self.assertEqual(app.brief_lines[0](), [("🏠", "HOME", [line])])
        self.assertEqual(self.routes["/homeassistant"](None), {"connected": True, "line": line, "msg": ""})


class Hooks(unittest.TestCase):
    """The bot tries module sentences before the AI classifier, and module buttons by their prefix; the brief adds module sections."""
    @classmethod
    def setUpClass(cls):
        cls.bot = harness.load_bot()

    def test_the_bot_and_the_brief_use_module_hooks(self):
        from unittest import mock
        from core.telegram import handlers
        heard, tapped = [], []
        hook = lambda text, t: heard.append(t) or t == "make it cosy"
        core_app.TEXT_HOOKS.append(hook)
        core_app.TAPS["cosy:"] = lambda data, msg: tapped.append(data)
        more = lambda: [("🏠", "HOME", ["All lights off"])]
        core_app.BRIEF_LINES.append(more)
        self.addCleanup(core_app.TEXT_HOOKS.remove, hook)
        self.addCleanup(core_app.TAPS.pop, "cosy:")
        self.addCleanup(core_app.BRIEF_LINES.remove, more)
        with mock.patch.object(handlers._intent, "classify", side_effect=AssertionError("the classifier should not be asked")):
            handlers.route("make it cosy")
        self.assertEqual(heard, ["make it cosy"])
        with mock.patch.object(handlers, "tg", lambda *a, **k: None):
            handlers.on_callback({"id": "1", "data": "cosy:on", "message": {"message_id": 1}})
        self.assertEqual(tapped, ["cosy:on"])
        from modules import briefing
        with mock.patch.object(briefing, "backup_line", lambda: "ok"):
            _, html, _ = briefing.build_briefing()
        self.assertIn("All lights off", html)


if __name__ == "__main__":
    unittest.main()
