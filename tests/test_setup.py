"""The setup wizard's backend: saved progress, the Telegram hand-off, the model download, and its routes, with Telegram and Ollama faked."""
import json
import os
import stat
import tempfile
import threading
import time
import unittest

import harness
from core import config, hardware, http_api, settings, setup
from test_hardware import M2, NVIDIA, PI
from test_settings import _call


def tg(replies):
    """A fake Telegram: replies maps a method to a result (or an Exception to raise). Every call is kept."""
    calls = []

    def api(token, method, params, timeout=15):
        calls.append((method, params))
        r = replies.get(method, {})
        if isinstance(r, Exception):
            raise r
        return {"result": r}
    api.calls = calls
    return api


def make(**kw):
    d = tempfile.mkdtemp(prefix="hl-setup-")
    return setup.Setup(d, log=lambda m: None, **kw), d


class Progress(unittest.TestCase):
    def test_a_fresh_install_is_first_run_unless_telegram_already_works(self):
        s, _ = make()
        self.assertTrue(s.view(False)["first_run"])
        self.assertFalse(s.view(True)["first_run"])  # a running install is not sent through setup

    def test_steps_are_saved_and_the_wizard_resumes_at_the_next_one(self):
        s, d = make()
        s.start()
        s.mark("modules", "done")
        s.mark("apps", "done")
        v = setup.Setup(d).view(False)  # a new process reads the same file
        self.assertEqual(v["next"], "ai")
        self.assertEqual([r["status"] for r in v["steps"]], ["done", "done", "pending", "pending", "pending"])
        self.assertTrue(v["show"])

    def test_finished_when_every_step_is_done_or_skipped_and_skipped_ones_make_the_checklist(self):
        s, _ = make()
        for i, st in zip(setup.IDS, ["done", "done", "skipped", "skipped", "done"]):
            s.mark(i, st)
        v = s.view(False)
        self.assertTrue(v["finished"])
        self.assertFalse(v["show"])
        self.assertEqual([c["id"] for c in v["checklist"]], ["ai", "telegram"])
        s.dismiss("telegram")
        self.assertEqual([c["id"] for c in s.view(False)["checklist"]], ["ai"])
        self.assertEqual([c["id"] for c in s.view(False, ["calendar"])["checklist"]], ["ai", "calendar"])

    def test_unknown_steps_and_statuses_are_refused(self):
        s, _ = make()
        self.assertFalse(s.mark("nope", "done"))
        self.assertFalse(s.mark("ai", "maybe"))


class Telegram(unittest.TestCase):
    def test_environment_beats_the_saved_login(self):
        s, d = make(tg_api=tg({"getMe": {"username": "my_bot"}}))
        s.telegram_token("111:abc")
        self.assertEqual(setup.telegram_login(d, {}), ("111:abc", 0))
        self.assertEqual(setup.telegram_login(d, {"TG_TOKEN": "222:xyz", "TG_CHAT": "5"}), ("222:xyz", 5))
        self.assertEqual(setup.telegram_login(tempfile.mkdtemp(), {}), ("", 0))

    def test_bad_tokens(self):
        s, d = make(tg_api=tg({"getMe": OSError("401")}))
        self.assertIn("does not look like", s.telegram_token("nonsense")[1]["error"])
        ok, out = s.telegram_token("111:abc")
        self.assertFalse(ok)
        self.assertIn("not accepted", out["error"])
        self.assertFalse(os.path.exists(os.path.join(d, setup.SECRET)))

    def test_good_token_is_kept_private_and_never_returned(self):
        s, d = make(tg_api=tg({"getMe": {"username": "my_bot"}}))
        ok, out = s.telegram_token(" 111:abc ")
        self.assertEqual((ok, out), (True, {"bot": "my_bot"}))
        p = os.path.join(d, setup.SECRET)
        self.assertEqual(stat.S_IMODE(os.stat(p).st_mode), 0o600)
        self.assertNotIn("111:abc", json.dumps(out))

    def test_waits_for_start_then_connects(self):
        api = tg({"getMe": {"username": "b"}, "getUpdates": []})
        s, d = make(tg_api=api)
        s.telegram_token("111:abc")
        self.assertEqual(s.telegram_detect()["state"], "waiting")
        group = {"update_id": 7, "message": {"chat": {"id": -100, "type": "group"}}}
        api2 = tg({"getUpdates": [group]})
        s.tg_api = api2
        self.assertEqual(s.telegram_detect()["state"], "waiting")  # someone else's group is not you
        dm = {"update_id": 8, "message": {"chat": {"id": 4242, "type": "private"}, "text": "/start"}}
        api3 = tg({"getUpdates": [group, dm]})
        s.tg_api = api3
        self.assertEqual(s.telegram_detect()["state"], "connected")
        self.assertEqual(setup.telegram_login(d, {}), ("111:abc", 4242))
        methods = [m for m, _ in api3.calls]
        self.assertEqual(methods, ["getUpdates", "getUpdates", "sendMessage"])  # the second one acknowledges, so the bot does not replay /start
        self.assertEqual(api3.calls[1][1]["offset"], 9)
        v = s.view(False)
        self.assertEqual([r["status"] for r in v["steps"]][3], "done")
        self.assertTrue(v["restart"])

    def test_detect_without_a_token_and_with_telegram_down(self):
        s, _ = make()
        self.assertEqual(s.telegram_detect()["state"], "no_token")
        s.tg_api = tg({"getMe": {"username": "b"}})
        s.telegram_token("111:abc")
        s.tg_api = tg({"getUpdates": OSError("down")})
        self.assertEqual(s.telegram_detect()["state"], "waiting")


def wait(s, secs=3):
    end = time.time() + secs
    while s.pull["active"] and time.time() < end:
        time.sleep(0.02)


class Models(unittest.TestCase):
    def test_download_reports_progress_and_marks_the_step_done(self):
        def stream(url, model):
            yield {"status": "pulling manifest"}
            yield {"status": "downloading", "total": 100, "completed": 40}
            yield {"status": "success", "total": 100, "completed": 100}
        s, _ = make(pull_stream=stream)
        self.assertTrue(s.start_pull("http://x", ["a:1", "b:2"]))
        wait(s)
        self.assertTrue(s.pull["done"])
        self.assertEqual([m["status"] for m in s.pull["models"]], ["done", "done"])
        self.assertEqual(s.view(False)["steps"][2]["status"], "done")

    def test_a_failed_download_says_what_to_check_and_can_be_retried(self):
        def stream(url, model):
            raise OSError("connection refused")
            yield
        s, _ = make(pull_stream=stream)
        s.start_pull("http://x", ["a:1"])
        wait(s)
        self.assertIn("Press Download", s.pull["error"])
        self.assertNotIn("connection refused", s.pull["error"])
        self.assertTrue(s.start_pull("http://x", ["a:1"]))

    def test_only_one_download_at_a_time(self):
        gate = threading.Event()

        def stream(url, model):
            gate.wait(3)
            yield {"status": "success"}
        s, _ = make(pull_stream=stream)
        self.assertTrue(s.start_pull("http://x", ["a:1"]))
        self.assertFalse(s.start_pull("http://x", ["a:1"]))
        gate.set()
        wait(s)

    def test_another_machines_ollama_is_checked(self):
        s, _ = make(ollama_tags=lambda url: {"models": []})
        self.assertTrue(s.check_ollama("http://10.0.0.5:11434/")[0])
        self.assertIn("http://", s.check_ollama("10.0.0.5")[1])
        s.ollama_tags = lambda url: (_ for _ in ()).throw(OSError("no route"))
        self.assertIn("Could not reach", s.check_ollama("http://10.0.0.5:11434")[1])

    def test_a_failed_ollama_check_says_what_to_do(self):
        from urllib.error import URLError
        s, _ = make()
        for reason, words in ((ConnectionRefusedError("Connection refused"), "only listens to itself"), (TimeoutError("timed out"), "firewall"),
                              (OSError("Name or service not known"), "could not be found")):
            s.ollama_tags = lambda url, r=reason: (_ for _ in ()).throw(URLError(r))
            self.assertIn(words, s.check_ollama("http://10.0.0.5:11434")[1])


class Routes(unittest.TestCase):
    def build(self, probe=NVIDIA, telegram_on=False, pin=None, add_app=None, host_do=None, **kw):
        kw.setdefault("ollama_tags", lambda url: {"models": []})
        kw.setdefault("sleep", lambda s: None)
        d = tempfile.mkdtemp(prefix="hl-setup-routes-")
        self.settings = settings.Settings(d, config.Config({"owner": {"name": "Alex"}, "timezone": "UTC", "modules": {"gym": True}}), log=lambda m: None)
        if pin:
            self.settings.set_pin(pin)
        self.restarted = threading.Event()
        self.setup = setup.Setup(d, restart=self.restarted.set, log=lambda m: None, **kw)
        hw = hardware.probe(**probe)
        from core.hardware import profiles
        view = {"hardware": hw, "summary": hardware.describe(hw), "recommendation": profiles.recommend(hw)}
        mods = [{"name": "gym", "title": "Gym", "description": "", "default": True, "requires": [], "why_off": "", "unavailable": False},
                {"name": "journal", "title": "Journal", "description": "", "default": True, "requires": [], "why_off": "", "unavailable": False}]
        self.router = http_api.Router()
        setup.routes(self.router, self.setup, self.settings, lambda: view, lambda: mods, lambda: telegram_on, lambda: ["calendar"], lambda: "http://ollama:11434", add_app=add_app, host_do=host_do)
        return lambda m, p, b=None, pin="": _call(self.router, m, p, b, pin)

    def test_get_setup_has_everything_the_wizard_needs(self):
        run = self.build()
        code, out = run("GET", "/setup")
        self.assertEqual(code, 200)
        self.assertEqual(out["next"], "modules")
        self.assertEqual(out["hardware"]["recommendation"]["profile"], "large")
        self.assertEqual([m["name"] for m in out["modules"]], ["gym", "journal"])
        self.assertTrue(out["first_run"])

    def test_the_wizard_opens_by_itself_once_then_what_is_left_waits_on_home(self):
        run = self.build()
        self.assertTrue(run("GET", "/setup")[1]["show"])
        run("POST", "/setup/seen", {})
        run("POST", "/setup/start", {})
        run("POST", "/setup/step", {"id": "modules", "status": "done"})
        out = run("GET", "/setup")[1]  # another tab, or the same one reloaded
        self.assertFalse(out["show"])
        self.assertIn("apps", [c["id"] for c in out["checklist"]])
        self.assertNotIn("modules", [c["id"] for c in out["checklist"]])
        run("POST", "/setup/reset", {})
        self.assertNotIn("seen", self.setup.state())  # Run setup again starts clean

    def test_app_picks_go_to_the_host_helper_and_are_saved_without_it(self):
        run = self.build()
        from core import apps
        apps.save(self.setup.dir, ["dozzle", "ollama"])
        out = run("POST", "/setup/apps", {"apps": ["searxng", "ollama", "bogus"]})[1]
        self.assertEqual(out["cmds"], ["bin/homelab apps add searxng"])  # the test's helper is not running: the command to copy instead
        self.assertEqual(apps.chosen(self.setup.dir), ["ollama", "searxng"])  # the AI engine is left to its own step, dozzle unticked
        self.assertFalse(run("POST", "/setup/apps", {"apps": ["searxng"]})[1]["changed"])

    def test_your_name_and_time_zone_are_saved_and_checked(self):
        run = self.build()
        self.assertEqual(run("GET", "/setup")[1]["profile"], {"name": "Alex", "timezone": "UTC", "home": ""})
        code, out = run("POST", "/setup/profile", {"name": "  Sam  ", "timezone": "Europe/London"})
        self.assertEqual((code, out["ok"]), (200, True))
        self.assertEqual(run("GET", "/setup")[1]["profile"], {"name": "Sam", "timezone": "Europe/London", "home": ""})
        self.assertTrue(run("GET", "/setup")[1]["restart"])  # the clock is read once at start
        self.assertEqual(run("POST", "/setup/profile", {"name": "x" * 41})[0], 400)
        self.assertEqual(run("POST", "/setup/profile", {"timezone": "Not/AZone"})[0], 400)
        self.assertEqual(run("GET", "/setup")[1]["profile"]["name"], "Sam")  # a bad request changes nothing
        self.assertEqual(run("POST", "/setup/profile", {"name": "   "})[0], 200)  # blank keeps what is there
        self.assertEqual(run("GET", "/setup")[1]["profile"]["name"], "Sam")

    def test_the_profile_needs_the_pin_when_one_is_set(self):
        run = self.build(pin="4821")
        self.assertNotEqual(run("POST", "/setup/profile", {"name": "Sam"})[0], 200)
        self.assertEqual(run("POST", "/setup/profile", {"name": "Sam"}, pin="4821")[0], 200)

    def test_modules_are_saved_as_settings_and_unknown_ones_ignored(self):
        run = self.build()
        self.assertEqual(run("POST", "/setup/modules", {"enabled": {"gym": False, "nonsense": True}})[0], 200)
        self.assertFalse(self.settings.merged()["modules"]["gym"])
        self.assertNotIn("nonsense", self.settings.merged()["modules"])
        self.assertEqual(run("GET", "/setup")[1]["steps"][0]["status"], "done")
        self.assertTrue(run("GET", "/setup")[1]["restart"])
        self.assertEqual(run("POST", "/setup/modules", {})[0], 400)

    def test_a_pin_guards_every_change(self):
        run = self.build(pin="2468")
        for m, p, b in [("POST", "/setup/step", {"id": "ai", "status": "skipped"}), ("POST", "/setup/modules", {"enabled": {}}),
                        ("POST", "/setup/telegram/token", {"token": "1:a"}), ("POST", "/setup/ai", {"mode": "none"})]:  # four wrong tries; the fifth would pause them all
            self.assertEqual(run(m, p, b)[0], 403, p)
        self.assertEqual(run("POST", "/setup/step", {"id": "ai", "status": "skipped"}, pin="2468")[0], 200)

    def test_step_skip_and_back(self):
        run = self.build()
        self.assertEqual(run("POST", "/setup/step", {"id": "ai", "status": "skipped"})[0], 200)
        self.assertEqual(run("POST", "/setup/step", {"id": "ai", "status": "pending"})[0], 200)
        self.assertEqual(run("POST", "/setup/step", {"id": "zzz", "status": "done"})[0], 400)

    def test_telegram_token_route_and_refusal_when_already_connected(self):
        run = self.build(tg_api=tg({"getMe": {"username": "b"}}))
        code, out = run("POST", "/setup/telegram/token", {"token": "111:abc"})
        self.assertEqual((code, out["bot"]), (200, "b"))
        self.assertNotIn("111:abc", json.dumps(run("GET", "/setup")[1]))
        self.assertEqual(run("POST", "/setup/telegram/token", {"token": "bad"})[0], 400)
        run2 = self.build(telegram_on=True)
        self.assertEqual(run2("POST", "/setup/telegram/token", {"token": "111:abc"})[0], 409)

    def test_ai_none_and_remote(self):
        run = self.build(ollama_tags=lambda url: {})
        self.assertEqual(run("POST", "/setup/ai", {"mode": "none"})[0], 200)
        self.assertEqual(run("GET", "/setup")[1]["steps"][2]["status"], "skipped")
        self.assertEqual(run("POST", "/setup/ai", {"mode": "remote", "url": "nope"})[0], 400)
        self.assertEqual(run("POST", "/setup/ai", {"mode": "remote", "url": "http://10.0.0.5:11434/"})[0], 200)
        self.assertEqual(self.settings.merged()["ollama"]["url"], "http://10.0.0.5:11434")
        self.assertEqual(run("POST", "/setup/ai", {"mode": "wat"})[0], 400)

    def test_ai_install_sets_the_models_and_downloads_them(self):
        run = self.build(pull_stream=lambda url, m: iter([{"status": "success"}]))
        self.assertEqual(run("POST", "/setup/ai", {"mode": "install"})[0], 200)
        wait(self.setup)
        self.assertEqual(self.settings.merged()["models"]["journal"], "gemma4:26b")
        code, out = run("GET", "/setup/ai/progress")
        self.assertTrue(out["done"])

    def test_ai_install_without_an_engine_installs_the_app_first_or_says_how(self):
        up, asked = [], []

        def tags(url):
            if not up:
                raise OSError("refused")
            return {"models": [{"name": "qwen3.5:4b"}]}
        run = self.build(ollama_tags=tags)
        code, out = run("POST", "/setup/ai", {"mode": "install"})
        self.assertEqual(code, 400)
        self.assertIn("bin/homelab apps add ollama", out["cmds"])  # no host helper: the exact command instead
        run = self.build(ollama_tags=tags, add_app=lambda a: asked.append(a) or up.append(1) or {"ok": True}, pull_stream=lambda url, m: iter([{"status": "success"}]))
        up.clear()
        code, out = run("POST", "/setup/ai", {"mode": "install"})
        self.assertEqual((code, out["installing"], asked), (200, True, ["ollama"]))
        wait(self.setup)
        self.assertTrue(self.setup.pull["done"])
        self.assertIn("already here", [m["status"] for m in self.setup.pull["models"]])  # the model it already had is not downloaded again

    def test_on_a_mac_install_puts_the_engine_on_the_mac_itself(self):
        asked, seen = [], []

        def tags(url):
            seen.append(url)
            if not asked:
                raise OSError("refused")
            return {"models": []}
        run = self.build(probe=M2, ollama_tags=tags, add_app=lambda a: asked.append(a) or {"ok": True}, pull_stream=lambda url, m: iter([{"status": "success"}]))
        code, out = run("POST", "/setup/ai", {"mode": "install", "anyway": True})
        self.assertEqual((code, asked), (200, ["ollama"]))  # the helper runs `homelab apps add ollama`, which uses Homebrew on a Mac
        self.assertEqual(self.settings.merged()["ollama"]["url"], setup.HOST_OLLAMA)
        self.assertTrue(all(u.startswith(setup.HOST_OLLAMA) for u in seen))
        wait(self.setup)

    def test_detect_finds_an_ollama_on_this_machine_and_use_switches_to_it(self):
        run = self.build(ollama_tags=lambda url: {"models": [{"name": "llama3.2:3b"}]} if "host.docker.internal" in url else (_ for _ in ()).throw(OSError("no")),
                         pull_stream=lambda url, m: iter([{"status": "success"}]))
        code, out = run("GET", "/setup/ai/detect")
        self.assertEqual(out["found"], [{"url": "http://host.docker.internal:11434", "models": ["llama3.2:3b"], "where": "this machine"}])
        self.assertEqual(run("POST", "/setup/ai", {"mode": "use", "url": "http://evil.example:11434"})[0], 400)
        self.assertEqual(run("POST", "/setup/ai", {"mode": "use", "url": "http://host.docker.internal:11434"})[0], 200)
        self.assertEqual(self.settings.merged()["ollama"]["url"], "http://host.docker.internal:11434")
        wait(self.setup)

    def test_access_lan_needs_a_pin_and_goes_through_the_host_helper(self):
        asked = []
        run = self.build(host_do=lambda act, name: asked.append((act, name)) or {"ok": True})
        self.assertIn("PIN", run("POST", "/setup/access", {"mode": "lan"})[1]["error"])
        self.settings.set_pin("2468")
        self.assertEqual(run("POST", "/setup/access", {"mode": "lan"}, pin="2468")[0], 200)
        self.assertEqual(asked, [("access", "lan")])
        run = self.build()
        self.assertIn("bin/homelab access local", run("POST", "/setup/access", {"mode": "local"})[1]["cmds"])

    def test_home_city_is_picked_from_a_search_and_saved_with_its_place(self):
        run = self.build()
        real = setup.find_places
        self.addCleanup(setattr, setup, "find_places", real)
        setup.find_places = lambda q: {"results": [{"name": "Leeds", "country": "United Kingdom", "admin1": "England", "latitude": 53.8, "longitude": -1.55, "timezone": "Europe/London"}]}
        code, out = run("GET", "/setup/places?q=lee")
        self.assertEqual(out["places"][0]["city"], "Leeds")
        self.assertEqual(run("POST", "/setup/profile", {"home": out["places"][0]})[0], 200)
        h = self.settings.merged()["home"]
        self.assertEqual((h["city"], h["lat"], h["tz"]), ("Leeds", 53.8, "Europe/London"))
        self.assertEqual(run("GET", "/setup")[1]["profile"]["home"], "Leeds")
        place = lambda region, lat: {"name": "Northfield", "country": "Testland", "admin1": region, "latitude": lat, "longitude": 1.0, "timezone": "UTC"}
        setup.find_places = lambda q: {"results": [place("North", 1.0), place("North", 1.1), place("South", 2.0), place("North", 1.2)]}
        hits = run("GET", "/setup/places?q=nor")[1]["places"]  # the same name in the same region is listed once, the biggest (first) one
        self.assertEqual([(p["region"], p["lat"]) for p in hits], [("North", 1.0), ("South", 2.0)])
        setup.find_places = lambda q: (_ for _ in ()).throw(OSError("offline"))
        self.assertIn("set it later", run("GET", "/setup/places?q=lee")[1]["error"])

    def test_ai_install_warns_before_a_model_that_will_not_fit_and_a_tiny_machine_gets_no_local_ai(self):
        run = self.build(probe=PI)
        code, out = run("POST", "/setup/ai", {"mode": "install"})
        self.assertEqual(code, 400)
        self.assertIn("too small", out["error"])

    def test_restart_route(self):
        run = self.build()
        self.assertEqual(run("POST", "/setup/restart", {})[0], 200)
        self.assertTrue(self.restarted.wait(3))


class Wired(unittest.TestCase):
    def test_the_real_app_answers_get_setup_and_reads_nothing_secret(self):
        bot = harness.load_bot()
        base = harness.start_api(bot)[1]
        code, out = harness.call(base, "GET", "/setup")
        harness._net_calls.clear()
        self.assertEqual(code, 200)
        self.assertFalse(out["first_run"])  # the test app has Telegram configured
        self.assertEqual([s["id"] for s in out["steps"]], setup.IDS)
        self.assertNotIn("test-token", json.dumps(out))


if __name__ == "__main__":
    unittest.main()
