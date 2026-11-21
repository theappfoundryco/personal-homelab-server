"""Alerts that reach you where you are: Telegram, an ntfy topic, or 100+ other services through an Apprise API server.

The assistant's own pushes (alerts, reminders, update reports) go through Notifier.send(); chat replies stay on Telegram.
Every channel is optional and none can stop the others: a failed send is logged and the rest still go. Standard library only."""
import html
import json
import os
import re
import secrets
from urllib.error import HTTPError
from urllib.parse import urlsplit
from urllib.request import Request, urlopen

TOPIC = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
LIMIT = 4000  # ntfy keeps messages under 4096 bytes; longer ones arrive as an attachment
LOCAL = "http://ntfy"  # the optional ntfy app (homelab apps add ntfy), as the assistant reaches it inside Docker
LOCAL_PORT = 8090  # where you open it on this machine (stack/compose.yaml)
TOPIC_FILE = "ntfy-topic.json"


def local_topic(data_dir):
    """The private topic the ntfy app gets alerts on: made once, at random, and kept in the data folder.
    On a server without logins, knowing the topic is what lets someone read it, so it is long and never in a log."""
    path = os.path.join(data_dir, TOPIC_FILE)
    try:
        with open(path) as f:
            topic = json.load(f).get("topic", "")
        if TOPIC.match(topic):
            return topic
    except (OSError, ValueError, AttributeError):
        pass
    topic = "homelab-" + secrets.token_hex(12)
    os.makedirs(data_dir, exist_ok=True)
    with open(path + ".tmp", "w") as f:
        json.dump({"topic": topic}, f)
    os.replace(path + ".tmp", path)
    return topic


def _post(url, payload, headers, timeout):
    req = Request(url, json.dumps(payload).encode(), {"Content-Type": "application/json", "User-Agent": "homelab-bot/2.0", **headers})
    with urlopen(req, timeout=timeout) as r:
        r.read()


def plain(text):
    """Telegram's HTML as plain text: tags dropped, &amp; and friends turned back into characters."""
    return html.unescape(re.sub(r"<[^>]+>", "", text or "")).strip()


def split_title(text):
    """A short first line becomes the title ("⏰ Reminder" over "Call the dentist"). One line stays the message."""
    first, _, rest = plain(text).partition("\n")
    if rest.strip() and len(first) <= 80:
        return first.strip(), rest.strip()
    return "", plain(text)


def links(buttons):
    """The buttons that open a web page, as (label, url). Buttons that answer the bot only work in Telegram, so they are left out."""
    return [(b["text"], b["url"]) for row in buttons or [] for b in row if isinstance(b, dict) and b.get("url")]


def ntfy_parts(url):
    """https://ntfy.sh/my-topic -> ("https://ntfy.sh", "my-topic"), or None when it is not a topic address."""
    u = urlsplit((url or "").strip())
    base, _, topic = u.path.rstrip("/").rpartition("/")
    if u.scheme not in ("http", "https") or not u.netloc or u.query or not TOPIC.match(topic):
        return None
    return f"{u.scheme}://{u.netloc}{base}", topic


def problems(conf, local=False):
    """What is wrong with the notify: section, in plain words (empty when it is fine). local: the ntfy app is installed here."""
    conf = conf if isinstance(conf, dict) else {}
    out = []
    if conf.get("ntfy") and not ntfy_parts(conf["ntfy"]):
        out.append("notify.ntfy should be a topic address like https://ntfy.sh/your-topic (letters, digits, - and _ in the topic).")
    if conf.get("apprise") and urlsplit(str(conf["apprise"])).scheme not in ("http", "https"):
        out.append("notify.apprise should be an Apprise API address like http://apprise:8000/notify/homelab.")
    if conf.get("telegram") is False and not conf.get("ntfy") and not conf.get("apprise") and not local:
        out.append("notify.telegram is false and no ntfy or Apprise address is set (and the ntfy app is not installed), so alerts go nowhere.")
    return out


class Notifier:
    def __init__(self, conf=None, telegram=None, telegram_ready=lambda: False, ntfy_token="", post=_post, log=print, timeout=8, local=lambda: None):
        """telegram: send(text, buttons, keyboard, silent), used while telegram_ready() is true and notify.telegram is not false.
        ntfy_token: an access token for a private ntfy server (HL_NTFY_TOKEN in .env). It is never logged.
        local: the ntfy app's topic address while that app is installed, else None. Used only when notify.ntfy is not set."""
        conf = conf if isinstance(conf, dict) else {}
        self._ntfy = ntfy_parts(conf.get("ntfy")) if conf.get("ntfy") else None
        self.local = local
        apprise = str(conf.get("apprise") or "").strip()
        self.apprise = apprise if urlsplit(apprise).scheme in ("http", "https") else ""
        self.use_telegram = conf.get("telegram") is not False
        self.telegram, self.telegram_ready, self.token = telegram, telegram_ready, ntfy_token
        self.post, self.log, self.timeout = post, log, timeout
        self.last = {}  # channel -> "" when the last send went through, else the error

    @property
    def ntfy(self):
        """(server, topic): the address in config.yaml, or else the ntfy app on this machine while it is installed."""
        if self._ntfy:
            return self._ntfy
        try:
            return ntfy_parts(self.local())
        except Exception:
            return None

    def source(self):
        """Where ntfy alerts go, in words: "config" (notify.ntfy), "app" (the ntfy app here) or "" (nowhere)."""
        return "config" if self._ntfy else "app" if self.ntfy else ""

    def extra(self):
        """The channels besides Telegram that are set up."""
        return [n for n, on in (("ntfy", self.ntfy), ("apprise", self.apprise)) if on]

    def send(self, text, buttons=None, silent=False):
        """Send to every channel that is set up. -> {channel: True/False}. Never raises."""
        done = {}
        if self.use_telegram and self.telegram and self.telegram_ready():
            done["telegram"] = self._try("telegram", lambda: self.telegram(text, buttons, None, silent))
        ntfy = self.ntfy
        if ntfy or self.apprise:
            title, body = split_title(text)
            if ntfy:
                done["ntfy"] = self._try("ntfy", lambda: self._send_ntfy(title, body, links(buttons), silent))
            if self.apprise:
                done["apprise"] = self._try("apprise", lambda: self._send_apprise(title, body, links(buttons)))
        return done

    def _try(self, name, fn):
        try:
            fn()
            self.last[name] = ""
            return True
        except Exception as e:
            why = str(e) if isinstance(e, HTTPError) else str(getattr(e, "reason", "") or e)  # "HTTP Error 403: Forbidden", "Name or service not known"
            self.last[name] = (re.sub(r"^\[Errno [^\]]+\]\s*", "", why) or type(e).__name__)[:200]
            self.log(f"notify {name}: {self.last[name]}")
            return False

    def _send_ntfy(self, title, body, urls, silent):
        base, topic = self.ntfy
        token = self.token if self._ntfy else ""  # the token is for the server named in config.yaml, never the app here
        msg = {"topic": topic, "message": body[:LIMIT] or title, "priority": 2 if silent else 3}
        if title and body:
            msg["title"] = title
        if urls:
            msg["click"] = urls[0][1]
            msg["actions"] = [{"action": "view", "label": label[:40], "url": url} for label, url in urls[:3]]
        self.post(base + "/", msg, {"Authorization": f"Bearer {token}"} if token else {}, self.timeout)

    def _send_apprise(self, title, body, urls):
        more = "\n".join(f"{label}: {url}" for label, url in urls)
        self.post(self.apprise, {"title": title, "body": "\n\n".join(p for p in (body, more) if p), "type": "info", "format": "text"}, {}, self.timeout)

    def status(self):
        """For the capability: (ok, detail). Not ok only when a channel is set up and its last send failed."""
        bad = [f"The last alert to {n} did not go through ({self.last[n]})." for n in self.extra() if self.last.get(n)]
        return (not bad, " ".join(bad))
