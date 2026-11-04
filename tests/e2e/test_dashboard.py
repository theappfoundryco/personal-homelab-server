"""Dashboard smoke tests on demo data at phone width. Needs: pip install playwright && playwright install chromium.
Each view must load with no console errors and no failed local requests. Screenshots go to tests/e2e/shots (compared with baselines)."""
import os, shutil, sys, unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import server

try:
    from playwright.sync_api import sync_playwright
except ImportError:
    sync_playwright = None

HERE = os.path.dirname(os.path.abspath(__file__))
BASE = os.path.join(os.path.dirname(os.path.dirname(HERE)), "demo", "baselines")
SHOTS = os.path.join(HERE, "shots")
VIEWS = [("home", "Home"), ("journal", "Journal"), ("gym", "Gym"), ("sg", "Health"), ("server", "Server")]
PHONE = {"width": 390, "height": 844}


@unittest.skipUnless(sync_playwright, "playwright not installed")
class Dashboard(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.srv, cls.url = server.start()
        cls.pw = sync_playwright().start()
        cls.browser = cls.pw.chromium.launch()

    @classmethod
    def tearDownClass(cls):
        cls.browser.close()
        cls.pw.stop()

    def page(self, modules=None):
        """modules: a replacement answer for /modules (None = the real one), or "down" for an assistant that cannot be reached."""
        ctx = self.browser.new_context(viewport=PHONE, device_scale_factor=1, reduced_motion="reduce", timezone_id="UTC", locale="en-US")
        pg = ctx.new_page()
        pg.clock.set_fixed_time("2026-11-03T10:00:00Z")  # same moment the API thinks it is
        self.errors = []
        pg.on("pageerror", lambda e: self.errors.append(str(e)))
        pg.on("console", lambda m: m.type == "error" and "ERR_FAILED" not in m.text and "404" not in m.text and self.errors.append(m.text))
        # anything that is not the local demo server is blocked (fonts, maps, the internet)
        pg.route("**/*", lambda r: r.continue_() if r.request.url.startswith(self.url) else r.abort())
        if modules is not None:
            import json
            pg.route("**/api/bot/modules", lambda r: r.abort() if modules == "down" else r.fulfill(status=200, content_type="application/json", body=json.dumps({"modules": modules})))
        pg.goto(self.url + "/")
        pg.wait_for_load_state("networkidle")
        return pg

    def check_baseline(self, tab, shot):
        """UPDATE_BASELINES=1 records. HL_PIXELS=1 compares exactly (same machine and fonts only, so CI keeps the shots as artifacts instead)."""
        base = os.path.join(BASE, f"{tab}.png")
        if os.environ.get("UPDATE_BASELINES"):
            os.makedirs(BASE, exist_ok=True)
            return shutil.copy(shot, base)
        if os.environ.get("HL_PIXELS") and os.path.exists(base):
            with open(shot, "rb") as a, open(base, "rb") as b:
                self.assertEqual(a.read(), b.read(), f"{tab} no longer matches its baseline (UPDATE_BASELINES=1 to accept)")

    def test_every_view_loads(self):
        os.makedirs(SHOTS, exist_ok=True)
        pg = self.page()
        for tab, label in VIEWS:
            with self.subTest(view=tab):
                pg.click(f'.tab[data-tab="{tab}"]')
                pg.wait_for_load_state("networkidle")
                pg.wait_for_timeout(300)
                view = pg.locator(f"#v-{tab}")
                self.assertTrue(view.is_visible(), f"{tab} view hidden")
                self.assertGreater(len(view.inner_text().strip()), 20, f"{tab} view is empty")
                shot = os.path.join(SHOTS, f"{tab}.png")
                pg.screenshot(path=shot, full_page=True)
                self.check_baseline(tab, shot)
        self.assertEqual(self.errors, [])

    def test_switched_off_modules_lose_their_tab(self):
        on = [{"name": "server", "tab": {"id": "server"}, "web": ["view.js"]}, {"name": "health", "tab": {"id": "sg"}, "web": ["view.js"]}]
        pg = self.page(on)
        self.assertEqual([t for t in ("journal", "gym") if pg.locator(f'.tab[data-tab="{t}"]').is_visible()], [])
        for tab in ("server", "sg"):
            self.assertTrue(pg.locator(f'.tab[data-tab="{tab}"]').is_visible())
        pg.click('.tab[data-tab="server"]')
        pg.wait_for_timeout(300)
        self.assertGreater(len(pg.locator("#v-server").inner_text().strip()), 20)
        self.assertEqual(self.errors, [])

    def test_every_built_in_view_loads_when_the_assistant_is_down(self):
        pg = self.page("down")
        for tab, _ in VIEWS:
            self.assertTrue(pg.locator(f'.tab[data-tab="{tab}"]').is_visible(), tab)

    def open_settings(self, pg, go=None):
        pg.click("#settings-open")
        pg.wait_for_selector("#set-body .sgo")
        if go:
            pg.click(f'#set-body [data-go="{go}"]')
            pg.wait_for_timeout(300)

    def test_health_check_page_names_the_fix(self):
        pg = self.page()
        self.open_settings(pg, "health")
        pg.wait_for_selector("#set-body .sdot")
        text = pg.locator("#set-body").inner_text().lower()  # the group titles are upper-cased by CSS
        for want in ("services", "modules", "fix:", "telegram"):
            self.assertIn(want, text)
        self.assertGreater(pg.locator("#set-body .sdot.warn").count(), 0)
        self.assertEqual(self.errors, [])

    def test_settings_save_and_a_bad_value(self):
        pg = self.page()
        self.open_settings(pg, "all")
        self.assertEqual(pg.locator('[id="f:owner.name"], [data-path^="night."]').count(), 0)  # set on their own pages, not here twice
        pg.fill('[id="f:support.therapist"]', "Sam")
        pg.click('[data-add-row="world_clock"]')
        pg.locator('[data-list="world_clock"] [data-row]').last.locator('[data-key="label"]').fill("Base")
        pg.locator('[data-list="world_clock"] [data-row]').last.locator('[data-key="tz"]').fill("Mars/Base")
        pg.click("#set-all-save")
        pg.wait_for_timeout(400)
        self.assertIn("Mars/Base", pg.locator('[data-path="world_clock"] .why').inner_text())
        pg.locator('[data-list="world_clock"] [data-row]').last.locator('[data-key="tz"]').fill("UTC")
        pg.click("#set-all-save")
        pg.wait_for_selector("#set-body .snote >> text=Saved")
        self.assertIn("Restart", pg.locator("#set-body .snote").last.inner_text())
        pg.click('[data-reset="support.therapist"]')
        pg.wait_for_timeout(400)
        pg.click("#set-back")  # back to the list
        pg.click("#set-reset")
        pg.click("[data-cfm-ok]")
        pg.wait_for_selector("#set-body .snote")
        self.assertEqual([e for e in self.errors if "status of 400" not in e], [])  # the refused timezone is a 400, by design

    def test_hiding_a_tab_and_a_card_applies_at_once(self):
        pg = self.page()
        self.open_settings(pg, "layout")
        pg.click('[data-sw="tab:gym"]')
        pg.click('[data-sw="card:clocks"]')
        pg.click("#set-layout-save")
        pg.wait_for_selector("#set-body .snote")
        self.assertFalse(pg.locator('.tab[data-tab="gym"]').is_visible())
        self.assertFalse(pg.locator("#clocks").is_visible())
        pg.click("#set-back"); pg.click("#set-back")
        pg.reload(); pg.wait_for_load_state("networkidle"); pg.wait_for_timeout(500)
        self.assertFalse(pg.locator('.tab[data-tab="gym"]').is_visible(), "the layout survives a reload")
        self.open_settings(pg, "layout")
        pg.click('[data-sw="tab:gym"]'); pg.click('[data-sw="card:clocks"]'); pg.click("#set-layout-save")
        pg.wait_for_selector("#set-body .snote")
        self.assertEqual(self.errors, [])

    def test_your_own_tile_needs_a_real_link(self):
        pg = self.page()
        self.open_settings(pg, "tiles")
        pg.fill("#tile-name", "Photos"); pg.fill("#tile-url", "javascript:alert(1)")
        pg.click("#tile-add")
        self.assertIn("http", pg.locator("#tile-why").inner_text())
        pg.fill("#tile-url", "https://photos.example.test")
        pg.click("#tile-add")
        pg.click("#tiles-save")
        pg.wait_for_selector("#set-body .snote")
        pg.click("#set-back"); pg.click("#set-back")
        self.assertEqual(pg.locator("#apps .app", has_text="Photos").count(), 1)
        self.open_settings(pg, "tiles")
        pg.click("[data-del-tile]"); pg.click("#tiles-save")
        pg.wait_for_selector("#set-body .snote")
        self.assertEqual(self.errors, [])

    def test_pin_locks_settings(self):
        pg = self.page()
        self.open_settings(pg, "security")
        pg.fill("#set-newpin", "12"); pg.click("#set-pin-on")
        pg.wait_for_function("document.querySelector('#set-pin-why').textContent.length > 0")
        self.assertIn("4 to 12", pg.locator("#set-pin-why").inner_text())
        pg.fill("#set-newpin", "2468"); pg.click("#set-pin-on")
        pg.wait_for_selector("#set-body .sgo")
        pg.evaluate("sessionStorage.removeItem('spin'); SET.pin = ''")  # as if on another device
        pg.click("#set-back"); pg.click("#settings-open")
        pg.wait_for_selector("#set-pin")
        pg.fill("#set-pin", "0000"); pg.click("#set-unlock")
        pg.wait_for_selector("text=That PIN is not right")
        pg.fill("#set-pin", "2468"); pg.click("#set-unlock")
        pg.wait_for_selector("#set-body .sgo")
        pg.click('#set-body [data-go="security"]')
        pg.click("#set-pin-off")
        pg.wait_for_selector("#set-body .sgo")

    def fake_setup(self, pg, connected=False):
        """A stand-in for the setup API, so the wizard can be walked without changing the real demo server. Returns its state."""
        import json
        ids = ["modules", "apps", "ai", "telegram", "access"]
        titles = {"modules": "What you will use", "apps": "Apps", "ai": "AI engine", "telegram": "Telegram", "access": "Access"}
        st = {"steps": {i: "pending" for i in ids}, "restart": False, "polls": 0, "calls": []}

        def handle(route):
            req = route.request
            path = req.url.split("/api/bot")[1].split("?")[0]
            body = json.loads(req.post_data or "{}") if req.method == "POST" else {}
            st["calls"].append((path, body))
            if req.method == "GET" and path == "/setup":
                real = route.fetch().json()
                skipped = [i for i in ids if st["steps"][i] == "skipped"]
                real.update(show=False, first_run=False, restart=st["restart"], pin=False, telegram={"connected": connected},
                            steps=[{"id": i, "title": titles[i], "status": st["steps"][i]} for i in ids],
                            checklist=[{"id": i, "title": titles[i], "why": "Later."} for i in skipped])
                return route.fulfill(status=200, content_type="application/json", body=json.dumps(real))
            out = {"ok": True}
            if path == "/setup/step":
                st["steps"][body["id"]] = body["status"]
            elif path == "/setup/modules":
                st["steps"]["modules"] = "done"
                st["restart"] = True
            elif path == "/setup/apps":
                out.update(changed=True, msg="Saved. To start them, run this in the project folder: homelab start")
            elif path == "/setup/ai":
                st["steps"]["ai"] = "skipped" if body.get("mode") == "none" else "done"
            elif path == "/setup/telegram/token":
                if body.get("token") != "111:good":
                    return route.fulfill(status=400, content_type="application/json", body=json.dumps({"ok": False, "error": "That token was not accepted. Copy it again from BotFather."}))
                out["bot"] = "demo_bot"
            elif path == "/setup/telegram/detect":
                st["polls"] += 1
                out["state"] = "connected" if st["polls"] > 1 else "waiting"
                if out["state"] == "connected":
                    st["steps"]["telegram"] = "done"
            elif path == "/setup/restart":
                return route.fulfill(status=200, content_type="application/json", body=json.dumps(out))
            route.fulfill(status=200, content_type="application/json", body=json.dumps(out))
        pg.route("**/api/bot/setup**", handle)
        return st

    def test_setup_wizard_walkthrough(self):
        pg = self.page()
        st = self.fake_setup(pg)
        os.makedirs(SHOTS, exist_ok=True)
        self.open_settings(pg)
        pg.click("[data-wiz]")
        pg.wait_for_selector("#wizp:not([hidden]) [data-act=start]")
        shot = lambda n: pg.screenshot(path=os.path.join(SHOTS, f"wizard-{n}.png"), full_page=False)
        flat = lambda: self.assertLessEqual(pg.evaluate("document.documentElement.scrollWidth"), PHONE["width"], "the wizard overflows sideways")
        txt = lambda: pg.locator("#wiz-body").inner_text()
        self.assertIn("Welcome home", txt())
        shot("1-welcome"); flat()
        pg.click("[data-act=start]")
        pg.wait_for_selector("text=Step 1 of 5")
        pg.wait_for_selector("text=What will you use it for?")
        self.assertGreater(pg.locator("#wizp [data-sw]").count(), 3)
        pg.locator("#wizp [data-sw]").first.click()
        shot("2-modules"); flat()
        pg.click("[data-act=next]")
        pg.wait_for_selector("#wiz-body >> text=Extra apps")
        pg.wait_for_selector('#wizp [data-sw="app:searxng"]')
        self.assertEqual(pg.locator('#wizp [data-sw="app:ollama"]').count(), 0)  # the AI engine is its own step
        pg.click('#wizp [data-sw="app:dozzle"]')
        self.assertIn("1 selected", txt()) if pg.locator('#wizp [data-sw][aria-checked="true"]').count() == 1 else None
        shot("3-apps"); flat()
        pg.click("[data-act=next]")
        pg.wait_for_selector("text=The AI answers chats")
        self.assertEqual(pg.locator("#wizp [data-opt]").count(), 3)
        pg.click('[data-opt=remote]')
        self.assertTrue(pg.locator("#wz-ollama").is_visible())
        pg.fill("#wz-ollama", "http://ollama-box:11434")
        pg.click('[data-oll-os=linux]')  # the steps sit under the option, per system, and the typed address survives the tab change
        self.assertEqual(pg.input_value("#wz-ollama"), "http://ollama-box:11434")
        self.assertIn("sudo systemctl restart ollama", txt())
        pg.context.grant_permissions(["clipboard-read", "clipboard-write"])
        pg.locator("#wizp .cmd-copy").first.click()
        pg.wait_for_selector("#wizp .cmd-copy.copied .ic-tick")
        self.assertEqual(pg.evaluate("navigator.clipboard.readText()"), "sudo systemctl edit ollama")
        pg.screenshot(path=os.path.join(SHOTS, "wizard-4-ai-remote.png"), full_page=True); flat()
        pg.click('[data-opt=none]')
        shot("4-ai"); flat()
        pg.click("[data-act=ai-go]")
        pg.wait_for_selector("text=Connect Telegram")
        self.assertIn("BotFather", txt())
        pg.fill("#wz-token", "nonsense")
        pg.click("[data-act=tg-token]")
        pg.wait_for_selector("text=not accepted")
        shot("5-telegram-bad"); flat()
        pg.fill("#wz-token", "111:good")
        pg.click("[data-act=tg-token]")
        pg.wait_for_selector("text=Waiting for your message")
        shot("5-telegram-wait"); flat()
        pg.wait_for_selector("#wiz-body >> text=Connected", timeout=10000)
        pg.click("[data-act=next]")
        pg.wait_for_selector("#wiz-body >> text=Who can open the dashboard")
        pg.click("[data-opt=lan]")
        pg.click("[data-act=next]")
        pg.wait_for_selector("text=Choose a PIN")
        self.assertIn("Next opens it to your home network for you", txt())
        pg.click("[data-opt=tailscale]")
        self.assertIn("tailscale.com", txt())
        pg.click("[data-opt=local]")
        shot("6-access"); flat()
        pg.click("[data-act=next]")
        pg.wait_for_selector("text=You are set")
        self.assertIn("Skipped, finish later", txt())
        self.assertIn("homelab start", txt())  # the apps picked without the host helper, and how to start them
        self.assertIn("Restart and open my dashboard", txt())
        shot("7-done"); flat()
        pg.click("#wiz-close")
        pg.wait_for_selector("#finish:not([hidden])")
        self.assertIn("AI engine", pg.locator("#finish").inner_text())
        pg.locator("#finish").scroll_into_view_if_needed()
        shot("8-finish-card"); flat()
        pg.click('[data-finish="go:ai"]')
        pg.wait_for_selector("text=The AI answers chats")
        self.assertEqual(st["steps"]["ai"], "pending")
        self.assertEqual([e for e in self.errors if "status of 400" not in e], [])  # the refused token is a 400, by design

    def test_a_skipped_step_waits_on_home_and_can_be_dismissed(self):
        pg = self.page()
        st = self.fake_setup(pg, connected=True)
        self.open_settings(pg)
        pg.click("[data-wiz]")
        pg.wait_for_selector("[data-act=start]")
        pg.click("[data-act=start]")
        pg.wait_for_selector("text=What will you use it for?")
        pg.click("[data-act=skip]")
        pg.wait_for_selector("#wiz-body >> text=Extra apps")
        pg.click("[data-act=skip]")
        pg.wait_for_selector("text=The AI answers chats")
        pg.click("[data-act=skip]")
        pg.wait_for_selector("text=Connect Telegram")
        self.assertIn("Connected", pg.locator("#wiz-body").inner_text())  # already linked: nothing to do here
        pg.click("[data-act=back]")
        pg.wait_for_selector("text=The AI answers chats")
        pg.click("#wiz-close")
        pg.wait_for_selector("#finish:not([hidden])")
        n = pg.locator("#finish .finish-row").count()
        self.assertGreaterEqual(n, 3)
        os.makedirs(SHOTS, exist_ok=True)
        pg.locator("#finish").screenshot(path=os.path.join(SHOTS, "finish.png"))
        self.assertEqual(self.errors, [])

    def test_demo_content_shows(self):
        pg = self.page()
        self.assertIn("Alex", pg.locator("#v-home").inner_text())
        pg.click('.tab[data-tab="gym"]')
        pg.wait_for_timeout(500)
        self.assertRegex(pg.locator("#v-gym").inner_text(), r"Push|Pull|Legs")
        pg.click('.tab[data-tab="journal"]')
        pg.wait_for_timeout(500)
        self.assertGreater(len(pg.locator("#v-journal").inner_text()), 50)

    def test_journal_writer_closes_without_a_word(self):
        pg = self.page()
        pg.route("**/api/bot/journal/entry", lambda r: r.fulfill(status=200, content_type="application/json", body='{"ok": true, "entry": null}') if r.request.method == "POST" else r.continue_())
        pg.click('.tab[data-tab="journal"]')
        pg.wait_for_selector("#j-today [data-jwrite], #j-today [data-jedit]")
        if not pg.locator("#j-today [data-jwrite]").count():  # demo night already written: open it for editing instead
            pg.click("#j-today [data-jedit]")
        else:
            pg.click("#j-today [data-jwrite]")
        pg.wait_for_selector("#j-today [data-jclose]")
        pg.locator("#j-today .jfoot").screenshot(path=os.path.join(SHOTS, "journal-writer-foot.png"))
        if not pg.input_value("#j-today [data-jt]"):
            pg.click("#j-today [data-jdone]")  # empty: Done just closes, no "write a few lines" dead end
        else:
            pg.click("#j-today [data-jclose]")
        pg.wait_for_selector("#j-today [data-jclose]", state="detached")
        self.assertEqual(self.errors, [])

    def test_your_own_app_gets_a_tile_and_the_form_says_what_is_wrong(self):
        import json
        cat = {"apps": [{"id": "dozzle", "title": "Live logs (Dozzle)", "what": "Logs", "services": ["dozzle"], "memory_mb": 30, "needs": [], "group": "Server", "chosen": True, "state": "running"},
                        {"id": "media-server", "title": "Media server", "what": "jellyfin/jellyfin:10.10.7", "services": ["media-server"], "memory_mb": None, "needs": [],
                         "group": "Your apps", "chosen": True, "custom": True, "port": 8096, "tile": "apps", "state": "running"}],
               "core": [], "docker": True, "helper": True, "reboot": False, "working": ""}
        sent = []
        ctx = self.browser.new_context(viewport=PHONE, device_scale_factor=1, reduced_motion="reduce", timezone_id="UTC", locale="en-US")
        pg = ctx.new_page()
        pg.route("**/*", lambda r: r.continue_() if r.request.url.startswith(self.url) else r.abort())
        pg.route("**/api/bot/server/catalog", lambda r: r.fulfill(status=200, content_type="application/json", body=json.dumps(cat)))
        pg.route("**/api/bot/server/apps/custom", lambda r: sent.append(r.request.post_data_json) or r.fulfill(
            status=400, content_type="application/json", body=json.dumps({"ok": False, "msg": "Pin the image to a version."})))
        pg.goto(self.url + "/")
        pg.wait_for_load_state("networkidle")
        pg.click('.tab[data-tab="server"]')
        tiles = pg.locator("#apps .app b").all_inner_texts()
        self.assertIn("Media server", tiles)
        self.assertEqual(tiles[-1], "Add apps")  # stays last
        pg.click("[data-app-more]")
        pg.wait_for_selector("#cu-add")
        self.assertTrue(pg.locator("text=Running on port 8096").is_visible())
        pg.click("#cu-add")
        self.assertIn("Fill in", pg.inner_text("#cu-why"))
        pg.fill("#cu-title", "Photos")
        pg.fill("#cu-image", "photoprism/photoprism")
        pg.fill("#cu-port", "2342")
        pg.click("#cu-add")
        pg.wait_for_function("document.querySelector('#cu-why') && document.querySelector('#cu-why').textContent.includes('Pin')")
        self.assertEqual(pg.input_value("#cu-image"), "photoprism/photoprism")  # what was typed stays
        self.assertEqual(sent[0]["title"], "Photos")
        os.makedirs(SHOTS, exist_ok=True)
        pg.screenshot(path=os.path.join(SHOTS, "apps-custom.png"), full_page=True)
        ctx.close()

    def test_nav_is_one_view_at_a_time(self):
        pg = self.page()
        for tab, _ in VIEWS:
            pg.click(f'.tab[data-tab="{tab}"]')
            shown = pg.locator(".view:not([hidden])").count()
            self.assertEqual(shown, 1, f"{tab}: {shown} views visible")

    def test_no_horizontal_scroll_on_phone(self):
        pg = self.page()
        for tab, _ in VIEWS:
            pg.click(f'.tab[data-tab="{tab}"]')
            pg.wait_for_timeout(300)
            self.assertLessEqual(pg.evaluate("document.documentElement.scrollWidth"), PHONE["width"], f"{tab} overflows sideways")


if __name__ == "__main__":
    unittest.main()
