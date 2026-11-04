"""Settings made in the dashboard: they sit on top of config.yaml, are checked like it, reset cleanly, and the optional PIN guards changes."""
import io, json, os, tempfile, unittest

import harness  # noqa: F401  (puts core on the path)
from core import config, http_api, settings


def make(base=None, over=None, pin=None):
    d = tempfile.mkdtemp(prefix="hl-settings-")
    if over is not None:
        json.dump(over, open(os.path.join(d, "settings.json"), "w"))
    s = settings.Settings(d, config.Config(base or {"owner": {"name": "Alex"}, "timezone": "UTC", "modules": {"gym": True}}), log=lambda m: None)
    if pin:
        s.set_pin(pin)
    return s, d


class Settings(unittest.TestCase):
    def test_the_page_wins_over_the_file_and_reset_goes_back(self):
        s, d = make()
        self.assertEqual(s.set({"owner.name": "Sam", "schedule.briefing": "6:45 AM"}), (True, []))
        eff = s.merged()
        self.assertEqual((eff["owner"]["name"], eff["schedule"]["briefing"], eff["timezone"]), ("Sam", "6:45 AM", "UTC"))
        self.assertEqual(json.load(open(os.path.join(d, "settings.json")))["owner"]["name"], "Sam")  # survives a restart
        s.reset("owner.name")
        self.assertEqual(s.merged()["owner"]["name"], "Alex")
        self.assertEqual(s.merged()["schedule"]["briefing"], "6:45 AM")
        s.reset()
        self.assertNotIn("schedule", s.merged())

    def test_values_are_checked_with_the_config_rules_and_nothing_half_saves(self):
        s, _ = make()
        ok, problems = s.set({"owner.name": "Sam", "timezone": "Mars/Base", "schedule.briefing": "25:99"})
        self.assertFalse(ok)
        self.assertEqual(len(problems), 2)
        self.assertEqual(s.merged()["owner"]["name"], "Alex")  # all or none
        self.assertFalse(s.set({"nope.thing": 1})[0])
        self.assertFalse(s.set({"home": 1})[0])
        self.assertTrue(s.set({"modules.gym": False, "features.therapy_recap": True, "home.lat": 51})[0])

    def test_apply_changes_the_config_in_place_and_keeps_the_file_values_for_reset(self):
        base = config.Config({"owner": {"name": "Alex"}})
        s = settings.Settings(tempfile.mkdtemp(), base, log=lambda m: None)
        s.set({"owner.name": "Sam"})
        cfg = s.apply(base)
        self.assertIs(cfg, base)
        self.assertEqual(base.get("owner.name"), "Sam")
        self.assertEqual(s.view()["fields"][0]["default"], "Alex")

    def test_a_broken_settings_file_is_ignored_with_a_message(self):
        seen = []
        d = tempfile.mkdtemp()
        json.dump({"timezone": "Mars/Base"}, open(os.path.join(d, "settings.json"), "w"))
        s = settings.Settings(d, config.Config({"timezone": "UTC"}), log=seen.append)
        self.assertEqual(s.merged()["timezone"], "UTC")
        self.assertTrue(seen)
        open(os.path.join(d, "settings.json"), "w").write("{not json")
        self.assertEqual(settings.Settings(d, config.Config({"timezone": "UTC"})).merged()["timezone"], "UTC")

    def test_a_module_for_another_platform_shows_as_off_even_when_its_default_is_on(self):
        s, _ = make()
        v = s.view([{"name": "net", "title": "Network", "description": "", "default": True, "requires": [], "unavailable": True},
                    {"name": "gym", "title": "Gym", "description": "", "default": True, "requires": [], "unavailable": False}])
        self.assertEqual([m["enabled"] for m in v["modules"]], [False, True])

    def test_view_lists_every_field_and_marks_what_changed(self):
        s, _ = make()
        s.set({"owner.name": "Sam"})
        v = s.view([{"name": "gym", "title": "Gym", "description": "", "default": True, "requires": []}])
        by = {f["path"]: f for f in v["fields"]}
        self.assertEqual((by["owner.name"]["value"], by["owner.name"]["changed"], by["owner.name"]["kind"]), ("Sam", True, "text"))
        self.assertEqual(by["schedule.briefing"]["kind"], "time")
        self.assertFalse(by["timezone"]["changed"])
        self.assertTrue(v["modules"][0]["enabled"])
        self.assertNotIn("modules", by)

    def test_pin_is_off_by_default_stored_hashed_and_locks_out_guessing(self):
        s, d = make()
        self.assertTrue(s.check_pin(""))
        s.set_pin("2468")
        raw = open(os.path.join(d, "settings.json")).read()
        self.assertNotIn("2468", raw)
        self.assertTrue(s.check_pin("2468"))
        self.assertFalse(s.check_pin("0000"))
        for _ in range(5):
            s.check_pin("1111")
        self.assertTrue(s.locked_out())
        self.assertFalse(s.check_pin("2468"))  # paused for a minute, even for the right one
        again = settings.Settings(d, config.Config({}), log=lambda m: None)
        self.assertTrue(again.pin)  # the PIN survives a restart
        self.assertNotIn("_pin", again.over)

    def test_own_tiles_must_be_web_links_and_layout_is_stored(self):
        s, _ = make()
        self.assertFalse(s.set({"dashboard.tiles": [{"name": "x", "url": "javascript:alert(1)"}]})[0])
        self.assertFalse(s.set({"dashboard.tiles": [{"name": "", "url": "https://a.test"}]})[0])
        self.assertFalse(s.set({"dashboard.tiles": [{"name": "x", "url": "https://a.test", "group": "other"}]})[0])
        ok = s.set({"dashboard.tiles": [{"name": "Photos", "url": "https://photos.test", "group": "apps"}], "dashboard.tabs": ["server", "gym"], "dashboard.home_hidden": ["clocks"]})
        self.assertTrue(ok[0])
        self.assertEqual(s.merged()["dashboard"]["tabs"], ["server", "gym"])
        self.assertNotIn("dashboard.tabs", [f["path"] for f in s.view()["fields"]])  # edited on the layout screens, not as a plain field

    def test_routes(self):
        s, _ = make()
        router = http_api.Router()
        settings.routes(router, s, lambda: [])
        run = lambda m, p, body=None, pin="": _call(router, m, p, body, pin)
        self.assertEqual(run("GET", "/settings")[0], 200)
        self.assertEqual(run("POST", "/settings", {"set": {"owner.name": "Sam"}})[1], {"ok": True, "restart": True})
        code, out = run("POST", "/settings", {"set": {"timezone": "Mars/Base"}})
        self.assertEqual(code, 400)
        self.assertEqual(len(out["problems"]), 1)
        self.assertEqual(run("POST", "/settings", {})[0], 400)
        self.assertEqual(run("POST", "/settings/pin", {"pin": "12"})[0], 400)
        self.assertEqual(run("POST", "/settings/pin", {"pin": "1357"})[1]["pin"], True)
        self.assertEqual(run("GET", "/settings")[0], 403)
        self.assertEqual(run("POST", "/settings", {"set": {"owner.name": "Kim"}})[0], 403)
        self.assertEqual(run("POST", "/settings", {"set": {"owner.name": "Kim"}}, pin="1357")[0], 200)
        self.assertEqual(run("POST", "/settings/reset", {"path": "owner.name"}, pin="1357")[0], 200)
        self.assertEqual(run("POST", "/settings/pin", {"pin": ""}, pin="1357")[1]["pin"], False)
        self.assertEqual(run("GET", "/settings")[0], 200)


def _call(router, method, path, body, pin):
    """Runs a route the way the server would. Returns (status, body)."""
    class H:
        pass
    h = H()
    data = json.dumps(body).encode() if body is not None else b""
    h.path, h.rfile, h.client_address = path, io.BytesIO(data), ("127.0.0.1", 1)
    h.headers = {"Content-Length": str(len(data)), "X-Settings-Pin": pin}
    out = router.find(method, path.split("?")[0])(http_api.Request(h))  # the server matches the path without its query, as here
    obj, code = out if isinstance(out, tuple) else (out, 200)
    return code, obj


if __name__ == "__main__":
    unittest.main()
