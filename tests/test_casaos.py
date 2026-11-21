"""Apps from the CasaOS store: what is taken from its compose file, what is refused and why, what is left out (and said), and the command line."""
import json
import shutil
import tempfile
import unittest
import urllib.error
from unittest import mock

import yaml

import harness  # noqa: F401  (puts core on the path)
from core import casaos, cli, custom
from test_cli import Base

MEDIA = """
name: jellyfin
services:
  jellyfin:
    image: linuxserver/jellyfin:10.10.7
    devices: [/dev/dri:/dev/dri]
    environment: {PGID: $PGID, PUID: $PUID, TZ: $TZ}
    network_mode: bridge
    ports:
      - {target: 8096, published: "8097", protocol: tcp}
      - {target: 7359, published: "7359", protocol: udp}
      - {target: 8920, published: "8921", protocol: tcp}
    restart: unless-stopped
    volumes:
      - {type: bind, source: /DATA/AppData/$AppID/config, target: /config}
      - {type: bind, source: /DATA/AppData/$AppID/cache, target: /cache}
      - {type: bind, source: /DATA/Media, target: /Media}
x-casaos:
  main: jellyfin
  port_map: "8097"
  category: Media
  title: {en_us: Jellyfin, zh_cn: Jellyfin}
"""
VAULT = """
services:
  twofauth:
    image: 2fauth/2fauth:6.1.3
    environment: {APP_KEY: SomeRandomStringOf32CharsExactly, APP_NAME: 2FAuth}
    command: php artisan serve --port 8000
    ports: ["8000:8000"]
    volumes: ["/DATA/AppData/$AppID:/2fauth"]
x-casaos: {port_map: "8000", title: {en_us: 2FAuth}, category: Utilities}
"""


def store(files, names=None):
    """A pretend store: raw files by app name, and the listing."""
    def fetch(url, timeout=20):
        if url == casaos.LISTING:
            return json.dumps([{"name": n, "type": "dir"} for n in (names or files)] + [{"name": "README.md", "type": "file"}])
        name = url.split("/Apps/")[1].split("/")[0]
        if name not in files:
            raise urllib.error.HTTPError(url, 404, "Not Found", {}, None)
        return files[name]
    return fetch


def spec(text, **kw):
    return casaos.spec(yaml.safe_load(text), uid=1001, gid=1002, tags_of=kw.pop("tags_of", lambda image: ["1.0", "2.4.1", "2.5.0-rc1", "latest"]), **kw)


class Reading(unittest.TestCase):
    def test_a_media_app_keeps_its_own_data_and_says_what_was_left_out(self):
        s, notes = spec(MEDIA)
        self.assertEqual({k: s[k] for k in ("id", "title", "image", "port", "inside", "keep", "more", "group")},
                         {"id": "jellyfin", "title": "Jellyfin", "image": "linuxserver/jellyfin:10.10.7", "port": 8097, "inside": 8096,
                          "keep": "/config", "more": ["/cache"], "group": "apps"})
        self.assertEqual(s["env"], {"PGID": "1002", "PUID": "1001"})  # your own user; TZ comes from the time zone setting
        text = " ".join(notes)
        self.assertIn("Not opened: 7359, 8921", text)
        self.assertIn("not connected: /Media", text)
        self.assertIn("Hardware devices", text)

    def test_a_fixed_password_in_the_store_becomes_a_random_one_of_the_same_length(self):
        s, notes = spec(VAULT)
        self.assertEqual(s["id"], "app-2fauth")  # a name must start with a letter
        self.assertEqual(len(s["env"]["APP_KEY"]), 32)
        self.assertNotEqual(s["env"]["APP_KEY"], "SomeRandomStringOf32CharsExactly")
        self.assertEqual(s["env"]["APP_NAME"], "2FAuth")
        self.assertEqual(s["command"], ["php", "artisan", "serve", "--port", "8000"])
        self.assertEqual(s["group"], "tools")
        self.assertIn("random one was made", " ".join(notes))

    def test_more_power_than_an_added_app_gets_is_refused_with_the_reason(self):
        one = "services:\n  a:\n    image: x/y:1.2\n    ports: ['9000:9000']\n"
        cases = [(one + "    privileged: true\n", "privileged"), (one + "    network_mode: host\n", "network_mode host"),
                 (one + "    cap_add: [NET_ADMIN]\n", "cap add"), (one + "    pid: host\n", "pid"),
                 (one + "    volumes: ['/var/run/docker.sock:/var/run/docker.sock']\n", "Docker socket"),
                 (one + "  b:\n    image: x/z:1.0\n", "2 containers"), (one + "    sysctls: {a: 1}\n", "sysctls"),
                 (one + "    environment: {URL: $HOST_IP}\n", "fills in"), ("services:\n  a:\n    image: x/y:1.2\n", "which port"),
                 ("services:\n  grafana:\n    image: grafana/grafana:12.0.0\n    ports: ['3000:3000']\nx-casaos: {title: {en_us: Grafana}}\n", "homelab apps add monitoring")]
        for text, word in cases:
            s, why = spec(text)
            self.assertIsNone(s, text)
            self.assertIn(word, why, text)

    def test_latest_is_pinned_to_the_newest_plain_version_or_refused(self):
        s, _ = spec("services:\n  a:\n    image: x/y:latest\n    ports: ['9000:9000']\n")
        self.assertEqual(s["image"], "x/y:2.4.1")  # not the release candidate
        s, why = spec("services:\n  a:\n    image: x/y\n    ports: ['9000:9000']\n", tags_of=lambda image: None)
        self.assertIsNone(s)
        self.assertIn("no version", why)

    def test_what_is_taken_writes_a_compose_file_with_no_extra_powers(self):
        d = tempfile.mkdtemp(prefix="hl-casaos-")
        self.addCleanup(shutil.rmtree, d, ignore_errors=True)
        s, _ = spec(VAULT)
        app, why = custom.check(d, s)
        self.assertIsNone(why)
        doc = yaml.safe_load(custom.compose_text(app))
        svc = doc["services"]["app-2fauth"]
        self.assertEqual(svc["command"], ["php", "artisan", "serve", "--port", "8000"])
        self.assertEqual(svc["ports"], ["${HL_BIND:-127.0.0.1}:8000:8000"])
        self.assertEqual(svc["environment"]["APP_NAME"], "2FAuth")
        for word in ("privileged", "network_mode", "cap_add", "devices"):
            self.assertNotIn(word, svc)
        s, _ = spec(MEDIA)
        app, _ = custom.check(d, s)
        vols = yaml.safe_load(custom.compose_text(app))["services"]["jellyfin"]["volumes"]
        self.assertEqual(vols, ["homelab-custom-jellyfin:/config", "homelab-custom-jellyfin-2:/cache"])  # the first keeps the name it always had

    def test_settings_with_a_dollar_stay_literal(self):
        d = tempfile.mkdtemp(prefix="hl-casaos-")
        self.addCleanup(shutil.rmtree, d, ignore_errors=True)
        app, why = custom.check(d, {"title": "Tool", "image": "x/y:1.2", "port": 9000, "env": {"PASS": "a$b"}, "command": ["echo", "$HOME"]})
        self.assertIsNone(why)
        svc = yaml.safe_load(custom.compose_text(app))["services"]["tool"]
        self.assertEqual(svc["environment"]["PASS"], "a$$b")  # compose reads $$ as one $
        self.assertEqual(svc["command"], ["echo", "$$HOME"])
        for bad in ({"env": {"BAD KEY": "x"}}, {"env": {"A": "x\ny"}}, {"command": "rm -rf /"}, {"user": "root; rm"}, {"more": ["/a", "/a"], "keep": "/b"}):
            self.assertIsNotNone(custom.check(d, {"title": "Tool", "image": "x/y:1.2", "port": 9000, "keep": "/data", **bad})[1], bad)


class Finding(unittest.TestCase):
    def test_names_are_found_exactly_first_then_by_part(self):
        names = ["Jellyfin", "Jellyseerr", "Memos"]
        self.assertEqual(casaos.find("jellyfin", names), ["Jellyfin"])
        self.assertEqual(casaos.find("jelly", names), ["Jellyfin", "Jellyseerr"])
        self.assertIsNone(casaos.apps(lambda url, timeout=20: (_ for _ in ()).throw(urllib.error.URLError("offline"))))
        self.assertEqual(casaos.prepare("jelly", fetch=store({"Jellyfin": MEDIA, "Jellyseerr": MEDIA}))[2], ["Jellyfin", "Jellyseerr"])
        self.assertIn("no app called", casaos.prepare("plex", fetch=store({"Jellyfin": MEDIA}))[1])


class CommandLine(Base):
    def go(self, *argv):
        self.lines.clear()
        return cli.main(list(argv), self.ctx)

    def test_search_then_add_asks_first_and_starts_it(self):
        fetch = store({"Jellyfin": MEDIA, "2FAuth": VAULT}, names=["2FAuth", "Jellyfin", "Memos"])
        real = cli.store_cmd
        with mock.patch.object(cli, "store_cmd", lambda c, a, p=None: real(c, a, p, fetch=fetch)), mock.patch.object(cli, "_port_free", lambda p: True):
            self.assertEqual(self.go("apps", "store", "jelly"), 0)
            self.assertIn("1 of 3 apps in the CasaOS store match jelly", self.say())
            self.assertEqual(self.go("apps", "store", "add", "jellyfin"), 1)  # no answer means no
            self.assertEqual(custom.ids(self.data), [])
            self.fake.answers = ["y"]
            self.assertEqual(self.go("apps", "store", "add", "jellyfin", "--port", "8123"), 0, self.say())
        self.assertIn("Not opened: 7359, 8921", self.say())
        self.assertEqual(custom.get(self.data, "jellyfin")["port"], 8123)
        self.assertIn("homelab-custom-jellyfin", self.fake.calls[-1])
        self.assertIn("Jellyfin started on port 8123", self.say())


if __name__ == "__main__":
    unittest.main()
