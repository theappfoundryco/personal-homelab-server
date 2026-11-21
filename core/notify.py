"""Alerts that reach you where you are: Telegram, an ntfy topic, or 100+ other services through an Apprise API server.

The assistant's own pushes (alerts, reminders, update reports) go through Notifier.send(); chat replies stay on Telegram.
Every channel is optional and none can stop the others: a failed send is logged and the rest still go. Standard library only."""
import html
import json
import re
from urllib.error import HTTPError
from urllib.parse import urlsplit
from urllib.request import Request, urlopen

TOPIC = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
LIMIT = 4000  # ntfy keeps messages under 4096 bytes; longer ones arrive as an attachment


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


def problems(conf):
    """What is wrong with the notify: section, in plain words (empty when it is fine)."""
    conf = conf if isinstance(conf, dict) else {}
    out = []
    if conf.get("ntfy") and not ntfy_parts(conf["ntfy"]):
        out.append("notify.ntfy should be a topic address like https://ntfy.sh/your-topic (letters, digits, - and _ in the topic).")
    if conf.get("apprise") and urlsplit(str(conf["apprise"])).scheme not in ("http", "https"):
        out.append("notify.apprise should be an Apprise API address like http://apprise:8000/notify/homelab.")
    if conf.get("telegram") is False and not conf.get("ntfy") and not conf.get("apprise"):
        out.append("notify.telegram is false and no ntfy or Apprise address is set, so alerts go nowhere.")
    return out


class Notifier:
    def __init__(self, conf=None, telegram=None, telegram_ready=lambda: False, ntfy_token="", post=_post, log=print, timeout=8):
        """telegram: send(text, buttons, keyboard, silent), used while telegram_ready() is true and notify.telegram is not false.
        ntfy_token: an access token for a private ntfy server (HL_NTFY_TOKEN in .env). It is never logged."""
        conf = conf if isinstance(conf, dict) else {}
        self.ntfy = ntfy_parts(conf.get("ntfy")) if conf.get("ntfy") else None
        apprise = str(conf.get("apprise") or "").strip()
        self.apprise = apprise if urlsplit(apprise).scheme in ("http", "https") else ""
        self.use_telegram = conf.get("telegram") is not False
        self.telegram, self.telegram_ready, self.token = telegram, telegram_ready, ntfy_token
        self.post, self.log, self.timeout = post, log, timeout
        self.last = {}  # channel -> "" when the last send went through, else the error

    def extra(self):
        """The channels besides Telegram that are set up."""
        return [n for n, on in (("ntfy", self.ntfy), ("apprise", self.apprise)) if on]

    def send(self, text, buttons=None, silent=False):
        """Send to every channel that is set up. -> {channel: True/False}. Never raises."""
        done = {}
        if self.use_telegram and self.telegram and self.telegram_ready():
            done["telegram"] = self._try("telegram", lambda: self.telegram(text, buttons, None, silent))
        if self.ntfy or self.apprise:
            title, body = split_title(text)
            if self.ntfy:
                done["ntfy"] = self._try("ntfy", lambda: self._ntfy(title, body, links(buttons), silent))
            if self.apprise:
                done["apprise"] = self._try("apprise", lambda: self._apprise(title, body, links(buttons)))
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

    def _ntfy(self, title, body, urls, silent):
        base, topic = self.ntfy
        msg = {"topic": topic, "message": body[:LIMIT] or title, "priority": 2 if silent else 3}
        if title and body:
            msg["title"] = title
        if urls:
            msg["click"] = urls[0][1]
            msg["actions"] = [{"action": "view", "label": label[:40], "url": url} for label, url in urls[:3]]
        self.post(base + "/", msg, {"Authorization": f"Bearer {self.token}"} if self.token else {}, self.timeout)

    def _apprise(self, title, body, urls):
        more = "\n".join(f"{label}: {url}" for label, url in urls)
        self.post(self.apprise, {"title": title, "body": "\n\n".join(p for p in (body, more) if p), "type": "info", "format": "text"}, {}, self.timeout)

    def status(self):
        """For the capability: (ok, detail). Not ok only when a channel is set up and its last send failed."""
        bad = [f"The last alert to {n} did not go through ({self.last[n]})." for n in self.extra() if self.last.get(n)]
        return (not bad, " ".join(bad))
