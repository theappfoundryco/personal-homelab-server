"""Imports the bot against fake demo data, a frozen clock and no network, so tests are repeatable.

The bot is a module with state at import time, so there is one instance per test process. Tests that write
should run after the ones that only read (see test_golden_api.py).
"""
import itertools
import json
import os
import socket
import sys
import tempfile
import threading
import time as _time
import uuid as _uuid
from datetime import datetime, timezone
from http.server import ThreadingHTTPServer
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "demo"))
sys.path.insert(0, os.path.join(ROOT, "stack", "telegram"))

FROZEN = datetime(2026, 11, 3, 10, 0, 0, tzinfo=timezone.utc)
_net_calls = []


def _block_network():
    real = socket.socket.connect

    def guard(self, addr, *a, **k):
        host = addr[0] if isinstance(addr, tuple) else addr
        if host not in ("127.0.0.1", "::1", "localhost"):
            _net_calls.append(str(host))
            raise OSError("network is blocked in tests")
        return real(self, addr, *a, **k)

    socket.socket.connect = guard


class _Time:
    """The time module, except time() stands still."""

    def __getattr__(self, k):
        return getattr(_time, k)

    def time(self):
        return FROZEN.timestamp()


class _Uuid:
    """uuid4() hands out 0001, 0002, ... so ids in recorded replies are stable."""
    n = itertools.count(1)

    def uuid4(self):
        return _uuid.UUID(int=next(self.n) << 96)

    def __getattr__(self, k):
        return getattr(_uuid, k)


def load_bot():
    """The bot module on a fresh copy of the demo data."""
    if "core.boot" in sys.modules:
        return sys.modules["core.boot"]
    import generate
    data = tempfile.mkdtemp(prefix="hl-demo-")
    generate.build(data, FROZEN.date(), seed=42)
    os.environ.update(TG_TOKEN="test-token", TG_CHAT="1", HL_DATA=data, HL_CONFIG=os.path.join(ROOT, "tests", "config.test.yaml"))
    _block_network()
    from core import boot as bot

    class FakeDT(datetime):
        @classmethod
        def now(cls, tz=None):
            return FROZEN.astimezone(tz) if tz else FROZEN.replace(tzinfo=None)

    bot.datetime, bot.time, bot.uuid = FakeDT, _Time(), _Uuid()
    from core import helpers
    helpers.datetime, helpers.time = FakeDT, bot.time  # modules moved out of bot.py read the clock from here
    for name, mod in list(sys.modules.items()):
        if name.startswith(("modules.", "core.")) and getattr(mod, "__file__", None):
            for attr, fake in (("datetime", FakeDT), ("time", bot.time), ("uuid", bot.uuid)):
                if hasattr(mod, attr):
                    setattr(mod, attr, fake)
    bot.now = lambda: FROZEN.astimezone(bot.TZ)
    return bot


def start_api(bot):
    srv = ThreadingHTTPServer(("127.0.0.1", 0), bot.Api)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, f"http://127.0.0.1:{srv.server_address[1]}"


def call(base, method, path, body=None):
    req = Request(base + path, data=None if body is None else json.dumps(body).encode(), method=method,
                  headers={"Content-Type": "application/json"})
    try:
        with urlopen(req, timeout=30) as r:
            return r.status, json.loads(r.read() or b"{}")
    except Exception as e:
        if hasattr(e, "code"):
            return e.code, json.loads(e.read() or b"{}")
        raise
