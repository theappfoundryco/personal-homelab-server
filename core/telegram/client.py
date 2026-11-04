"""Telegram client for one owner: sending (long messages are split), editing, and the owner-only check."""
import json
import re
from urllib.error import HTTPError
from urllib.request import Request, urlopen

LIMIT = 4000
strip_tags = lambda s: re.sub(r"<[^>]+>", "", s)


def split(text, limit=LIMIT):
    """Cut text into messages Telegram accepts, at line breaks where possible. One giant line is cut as plain text."""
    chunks, cur = [], ""
    for line in text.split("\n"):
        if cur and len(cur) + len(line) + 1 > limit:
            chunks.append(cur)
            cur = ""
        cur = f"{cur}\n{line}" if cur else line
        while len(cur) > limit:
            chunks.append(strip_tags(cur)[:limit])
            cur = strip_tags(cur)[limit:]
    return [c for c in chunks + [cur] if c.strip()] or [""]


class Telegram:
    def __init__(self, token, owner, post=None, log=print):
        """post(url, params, timeout) returns parsed JSON; tests pass a fake, the default uses urllib."""
        self.api, self.owner, self.log = f"https://api.telegram.org/bot{token}", owner, log
        self._post = post or self._urlopen
        self.enabled, self._told = bool(token and owner), False  # without both, nothing is sent and the dashboard still works

    @staticmethod
    def _urlopen(url, params, timeout):
        req = Request(url, json.dumps(params).encode(), {"Content-Type": "application/json", "User-Agent": "homelab-bot/2.0"})
        with urlopen(req, timeout=timeout) as r:
            return json.loads(r.read())

    def call(self, method, **params):
        """The result, or None after logging why (a down network or a rejected call never raises)."""
        if not self.enabled:
            if not self._told:
                self._told = True
                self.log("telegram is not set up (no token or chat id): chat is off, the dashboard still works")
            return None
        try:
            return self._post(f"{self.api}/{method}", params, 70)["result"]
        except HTTPError as e:
            msg = e.read().decode()
            if "message is not modified" not in msg:
                self.log(f"telegram {method}: {msg}")
        except Exception as e:
            self.log(f"telegram {method}: {e}")
        return None

    def send(self, text, buttons=None, keyboard=None, silent=False):
        markup = {"inline_keyboard": buttons} if buttons else keyboard
        parts, m = split(text), None
        for i, chunk in enumerate(parts):
            extra = {"reply_markup": markup} if markup and i == len(parts) - 1 else {}
            m = self.call("sendMessage", chat_id=self.owner, text=chunk, parse_mode="HTML", disable_web_page_preview=True,
                          disable_notification=silent, **extra)
        return m

    def edit(self, msg, text, buttons=None):
        if not msg:
            return self.send(text, buttons)
        extra = {"reply_markup": {"inline_keyboard": buttons}} if buttons else {}
        return self.call("editMessageText", chat_id=self.owner, message_id=msg["message_id"], text=text[:LIMIT],
                         parse_mode="HTML", disable_web_page_preview=True, **extra)

    def typing(self, action="typing"):
        self.call("sendChatAction", chat_id=self.owner, action=action)

    def is_owner(self, update):
        """True for the owner's messages and button taps. Anyone else gets a polite no (private chats only) and False."""
        if "callback_query" in update:
            return update["callback_query"]["from"]["id"] == self.owner
        chat = (update.get("message") or {}).get("chat", {})
        if chat.get("id") == self.owner:
            return True
        if chat.get("type") == "private":
            self.call("sendMessage", chat_id=chat.get("id"), text="Sorry, this is a private assistant.")
        return False
