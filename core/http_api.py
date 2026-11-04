"""Route registration for the dashboard API. Modules register (method, path, function); the bot's older handler keeps whatever is not registered yet,
so every existing path and payload stays exactly as it was."""
import json
from http.server import BaseHTTPRequestHandler
from urllib.parse import parse_qs, urlparse


HANDLED = object()  # a route returns this after writing its own response (a stream)


class Router:
    def __init__(self, log=print):
        self.routes, self.prefixes, self.log = {}, [], log

    def add(self, method, path, fn):
        """fn(req) returns a JSON-able object, or (object, status). req has .path, .query, .json() and .headers."""
        key = (method.upper(), path)
        if key in self.routes:
            raise ValueError(f"{method} {path} is already registered")
        self.routes[key] = fn
        return fn

    def add_prefix(self, method, prefix, fn):
        """One function for every path starting with prefix (an exact route wins). Used where a module keeps its own sub-paths."""
        self.prefixes.append((method.upper(), prefix, fn))
        return fn

    def get(self, path):
        return lambda fn: self.add("GET", path, fn)

    def post(self, path):
        return lambda fn: self.add("POST", path, fn)

    def find(self, method, path):
        fn = self.routes.get((method.upper(), path))
        if fn:
            return fn
        return next((f for m, p, f in self.prefixes if m == method.upper() and path.startswith(p)), None)


class Request:
    def __init__(self, handler):
        u = urlparse(handler.path)
        self.path, self.query, self.headers = u.path, {k: v[0] for k, v in parse_qs(u.query).items()}, handler.headers
        self.client = handler.client_address[0]  # who is asking (127.0.0.1 for the host's own helpers)
        self._h = handler

    def json(self):
        n = int(self.headers.get("Content-Length") or 0)
        return json.loads(self._h.rfile.read(n) or b"{}") if n else {}


class Handler(BaseHTTPRequestHandler):
    """Base class: reply(), body() and dispatch(). Subclass it, set .router, and call dispatch() first; it returns True if a route answered."""
    router = None
    timeout = 10

    def log_message(self, *a):
        pass

    def reply(self, obj, code=200):
        b = json.dumps(obj, default=str).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(b)))
        self.end_headers()
        self.wfile.write(b)

    def body(self):
        n = int(self.headers.get("Content-Length") or 0)
        return json.loads(self.rfile.read(n) or b"{}") if n else {}

    def dispatch(self, method):
        fn = self.router and self.router.find(method, urlparse(self.path).path)
        if not fn:
            return False
        try:
            out = fn(Request(self))
            if out is HANDLED:
                return True
            obj, code = out if isinstance(out, tuple) else (out, 200)
            self.reply(obj, code)
        except Exception as e:  # a broken route answers with a message; it never takes the server down
            self.router.log(f"{method} {self.path} failed: {e}")
            self.reply({"ok": False, "error": "That didn't work. Check the server log for details."}, 500)
        return True
