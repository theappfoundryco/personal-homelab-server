"""Serve the dashboard against demo data, with no network. Used by the Playwright smoke tests."""
import os, sys, threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.request import Request, urlopen

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
import harness  # noqa: E402

SITE = os.path.join(harness.ROOT, "stack", "landing", "site")
TYPES = {".html": "text/html", ".css": "text/css", ".js": "text/javascript", ".svg": "image/svg+xml", ".png": "image/png", ".webmanifest": "application/json"}


def start():
    """Returns (server, base_url). The bot API runs on the frozen clock, the site is proxied to it under /api/bot/."""
    bot = harness.load_bot()
    _, api = harness.start_api(bot)

    class H(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def _send(self, code, body, ctype="application/json"):
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            if self.command != "HEAD":
                self.wfile.write(body)

        def _handle(self):
            path = self.path
            if path.startswith("/api/bot/"):
                n = int(self.headers.get("Content-Length") or 0)
                req = Request(api + "/" + path[len("/api/bot/"):], data=self.rfile.read(n) if n else None, method=self.command,
                              headers={"Content-Type": "application/json", "X-Settings-Pin": self.headers.get("X-Settings-Pin", "")})  # nginx passes request headers on, so does this
                try:
                    with urlopen(req, timeout=30) as r:
                        return self._send(r.status, r.read())
                except Exception as e:
                    return self._send(getattr(e, "code", 502), e.read() if hasattr(e, "read") else b"{}")
            if path.startswith("/m/"):  # a module's dashboard files
                parts = path.split("?")[0].split("/")
                f = os.path.join(harness.ROOT, "modules", parts[2], "web", *parts[4:]) if len(parts) > 4 and parts[3] == "web" else ""
                if not f or ".." in parts or not os.path.isfile(f):
                    return self._send(404, b"not found", "text/plain")
                with open(f, "rb") as fh:
                    return self._send(200, fh.read(), TYPES.get(os.path.splitext(f)[1], "application/octet-stream"))
            if path.startswith("/api/"):
                return self._send(404, b"{}")  # prometheus, n8n and host files do not exist in the demo
            name = "index.html" if path.split("?")[0] == "/" else path.split("?")[0].lstrip("/")
            f = os.path.join(SITE, name)
            if not os.path.abspath(f).startswith(SITE) or not os.path.isfile(f):
                return self._send(404, b"not found", "text/plain")
            with open(f, "rb") as fh:
                self._send(200, fh.read(), TYPES.get(os.path.splitext(f)[1], "application/octet-stream"))

        do_GET = do_POST = do_HEAD = _handle

    srv = ThreadingHTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, f"http://127.0.0.1:{srv.server_address[1]}"


if __name__ == "__main__":
    s, u = start()
    print(u, flush=True)
    threading.Event().wait()
