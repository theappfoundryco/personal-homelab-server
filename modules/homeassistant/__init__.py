"""Home Assistant: your smart home from Telegram, and a line about it in the morning brief.

Set homeassistant.url in config.yaml and a long-lived access token as HL_HA_TOKEN in .env (Home Assistant: your profile, Security, Long-lived access tokens).
Without them this module stays quiet: no sentences are taken, nothing is added to the brief, and the doctor says how to connect it.

Every change asks Yes or No first, on a button. Only lights, switches, fans, covers, locks and scenes can be changed; scripts and automations
can do anything, so they are never run from here. Unlocking a lock or opening a garage door or gate also needs homeassistant.allow_unlock: true.
Standard library only: GET /api/states and POST /api/services/<domain>/<service>."""
import json
import os
import re
import secrets
import time
import urllib.error
import urllib.request

from core import host
from core.helpers import esc

CHANGE = {  # domain -> {what you say: the service}
    "light": {"on": "turn_on", "off": "turn_off"}, "switch": {"on": "turn_on", "off": "turn_off"}, "fan": {"on": "turn_on", "off": "turn_off"},
    "input_boolean": {"on": "turn_on", "off": "turn_off"}, "cover": {"open": "open_cover", "close": "close_cover"},
    "lock": {"lock": "lock", "unlock": "unlock"}, "scene": {"on": "turn_on"},
}
RISKY_COVERS = {"garage", "gate", "door"}  # opening these, or unlocking any lock, also needs allow_unlock
OPENINGS = {"door", "window", "garage_door", "opening"}
WORDS = re.compile(r"[a-z0-9]+")
FILL = {"the", "a", "my", "in", "on", "off", "of", "please", "all", "light", "lights", "lamp", "lamps", "room", "turn", "switch", "put", "is", "are", "it"}
PENDING = {}  # button key -> (domain, service or, for "which one?", the word you said, entity id, name, asked at)
WAIT = 600  # a Yes button works for 10 minutes


class HA:
    """The Home Assistant REST API: a GET of every state, and a POST to one service. Short timeouts; errors are plain sentences."""
    def __init__(self, url, token, opener=None, timeout=8):
        self.url, self.token, self.timeout = (url or "").rstrip("/"), token or "", timeout
        self.opener = opener or urllib.request.urlopen

    @property
    def ready(self):
        return bool(self.url and self.token)

    def _call(self, path, body=None):
        req = urllib.request.Request(self.url + path, data=json.dumps(body).encode() if body is not None else None, method="POST" if body is not None else "GET",
                                     headers={"Authorization": f"Bearer {self.token}", "Content-Type": "application/json"})
        with self.opener(req, timeout=self.timeout) as r:
            return json.load(r)

    def check(self):
        try:
            self._call("/api/")
            return True, ""
        except urllib.error.HTTPError as e:
            return False, "Home Assistant refused the token (check HL_HA_TOKEN)." if e.code == 401 else f"Home Assistant answered {e.code}."
        except (OSError, ValueError) as e:
            return False, f"Home Assistant cannot be reached at {self.url} ({getattr(e, 'reason', e)})."

    def states(self):
        return [s for s in self._call("/api/states") if isinstance(s, dict) and "." in str(s.get("entity_id", ""))]

    def do(self, domain, service, entity_id):
        return self._call(f"/api/services/{domain}/{service}", {"entity_id": entity_id})


def name(s):
    return str((s.get("attributes") or {}).get("friendly_name") or s["entity_id"].split(".", 1)[1].replace("_", " ")).strip()


def match(phrase, states, domains):
    """The entities whose names fit the words you used, best first. 'the kitchen lights' finds 'Kitchen ceiling light'; a tie returns all of them."""
    want = [w for w in WORDS.findall(phrase.lower()) if w not in FILL]
    if not want:
        return []
    scored = []
    for s in states:
        if s["entity_id"].split(".")[0] not in domains or s.get("state") == "unavailable":
            continue
        have = set(WORDS.findall(name(s).lower())) | set(WORDS.findall(s["entity_id"].split(".", 1)[1].replace("_", " ")))
        hits = sum(1 for w in want if w in have or w.rstrip("s") in have)
        if hits == len(want):
            scored.append((len(have), s))  # fewer extra words is a closer name
    scored.sort(key=lambda x: x[0])
    return [s for n, s in scored if n == scored[0][0]] if scored else []


def summary(states):
    """One line for the brief and /home: open doors and windows, unlocked locks, lights on, and temperatures."""
    opened = [name(s) for s in states if s["entity_id"].startswith("binary_sensor.") and s.get("state") == "on"
              and (s.get("attributes") or {}).get("device_class") in OPENINGS]
    unlocked = [name(s) for s in states if s["entity_id"].startswith("lock.") and s.get("state") == "unlocked"]
    lights = [name(s) for s in states if s["entity_id"].startswith("light.") and s.get("state") == "on"]
    temps = []
    for s in states:
        a = s.get("attributes") or {}
        if s["entity_id"].startswith("climate.") and a.get("current_temperature") is not None:
            temps.append(f"{name(s)} {a['current_temperature']:g}°" + (f" (set to {a['temperature']:g}°)" if isinstance(a.get("temperature"), (int, float)) else ""))
    parts = []
    if opened:
        parts.append(f"{len(opened)} open: {', '.join(opened[:4])}{' and more' if len(opened) > 4 else ''}")
    if unlocked:
        parts.append(f"Unlocked: {', '.join(unlocked[:3])}")
    parts.append(f"{len(lights)} light{'s' if len(lights) != 1 else ''} on" if lights else "All lights off")
    parts += temps[:3]
    return " • ".join(parts)


def register(app):
    host.need(globals(), "B", "edit", "send")
    url = app.config.get("homeassistant.url", "") or ""
    allow_unlock = bool(app.config.get("homeassistant.allow_unlock", False))
    ha = HA(url, os.environ.get("HL_HA_TOKEN", ""))
    app.caps.register("homeassistant", "Home Assistant", ha.check, "Check homeassistant.url in config.yaml and HL_HA_TOKEN in .env.", ttl=60,
                      off=lambda: "" if ha.ready else "Home Assistant is not connected. Add homeassistant.url to config.yaml and a long-lived token as HL_HA_TOKEN in .env.")

    def states():
        return ha.states() if ha.ready and app.caps.ok("homeassistant") else None

    def ask(domain, word, s):
        service = CHANGE[domain][word]
        title = name(s)
        risky = (domain, word) == ("lock", "unlock") or ((domain, word) == ("cover", "open") and (s.get("attributes") or {}).get("device_class") in RISKY_COVERS)
        if risky and not allow_unlock:
            send(f"🔒 I don't unlock or open {esc(title)} from Telegram. To allow it, set homeassistant.allow_unlock: true in config.yaml.")
            return True
        now = time.time()
        for k in [k for k, v in PENDING.items() if now - v[4] > WAIT]:
            PENDING.pop(k, None)
        key = secrets.token_hex(4)
        PENDING[key] = (domain, service, s["entity_id"], title, now)
        verb = {"turn_on": "Turn on", "turn_off": "Turn off", "open_cover": "Open", "close_cover": "Close", "lock": "Lock", "unlock": "Unlock"}[service]
        if domain == "scene":
            verb = "Start the scene"
        send(f"🏠 {verb} <b>{esc(title)}</b>? It is {esc(s.get('state', 'unknown'))} now.", [[B(f"Yes, {verb.lower()}", f"ha!:{key}"), B("Cancel", "noop")]])
        return True

    def which(found, word, domain):
        """More than one fits: a button for each (up to 6), each asking Yes or No in turn."""
        rows = []
        for s in found[:6]:
            key = secrets.token_hex(4)
            PENDING[key] = (domain, word, s["entity_id"], name(s), time.time())
            rows.append([B(name(s), f"ha?:{key}")])
        send("🏠 Which one?", rows + [[B("Cancel", "noop")]])
        return True

    def hear(text, t):
        """Sentences about your home. Returns False for anything else, so the rest of the bot answers it."""
        if not ha.ready:
            return False
        if t in ("/home", "home", "my home", "home status", "house"):
            st = states()
            send(f"🏠 {esc(summary(st))}" if st is not None else f"🏠 {esc(app.caps.missing(['homeassistant'])[0])}")
            return True
        m = (re.match(r"^(?:turn|switch|put)\s+(on|off)\s+(.+)$", t) or re.match(r"^(?:turn|switch|put)\s+(.+?)\s+(on|off)$", t)
             or re.match(r"^(lock|unlock|open|close)\s+(.+)$", t) or re.match(r"^(?:start|activate|run)\s+(?:the\s+)?(.+?)\s+scene$", t))
        st_m = re.match(r"^(?:is|are)\s+(.+?)\s+(on|off|open|closed|locked|unlocked)\s*\??$", t)
        temp_m = re.match(r"^(?:what'?s|what is|how)\s+(?:the\s+)?(?:temperature|temp|warm|cold|hot)\b(?:\s+is it)?\s+(?:in|at)\s+(.+?)\s*\??$", t)
        if not (m or st_m or temp_m):
            return False
        st = states()
        if st is None:
            return False  # not connected right now: let the rest of the bot answer
        if m:
            g = m.groups()
            if len(g) == 1:
                word, what, domains = "on", g[0], ["scene"]
            elif g[0] in ("on", "off", "lock", "unlock", "open", "close"):
                word, what = g
            else:
                what, word = g
            if len(g) == 2:
                domains = [d for d, verbs in CHANGE.items() if word in verbs and d != "scene"]
            found = match(what, st, domains)
            if not found:
                return False
            domain = found[0]["entity_id"].split(".")[0]
            return ask(domain, word, found[0]) if len(found) == 1 else which(found, word, domain)
        if st_m:
            found = match(st_m[1], st, ["light", "switch", "fan", "cover", "lock", "binary_sensor", "input_boolean"])
            if not found:
                return False
            send("🏠 " + " • ".join(f"{esc(name(s))}: <b>{esc(s.get('state'))}</b>" for s in found[:4]))
            return True
        found = [s for s in match(temp_m[1] + " temperature", st, ["sensor"]) if (s.get("attributes") or {}).get("device_class") == "temperature"]
        found += [s for s in match(temp_m[1], st, ["climate"]) if (s.get("attributes") or {}).get("current_temperature") is not None]
        if not found:
            return False
        s = found[0]
        a = s.get("attributes") or {}
        value = f"{a['current_temperature']:g}°" if s["entity_id"].startswith("climate.") else f"{s.get('state')}{a.get('unit_of_measurement', '')}"
        send(f"🌡️ {esc(name(s))}: <b>{esc(value)}</b>")
        return True

    def tap(data, msg):
        key = data.split(":", 1)[1]
        p = PENDING.pop(key, None)
        if not p or time.time() - p[4] > WAIT:
            return edit(msg, "That question is old. Ask again.")
        domain, service, entity_id, title, _ = p
        if data.startswith("ha?:"):  # picked one of several: now the Yes or No (service holds the word you said)
            return ask(domain, service, {"entity_id": entity_id, "attributes": {"friendly_name": title}, "state": next((s.get("state") for s in (states() or []) if s["entity_id"] == entity_id), "unknown")})
        try:
            ha.do(domain, service, entity_id)
        except (OSError, ValueError) as e:
            return edit(msg, f"❌ Home Assistant did not do it: {esc(str(getattr(e, 'reason', e)))}")
        done = {"turn_on": "is on", "turn_off": "is off", "open_cover": "is opening", "close_cover": "is closing", "lock": "is locking", "unlock": "is unlocking"}[service]
        return edit(msg, f"✅ {esc(title)} {done if domain != 'scene' else 'started'}.")

    def brief():
        st = states() if ha.ready else None
        return [("🏠", "HOME", [summary(st)])] if st else []

    app.text_hooks.append(hear)
    app.taps["ha!:"] = tap
    app.taps["ha?:"] = tap
    app.brief_lines.append(brief)

    @app.router.get("/homeassistant")
    def home(req):
        if not ha.ready:
            return {"connected": False, "msg": "Not connected. Add homeassistant.url to config.yaml and HL_HA_TOKEN to .env."}
        st = states()
        return {"connected": st is not None, "line": summary(st) if st is not None else "", "msg": "" if st is not None else app.caps.missing(["homeassistant"])[0]}
