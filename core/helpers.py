"""Small helpers every module shares: web calls, a safe wrapper, a timed cache, and the one clock (in the user's timezone)."""
import html
import json
import re
import threading
import time
from datetime import datetime
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

TZ = ZoneInfo("UTC")
_on_error = lambda e: None


def configure(tz=None, on_error=None):
    """The app calls this once at start: tz is the user's timezone, on_error hears every error safe() swallows."""
    global TZ, _on_error
    if tz is not None:
        TZ = tz
    if on_error is not None:
        _on_error = on_error


def now():
    return datetime.now(TZ)


def http(url, data=None, timeout=30, headers=None, raw=False, method=None, binary=False):
    body = data if isinstance(data, bytes) else json.dumps(data).encode() if data is not None else None
    h = {"User-Agent": "homelab-bot/2.0", **({"Content-Type": "application/json"} if body and not isinstance(data, bytes) else {}), **(headers or {})}
    with urlopen(Request(url, body, h, method=method), timeout=timeout) as r:
        b = r.read()
        return b if binary else b.decode("utf-8", "replace") if raw else json.loads(b)


esc = lambda s: html.escape(str(s), quote=False)
strip_tags = lambda s: re.sub(r"<[^>]+>", "", s)


def cached(seconds):
    def wrap(fn):
        store, lock = {}, threading.Lock()
        def inner(*a):
            with lock:
                hit = store.get(a)
                if hit and time.time() - hit[1] < seconds:
                    return hit[0]
            v = fn(*a)
            with lock:
                store[a] = (v, time.time())
            return v
        inner.clear = store.clear
        return inner
    return wrap


def safe(fn, default=None):
    try:
        return fn()
    except Exception as e:
        _on_error(e)
        return default


def t12(d, ampm=True):
    """9:30 PM, or 9 PM on the hour."""
    return (f"{d:%-I}" if d.minute == 0 else f"{d:%-I:%M}") + (f" {d:%p}" if ampm else "")


def t12_range(a, b=None):
    """9–10 AM, 11:30 AM–1 PM."""
    if not b:
        return t12(a)
    return f"{t12(a, a.strftime('%p') != b.strftime('%p'))}–{t12(b)}"
