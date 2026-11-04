import threading, unittest
from http.server import ThreadingHTTPServer

import harness
from core import http_api


class H(http_api.Handler):
    router = http_api.Router(log=lambda m: None)

    def do_GET(self):
        if not self.dispatch("GET"):
            self.reply({"legacy": True}, 200)

    def do_POST(self):
        if not self.dispatch("POST"):
            self.reply({"legacy": True}, 200)


@H.router.get("/hello")
def hello(req):
    return {"hi": req.query.get("who", "you")}


@H.router.post("/echo")
def echo(req):
    return {"got": req.json()}, 201


H.router.add_prefix("POST", "/things/", lambda req: {"path": req.path})


@H.router.get("/boom")
def boom(req):
    raise RuntimeError("secret detail")


class ApiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.srv = ThreadingHTTPServer(("127.0.0.1", 0), H)
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()
        cls.base = f"http://127.0.0.1:{cls.srv.server_address[1]}"

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()

    def test_registered_routes_answer(self):
        self.assertEqual(harness.call(self.base, "GET", "/hello?who=Sam"), (200, {"hi": "Sam"}))
        self.assertEqual(harness.call(self.base, "POST", "/echo", {"a": 1}), (201, {"got": {"a": 1}}))

    def test_unregistered_falls_through_to_legacy(self):
        self.assertEqual(harness.call(self.base, "GET", "/old"), (200, {"legacy": True}))

    def test_prefix_routes(self):
        self.assertEqual(harness.call(self.base, "POST", "/things/a/b", {}), (200, {"path": "/things/a/b"}))
        self.assertEqual(harness.call(self.base, "GET", "/things/a"), (200, {"legacy": True}))

    def test_failing_route_hides_details(self):
        code, body = harness.call(self.base, "GET", "/boom")
        self.assertEqual(code, 500)
        self.assertNotIn("secret", str(body))

    def test_duplicate_route_is_refused(self):
        with self.assertRaises(ValueError):
            H.router.add("GET", "/hello", hello)


if __name__ == "__main__":
    unittest.main()
