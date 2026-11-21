"""Newer versions of your own apps: which tags count, how a registry is asked, what is said once, and moving to a new version (with a way back)."""
import io
import json
import os
import shutil
import tempfile
import unittest
import urllib.error
from unittest import mock

import harness  # noqa: F401  (puts core on the path)
from core import cli, custom, versions
from test_cli import Base

JELLY = {"id": "media", "title": "Media server", "image": "jellyfin/jellyfin:10.10.7", "port": 8096, "inside": 8096, "keep": "/config", "group": "apps"}
PG = {"id": "db", "title": "Postgres", "image": "postgres:16.4", "port": 5433, "inside": 5432, "keep": "", "group": "tools"}


class Registry:
    """A pretend registry: answers 401 with a token realm until it is given that token, then lists tags in pages."""
    def __init__(self, tags, per=2):
        self.tags, self.per, self.asked = tags, per, []

    def __call__(self, url, headers):
        self.asked.append((url, dict(headers)))
        if url.startswith("https://auth.example.test/token"):
            return {"token": "anon-123"}, ""
        if headers.get("Authorization") != "Bearer anon-123":
            raise urllib.error.HTTPError(url, 401, "Unauthorized", {"WWW-Authenticate": 'Bearer realm="https://auth.example.test/token",service="registry",scope="repository:x:pull"'}, io.BytesIO())
        start = int(url.split("last=")[1]) if "last=" in url else 0
        page = self.tags[start:start + self.per]
        more = start + self.per < len(self.tags)
        name = url.split("/v2/")[1].split("/tags")[0]
        return {"tags": page}, f'</v2/{name}/tags/list?n=2&last={start + self.per}>; rel="next"' if more else ""


class Tags(unittest.TestCase):
    def test_where_each_image_is_asked(self):
        self.assertEqual(versions.split("jellyfin/jellyfin:10.10.7"), ("registry-1.docker.io", "jellyfin/jellyfin", "10.10.7"))
        self.assertEqual(versions.split("postgres:16.4"), ("registry-1.docker.io", "library/postgres", "16.4"))
        self.assertEqual(versions.split("ghcr.io/linuxserver/sonarr:4.0.14"), ("ghcr.io", "linuxserver/sonarr", "4.0.14"))
        self.assertEqual(versions.split("localhost:5000/me/app:1.2"), ("localhost:5000", "me/app", "1.2"))
        self.assertIsNone(versions.split("jellyfin/jellyfin@sha256:" + "a" * 64))

    def test_only_tags_shaped_like_yours_and_higher_count(self):
        avail = ["10.10.6", "10.10.9", "10.11.0", "10.11.1-alpine", "10.11.2-rc1", "11", "latest", "unstable", "10.11.0.1"]
        self.assertEqual(versions.newer("10.10.7", avail), "10.11.0")
        self.assertEqual(versions.newer("10.10.7", avail, same_major=True), "10.11.0")
        self.assertEqual(versions.newer("v2.11.0", ["v2.9.0", "v2.38.1", "2.40.0"]), "v2.38.1")  # 2.40.0 has no v
        self.assertEqual(versions.newer("4.0.14-ls280", ["4.0.14-ls281", "4.0.15-ls279", "4.0.15"]), "4.0.15-ls279")
        self.assertEqual(versions.newer("1.27.3-alpine", ["1.27.4", "1.27.4-alpine", "1.28.0-alpine-slim"]), "1.27.4-alpine")
        self.assertEqual(versions.newer("2.0.0-rc1", ["2.0.0-rc2", "2.0.0"]), "2.0.0-rc2")  # you run a test build, so test builds count
        self.assertEqual(versions.newer("16.4", ["16.10", "17.2", "19.0"], same_major=True), "16.10")
        self.assertIsNone(versions.newer("latest", avail))
        self.assertIsNone(versions.newer("10.11.0", avail))

    def test_the_registry_is_asked_with_an_anonymous_token_page_by_page(self):
        reg = Registry(["1.0.0", "1.1.0", "1.2.0", "2.0.0", "junk"])
        self.assertEqual(versions.tags("example.test/me/app:1.0.0", reg), ["1.0.0", "1.1.0", "1.2.0", "2.0.0", "junk"])
        self.assertTrue(reg.asked[0][0].startswith("https://example.test/v2/me/app/tags/list"))
        self.assertTrue(any(u.startswith("https://auth.example.test/token?service=registry&scope=repository") for u, _ in reg.asked))

    def test_a_registry_that_cannot_be_asked_gives_none_not_a_crash(self):
        def down(url, headers):
            raise urllib.error.URLError("no internet")
        self.assertIsNone(versions.tags("jellyfin/jellyfin:10.10.7", down))

        def no_token(url, headers):
            raise urllib.error.HTTPError(url, 401, "no", {"WWW-Authenticate": 'Bearer realm="http://plain.example.test/token"'}, io.BytesIO())
        self.assertIsNone(versions.tags("jellyfin/jellyfin:10.10.7", no_token))  # a token is only fetched over https


class State(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp(prefix="hl-versions-")
        self.addCleanup(shutil.rmtree, self.d, ignore_errors=True)
        self.now = 1_800_000_000

    def test_a_check_counts_for_a_week_and_each_version_is_said_once(self):
        reg = Registry(["10.10.7", "10.10.9", "16.4", "16.10", "19.0"], per=10)
        versions.check_all(self.d, [JELLY, PG], reg, clock=lambda: self.now)
        self.assertEqual(versions.available(self.d, [JELLY, PG]), {"media": {"newest": "10.10.9", "major": None}, "db": {"newest": "16.10", "major": "19.0"}})
        lines = versions.news(self.d, [JELLY, PG])
        self.assertEqual(lines[0], "Media server 10.10.9 is out (you have 10.10.7). Move to it with: homelab apps custom update media")
        self.assertIn("A bigger jump, 19.0, is out too. Read its release notes first", lines[1])
        self.assertEqual(versions.news(self.d, [JELLY, PG]), [])  # once
        asked = len(reg.asked)
        versions.check_all(self.d, [JELLY, PG], reg, clock=lambda: self.now + 86400)
        self.assertEqual(len(reg.asked), asked)  # a day later nothing is asked again
        reg.tags.append("10.10.10")
        versions.check_all(self.d, [JELLY, PG], reg, clock=lambda: self.now + 7 * 86400)
        self.assertEqual(versions.news(self.d, [JELLY, PG]), ["Media server 10.10.10 is out (you have 10.10.7). Move to it with: homelab apps custom update media"])

    def test_a_failed_check_keeps_what_was_known_and_a_new_pin_starts_fresh(self):
        versions.check_all(self.d, [JELLY], Registry(["10.10.9"]), clock=lambda: self.now)

        def down(url, headers):
            raise urllib.error.URLError("no internet")
        versions.check_all(self.d, [JELLY], down, force=True)
        self.assertEqual(versions.available(self.d, [JELLY])["media"]["newest"], "10.10.9")
        self.assertEqual(versions.available(self.d, [{**JELLY, "image": "jellyfin/jellyfin:10.10.9"}]), {})  # you moved: the old news is gone


class CommandLine(Base):
    def setUp(self):
        super().setUp()
        custom.add(self.data, JELLY)
        custom.add(self.data, PG)

    def go(self, *argv):
        self.lines.clear()
        return cli.main(list(argv), self.ctx)

    def test_check_says_what_is_new_and_update_moves_to_it_keeping_the_data(self):
        reg = Registry(["10.10.9", "16.10", "19.0"], per=10)
        with mock.patch.object(versions, "_get", reg):
            self.assertEqual(self.go("apps", "custom", "check"), 0)
        self.assertIn("Media server 10.10.9 is out (you have 10.10.7)", self.say())
        self.assertIn("A bigger jump, 19.0", self.say())
        self.assertEqual(self.go("apps", "custom", "update", "media"), 0, self.say())
        self.assertEqual(custom.get(self.data, "media")["image"], "jellyfin/jellyfin:10.10.9")
        self.assertIn('image: "jellyfin/jellyfin:10.10.9"', open(custom.compose_path(self.data, "media")).read())
        self.assertIn("homelab-custom-media", self.fake.calls[-1])
        self.assertIn("Its data folder stays", self.say())
        self.assertEqual(self.go("apps", "custom", "update", "db", "19.0"), 0)  # a bigger jump only when you name it
        self.assertEqual(custom.get(self.data, "db")["image"], "postgres:19.0")

    def test_a_version_that_will_not_start_goes_back(self):
        self.fake.up_rc = 1
        self.assertEqual(self.go("apps", "custom", "update", "media", "10.11.0"), 1)
        self.assertIn("is back on 10.10.7", self.say())
        self.assertEqual(custom.get(self.data, "media")["image"], "jellyfin/jellyfin:10.10.7")
        self.assertIn('image: "jellyfin/jellyfin:10.10.7"', open(custom.compose_path(self.data, "media")).read())

    def test_nothing_known_unknown_apps_and_bad_versions(self):
        self.assertEqual(self.go("apps", "custom", "update", "media"), 0)
        self.assertIn("newest version known", self.say())
        self.assertEqual(self.go("apps", "custom", "update", "nope"), 2)
        self.assertEqual(self.go("apps", "custom", "update", "media", "latest"), 2)
        self.assertEqual(self.go("apps", "custom", "update", "media", "1.0;rm"), 2)
        self.assertEqual(self.fake.calls, [])


class Dashboard(unittest.TestCase):
    def test_the_catalog_and_the_morning_recap_say_so(self):
        from harness import load_bot
        bot = load_bot()
        custom.add(bot.DATA, JELLY)
        self.addCleanup(lambda: [os.remove(os.path.join(bot.DATA, f)) for f in (custom.FILE, versions.FILE) if os.path.exists(os.path.join(bot.DATA, f))])
        json.dump({"media": {"current": "10.10.7", "newest": "10.10.9", "major": None, "checked": 1}}, open(os.path.join(bot.DATA, versions.FILE), "w"))
        from modules import briefing as brief, server
        app = next(a for a in server.catalog()["apps"] if a["id"] == "media")
        self.assertEqual((app["newer"], app["current"]), ("10.10.9", "10.10.7"))
        with mock.patch.object(brief, "backup_line", lambda: "ok"):
            _, html, _ = brief.build_briefing(recap=True)
        self.assertIn("Media server 10.10.9 is out", html)


if __name__ == "__main__":
    unittest.main()
