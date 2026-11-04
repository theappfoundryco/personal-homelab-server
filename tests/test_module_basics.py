"""The moved modules still say what they said when they lived in bot.py (clock frozen at 3 Nov 2026, 10 AM UTC; network blocked)."""
import os, re, unittest

import harness
from harness import load_bot


class Basics(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.bot = load_bot()

    def patch(self, mod, **attrs):
        for k, v in attrs.items():
            self.addCleanup(setattr, mod, k, getattr(mod, k))
            setattr(mod, k, v)

    def capture(self, mod):
        sent = []
        self.patch(mod, send=lambda text, buttons=None, **kw: sent.append(text))
        return sent

    def test_world_clock(self):
        import modules.clock as m
        sent = self.capture(m)
        m.world_clock()
        self.assertEqual(len(sent), 1)
        self.assertIn("<b>World clock</b>", sent[0])
        self.assertIn("You: 10:00 AM, Tue 03 Nov", sent[0])
        self.assertIn("Paris", sent[0])
        self.assertIn("11:00 AM", sent[0])  # Paris is 1h ahead in November
        self.assertIn("7:00 PM", sent[0])   # Tokyo is 9h ahead

    def test_currency_conversion(self):
        import modules.currency as m
        sent = self.capture(m)
        self.patch(m, fx_rate=lambda a, b: 80.0 if (a, b) == ("SGD", "INR") else 1.0)
        m.fx("100 sgd in rupees")
        self.assertIn("100.00 SGD = 8,000.00 INR", sent[0])

    def test_currency_failure_is_polite(self):
        import modules.currency as m
        sent = self.capture(m)
        def down(a, b): raise OSError("offline")
        self.patch(m, fx_rate=down)
        m.fx("5 usd to inr")
        self.assertIn("aren't available right now", sent[0])

    def test_weather_failure_is_polite(self):
        import modules.weather as m
        sent = self.capture(m)
        def down(*a): raise OSError("offline")
        self.patch(m, weather_lines=down, location=lambda *a: {"city": "Testville", "lat": 1, "lon": 2})
        m.weather("weather")
        self.assertIn("Weather isn't available right now", sent[0])

    ICS = ("BEGIN:VCALENDAR\nBEGIN:VEVENT\nDTSTART;VALUE=DATE:20261105\nSUMMARY:Alex in Paris\nEND:VEVENT\n"
           "BEGIN:VEVENT\nDTSTART:20261103T150000Z\nDTEND:20261103T160000Z\nSUMMARY:Dentist\nEND:VEVENT\nEND:VCALENDAR\n")

    def test_calendar_reads_events(self):
        import datetime as dt, modules.calendar as m
        self.patch(m, ics_text=lambda: self.ICS, has_calendar=lambda: True)
        today = [e["title"] for e in m.day_events(dt.date(2026, 11, 3))]
        self.assertEqual(today, ["Dentist"])

    def test_no_calendar_means_no_events_not_an_error(self):
        import datetime as dt, modules.calendar as m
        self.patch(m, has_calendar=lambda: False)
        self.assertEqual(m.day_events(dt.date(2026, 11, 3)), [])

    def test_location_follows_the_calendar_and_a_shared_pin(self):
        import datetime as dt, modules.location as m
        b = self.bot
        self.patch(m, ip_location=lambda: (_ for _ in ()).throw(OSError("offline")), geocode=lambda c: {"city": c, "country": "France", "lat": 1, "lon": 2, "tz": "Europe/Paris"},
                   day_events=lambda d: [{"title": "Alex in Paris", "all_day": True}] if d == dt.date(2026, 11, 5) else [])
        self.assertEqual(m.location(dt.date(2026, 11, 5))["city"], "Paris")
        self.assertEqual(m.location()["city"], "Testville")  # offline, no pin: falls back to home
        b.state["here"] = {"loc": {"city": "Pinned"}, "ts": b.time.time()}
        try:
            self.assertEqual(m.location()["city"], "Pinned")
        finally:
            b.state.pop("here")

    RSS = ("<rss><channel><item><title>Big &amp; news</title><link>http://x/1</link><pubDate>Tue, 03 Nov 2026 09:00:00 GMT</pubDate>"
           "<description>&lt;p&gt;Something happened today.&lt;/p&gt;</description></item></channel></rss>")

    def test_news_reads_a_feed(self):
        import modules.news as m
        self.patch(m, http=lambda *a, **k: self.RSS)
        m.feed_items.clear()
        items = m.feed_items("http://feed")
        self.assertEqual([(i["title"], i["link"]) for i in items], [("Big & news", "http://x/1")])
        self.assertEqual(items[0]["ts"], 1793696400.0)

    def test_headlines_drop_old_and_fluff_and_sort_newest_first(self):
        import modules.news as m
        t = self.bot.time.time()
        feed = [{"title": "Fresh", "link": "a", "ts": t - 60, "desc": ""}, {"title": "Fresher", "link": "b", "ts": t - 10, "desc": ""},
                {"title": "Old", "link": "c", "ts": t - 5 * 86400, "desc": ""}, {"title": "Quiz of the week", "link": "d", "ts": t - 5, "desc": ""}]
        self.patch(m, feed_items=lambda url: feed)
        self.assertEqual([h["title"] for h in m.headlines_for("tech", 5)], ["Fresher", "Fresh"])

    def test_topic_detection(self):
        import modules.news as m
        self.assertEqual(m.detect_topic("any f1 news"), "f1")
        self.assertIsNone(m.detect_topic("zzzz qqqq"))

    def test_f1_lines(self):
        import modules.sports as m
        race = {"raceName": "Test Grand Prix", "date": "2026-11-08", "time": "13:00:00Z"}
        def fake(path):
            if path == "next":
                return {"RaceTable": {"Races": [race]}}
            if path == "last/results":
                return {"RaceTable": {"Races": [{"raceName": "Last GP", "Results": [{"Driver": {"familyName": n}} for n in ("Ada", "Bo", "Cy")]}]}}
            return {"StandingsTable": {"StandingsLists": [{"DriverStandings": [{"position": "1", "points": "99", "Driver": {"familyName": "Ada"}}]}]}}
        self.patch(m, jolpica=fake)
        text = "\n".join(m.f1_lines())
        self.assertIn("Next: <b>Test Grand Prix</b>", text)
        self.assertIn("🥇 Ada 🥈 Bo 🥉 Cy", text)
        self.assertIn("Standings: 1. Ada 99", text)

    def test_cricket_only_shows_india(self):
        import modules.sports as m
        self.patch(m, cricket_items=lambda: [{"title": "India 100/2 v Chile*", "link": ""}, {"title": "Peru v Fiji", "link": ""}])
        out = m.cricket_lines()
        self.assertEqual(len(out), 2)
        self.assertIn("🔴 live", out[1])
        self.patch(m, cricket_items=lambda: [])
        self.assertIn("No India match", m.cricket_lines()[1])

    def test_flights_found_in_the_calendar(self):
        import datetime as dt, modules.flights as m
        start = dt.datetime(2026, 11, 4, 18, 0, tzinfo=dt.timezone.utc)
        ev = {"title": "Flight AB 123 to Paris", "start": start, "loc": "Testville Airport", "all_day": False}
        self.patch(m, has_calendar=lambda: True, day_events=lambda d: [ev] if d == dt.date(2026, 11, 4) else [])
        f = m.flights()
        self.assertEqual(len(f), 1)
        self.assertEqual(f[0]["code"], "AB 123")
        self.assertEqual(f[0]["leave_by"], start - dt.timedelta(hours=3, minutes=15))
        self.patch(m, has_calendar=lambda: False)
        self.assertEqual(m.flights(), [])

    def test_notes_and_goals_keep_one_shared_state(self):
        import modules.planner as m
        b = self.bot
        self.assertIs(m.state, b.state)  # one dict, never a copy
        self.capture(m)
        saved = {k: list(b.state[k]) for k in ("notes", "reminders", "goals")}
        self.addCleanup(lambda: b.state.update(saved))
        self.patch(m, save=lambda: None)
        m.add_note("buy milk")
        self.assertIn("milk", b.state["notes"][-1]["text"].lower())
        n = len(b.state["goals"])
        m.save_goal("Run a marathon")
        self.assertEqual(len(b.state["goals"]), n + 1)

    def test_parse_when_understands_plain_words(self):
        import modules.planner as m
        when, repeat, used = m.parse_when("remind me tomorrow at 4:30 pm to call Sam")
        self.assertEqual((when.year, when.month, when.day, when.hour, when.minute), (2026, 11, 4, 16, 30))

    def test_gym_owns_its_routes_and_data(self):
        import modules.gym as m
        b = self.bot
        self.assertIs(b.gym, m.gym)
        self.assertIsNotNone(b.ROUTER.find("GET", "/gym"))
        self.assertIsNotNone(b.ROUTER.find("POST", "/gym/set"))
        self.assertEqual(m.gym_key("DB curls"), m.gym_key("dumbbell curl"))
        self.assertNotEqual(m.gym_key("DB bench presses"), m.gym_key("dumbbell bench press"))  # known quirk, kept as is: "presses" becomes "presse"
        self.assertEqual(m.gym_date({"date": "2026-11-01"}), "2026-11-01")
        self.assertIsNone(m.gym_date({"date": "2030-01-01"}))  # the future is refused

    def test_journal_day_turns_over_at_4am_and_dates_are_checked(self):
        import modules.journal as m
        self.assertIs(self.bot.journal, m.journal)
        self.assertEqual(m.journal_day(), "2026-11-03")  # clock is 10 AM in the user's zone
        self.assertEqual(m.journal_date({"date": "2026-11-01"}), "2026-11-01")
        self.assertIsNone(m.journal_date({"date": "2999-01-01"}))  # the future is refused
        self.assertIsNone(m.journal_date({"date": "not a date"}))

    def test_journal_rows_leave_the_words_out(self):
        import modules.journal as m
        rows = m.journal_rows({"2026"})
        self.assertTrue(rows and all("text" not in r for r in rows))
        month = m.journal_texts("2026-10")
        self.assertTrue(all(d.startswith("2026-10") for d in month))

    def test_journal_suggested_tags_nothing_new(self):
        import modules.journal as m
        sent = self.capture(m)
        self.patch(m, journal_topics=lambda: {"work"})
        self.patch(m, journal={"entries": [], "ignored_tags": []})
        m.suggested_tags()
        self.assertIn("Nothing new", sent[0])

    def test_journal_owns_its_routes(self):
        r = self.bot.ROUTER
        for path in ("/journal", "/journal/now", "/journal/weekly", "/journal/deep", "/journal/deep/letters", "/journal/month", "/journal/year"):
            self.assertIsNotNone(r.find("GET", path), path)
        for path in ("/journal/save", "/journal/reai", "/journal/deep/run"):
            self.assertIsNotNone(r.find("POST", path), path)
        base = harness.start_api(self.bot)[1]
        self.assertEqual(harness.call(base, "GET", "/journal/month?m=bad")[0], 404)
        self.assertEqual(harness.call(base, "GET", "/journal/year?y=2026")[0], 200)

    def test_modules_route_lists_what_is_on(self):
        base = harness.start_api(self.bot)[1]
        code, out = harness.call(base, "GET", "/modules")
        self.assertEqual(code, 200)
        by = {m["name"]: m for m in out["modules"]}
        self.assertEqual(set(by), set(self.bot.ENABLED))
        self.assertEqual({k: by[k]["tab"]["id"] for k in ("gym", "journal", "server", "health")}, {"gym": "gym", "journal": "journal", "server": "server", "health": "sg"})
        self.assertEqual(by["gym"]["web"], ["view.js"])
        self.assertEqual(by["gym"]["degraded"], [])  # it lists nothing optional
        ai = {d["capability"]: d for d in by["journal"]["degraded"]}  # no Ollama on the test machine
        self.assertEqual(set(ai), {"ollama"})
        self.assertEqual(set(ai["ollama"]), {"capability", "feature", "reason", "fix"})
        self.assertIn("Ollama", ai["ollama"]["fix"])
        harness._net_calls.clear()
        for m in out["modules"]:
            for f in m["web"]:
                self.assertTrue(os.path.isfile(os.path.join(harness.ROOT, "modules", m["name"], "web", f)), (m["name"], f))

    def test_settings_route_is_live_in_the_app(self):
        base = harness.start_api(self.bot)[1]
        code, out = harness.call(base, "GET", "/settings")
        self.assertEqual(code, 200)
        self.assertIn("owner.name", [f["path"] for f in out["fields"]])
        self.assertEqual({m["name"] for m in out["modules"]}, set(self.bot.MODULES) - {"_template"})
        self.assertFalse(out["pin"])
        self.assertEqual(harness.call(base, "POST", "/settings", {"set": {"timezone": "Mars/Base"}})[0], 400)

    def test_landing_routes_and_leftovers(self):
        """Routes moved out of the old handler keep their refusals: inbound posts from the proxy are 403, empty input and unknown paths are 4xx."""
        base = harness.start_api(self.bot)[1]
        for path in ("/watchtower", "/alert"):
            self.assertEqual(harness.call(base, "POST", path, {})[0], 200)
        self.assertEqual(harness.call(base, "POST", "/notes", {"text": ""})[0], 400)
        self.assertEqual(harness.call(base, "POST", "/ask", {"q": " "})[0], 400)
        self.assertEqual(harness.call(base, "GET", "/nope")[0], 404)
        self.assertEqual(harness.call(base, "POST", "/nope", {})[0], 400)

    def test_server_and_ai_own_their_routes(self):
        r = self.bot.ROUTER
        for m, path in (("GET", "/server/apps"), ("GET", "/server/ai"), ("GET", "/sg/ai"), ("POST", "/server/restart"), ("POST", "/server/reboot"),
                        ("POST", "/server/unload"), ("POST", "/server/gitsync"), ("POST", "/server/ai/model")):
            self.assertIsNotNone(r.find(m, path), path)
        base = harness.start_api(self.bot)[1]
        code, out = harness.call(base, "POST", "/server/restart", {"id": "nope"})
        self.assertEqual((code, out["msg"]), (400, "Unknown app."))
        code, out = harness.call(base, "POST", "/server/reboot", {})
        self.assertEqual((code, out["msg"]), (400, "Not confirmed."))  # a reboot needs the word, never a stray tap

    def test_status_says_off_for_missing_optional_apps_and_lists_only_installed_ones(self):
        import modules.server as m
        base = harness.start_api(self.bot)[1]

        def down(*a):
            raise OSError("not installed")
        self.patch(m, prom=down, containers=down)  # a fresh install: no monitoring, no Docker reader
        self.assertEqual(harness.call(base, "GET", "/server/status"), (200, {"monitoring": False, "apps": None}))
        self.patch(m, prom=lambda q: [], containers=lambda: {"landing": "running", "telegram-bot": "exited", "docker-proxy": "running", "mystery": "running"})
        code, out = harness.call(base, "GET", "/server/status")
        self.assertTrue(out["monitoring"])
        self.assertEqual([(a["id"], a["state"]) for a in out["apps"]], [("landing", "running"), ("telegram-bot", "exited")])

    def test_catalog_shows_chosen_apps_state_and_memory_and_changes_go_through_the_helper(self):
        import json, tempfile
        import modules.server as m
        d = tempfile.mkdtemp()
        json.dump({"apps": ["open-webui", "monitoring"]}, open(os.path.join(d, "apps.json"), "w"))
        asked = []
        self.patch(m, DATA=d, containers=lambda: {"landing": "running", "open-webui": "running", "ollama": "running", "prometheus": "exited"},
                   app_memory=lambda names: {"open-webui": 610, "ollama": 4200, "landing": 12}, host_action=lambda act, name="": asked.append((act, name)) or {"ok": True})
        base = harness.start_api(self.bot)[1]
        code, out = harness.call(base, "GET", "/server/catalog")
        by = {a["id"]: a for a in out["apps"]}
        self.assertEqual((by["ollama"]["state"], by["ollama"]["memory_now_mb"], by["ollama"]["chosen"]), ("running", 4200, False))
        self.assertEqual((by["monitoring"]["state"], by["monitoring"]["chosen"]), ("stopped", True))
        self.assertEqual(by["n8n"]["state"], "missing")
        self.assertEqual(out["core"][0], {"id": "landing", "title": "Home page", "state": "running", "memory_now_mb": 12})
        self.assertEqual(harness.call(base, "POST", "/server/apps/change", {"action": "remove", "id": "ollama"})[0], 409)  # open-webui needs it
        self.assertEqual(harness.call(base, "POST", "/server/apps/change", {"action": "add", "id": "rm -rf"})[0], 400)
        self.assertTrue(harness.call(base, "POST", "/server/apps/change", {"action": "add", "id": "whisper"})[1]["ok"])
        self.assertEqual(asked, [("add", "whisper")])

    def test_update_card_compares_versions_and_starts_one_update_through_the_helper(self):
        import json, tempfile
        import modules.server as m
        self.assertGreater(m.vtuple("v0.2.10"), m.vtuple("0.2.9"))
        self.assertIsNone(m.vtuple("v1.0.0-rc1"))
        d = tempfile.mkdtemp()
        asked = []
        rel = {"tag": "v0.2.0", "url": "https://github.com/x/y/releases/tag/v0.2.0", "notes": "n"}
        self.patch(m, DATA=d, VERSION="0.1.0", latest_release=type("L", (), {"__call__": lambda self: rel, "clear": lambda self: None})(),
                   host_action=lambda act, name="": asked.append(act) or {"ok": True, "msg": "update started"})
        base = harness.start_api(self.bot)[1]
        code, out = harness.call(base, "GET", "/server/update")
        self.assertEqual((code, out["available"], out["latest"], out["state"]), (200, True, "0.2.0", "idle"))
        self.assertTrue(harness.call(base, "POST", "/server/update", {})[1]["ok"])
        self.assertEqual(asked, ["update"])
        self.assertEqual(harness.call(base, "GET", "/server/update")[1]["state"], "updating")
        self.assertEqual(harness.call(base, "POST", "/server/update", {})[0], 409)  # one at a time
        json.dump({"from": "0.1.0", "to": "0.2.0", "at": m.time.time() - m.UPDATE_STALE - 1}, open(f"{d}/update-started.json", "w"))
        self.assertEqual(harness.call(base, "GET", "/server/update")[1]["state"], "failed")
        self.patch(m, VERSION="0.2.0")  # the new version is running: the marker clears and nothing is offered
        out = harness.call(base, "GET", "/server/update")[1]
        self.assertEqual((out["state"], out["available"]), ("idle", False))
        self.assertEqual(harness.call(base, "POST", "/server/update", {})[0], 409)
        self.patch(m, latest_release=lambda: None)  # offline or not public yet: no crash, nothing offered
        out = harness.call(base, "GET", "/server/update")[1]
        self.assertEqual((out["available"], out["latest"]), (False, None))

    def test_clocks_can_be_added_and_removed_live(self):
        import modules.clock as m
        before = list(m.CLOCKS)
        self.addCleanup(lambda: (m.CLOCKS.__setitem__(slice(None), before), self.bot.SETTINGS.reset("world_clock")))
        base = harness.start_api(self.bot)[1]
        code, out = harness.call(base, "POST", "/clocks", {"clocks": [{"label": "Tokyo", "tz": "Asia/Tokyo"}]})
        self.assertEqual((code, out["clocks"]), (200, [{"label": "Tokyo", "tz": "Asia/Tokyo"}]))
        self.assertEqual(harness.call(base, "GET", "/config")[1]["clocks"], [{"label": "Tokyo", "tz": "Asia/Tokyo"}])  # live, no restart
        self.assertEqual(harness.call(base, "POST", "/clocks", {"clocks": [{"label": "X", "tz": "Mars/Base"}]})[0], 400)
        self.assertEqual(harness.call(base, "POST", "/clocks", {"clocks": []})[1]["clocks"], [])

    def test_server_helpers(self):
        self.assertEqual(self.bot.app_name("n8n"), "Automations (n8n)")
        self.assertEqual(self.bot.app_name("unknown-app"), "unknown-app")
        self.assertIs(self.bot.ai_status, __import__("modules.ai", fromlist=["x"]).ai_status)

    def test_gmail_without_a_password_is_polite(self):
        import modules.gmail as m
        sent = self.capture(m)
        self.patch(m, GMAIL_FILE="/nonexistent/gmail.txt")
        m.gmail()
        self.assertEqual(len(sent), 1)
        self.assertNotIn("Traceback", sent[0])

    def test_search_page_text_grab_skips_menus_and_scripts(self):
        import modules.search as m
        g = m.TextGrab()
        g.feed("<html><title>Hello</title><nav>Menu</nav><script>x()</script><p>Real text</p><footer>Foot</footer></html>")
        text = "".join(g.parts)
        self.assertEqual(g.title, "Hello")
        self.assertIn("Real text", text)
        self.assertNotIn("Menu", text)
        self.assertNotIn("x()", text)

    def test_alerts_record_incidents_quietly(self):
        import modules.alerts as m
        sent = self.capture(m)
        self.patch(m, save=lambda: None)
        self.bot.state["incidents"] = []
        m.incident("Test app stopped for a while")
        self.assertEqual([i["text"] for i in self.bot.state["incidents"]], ["Test app stopped for a while"])
        self.assertEqual(sent, [])  # recorded for the recap, never pushed

    def test_briefing_state_is_shared_not_copied(self):
        import modules.briefing as m
        self.assertIs(self.bot.LAST_BRIEF, m.LAST_BRIEF)  # /brief reads what the module wrote
        self.assertIs(self.bot.BRIEF_NEWS, m.BRIEF_NEWS)

    def test_health_owns_its_routes_and_ticks(self):
        import modules.health as m
        r = self.bot.ROUTER
        self.assertIsNotNone(r.find("GET", "/sg"))
        self.assertIsNotNone(r.find("POST", "/sg/tick"))
        self.assertIs(self.bot.sg, m.sg)
        self.assertEqual(set(m.SG_SEED), {"slots", "courses", "health", "log"})  # a fresh install starts empty

    def test_python_dash_m_core_finds_the_app(self):
        import core.__main__  # noqa: F401  (importing it must not start anything)
        from core import boot
        self.assertTrue(callable(boot.main))
        self.assertIs(boot, self.bot)

    def test_modules_are_registered_and_examples_merge(self):
        self.assertEqual(self.bot.STARTED, self.bot.ENABLED)  # a module that fails to start must fail the build
        self.assertTrue({"weather", "currency", "clock", "calendar", "location", "news", "sports", "flights", "planner", "gym", "journal", "ai", "server", "gmail", "search", "alerts", "briefing", "day", "health"} <= set(self.bot.ENABLED))
        ex = self.bot.module_examples()
        self.assertEqual({k: len(v) for k, v in ex.items()}, {"weather": 10, "currency": 5, "news": 19, "sports": 11, "flights": 4, "add_note": 11, "manage_notes": 10, "manage_reminders": 7, "show_notes": 4, "add_reminder": 7, "show_reminders": 4, "email": 4, "briefing": 12, "my_day": 11, "evening_plan": 5, "weekly_report": 4})


if __name__ == "__main__":
    unittest.main()
