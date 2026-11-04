import json, os, tempfile, threading, unittest
from http.server import BaseHTTPRequestHandler, HTTPServer

import harness  # noqa: F401
from core import llm

SEEN = []


class Fake(BaseHTTPRequestHandler):
    def log_message(self, *a): pass

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        SEEN.append((self.path, body))
        out = {"response": "hi", "prompt_eval_count": 7, "eval_count": 3} if self.path == "/api/generate" else {"embeddings": [[1, 2]]}
        self._send(out)

    def do_GET(self):
        self._send({"models": []})

    def _send(self, out):
        b = json.dumps(out).encode()
        self.send_response(200); self.send_header("Content-Length", str(len(b))); self.end_headers(); self.wfile.write(b)


class LLMTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.srv = HTTPServer(("127.0.0.1", 0), Fake)
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()
        cls.url = f"http://127.0.0.1:{cls.srv.server_address[1]}"

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()

    def test_generate_counts_tokens(self):
        path = os.path.join(tempfile.mkdtemp(), "u.json")
        u = llm.Usage(path, today=lambda: "2026-11-03")
        o = llm.Ollama(self.url, u)
        self.assertEqual(o.generate("m", "hello", kind="Chat")["response"], "hi")
        o.generate("m", "again", kind="Chat")
        self.assertEqual(json.load(open(path)), {"2026-11-03": {"Chat": {"in": 14, "out": 6, "calls": 2}}})

    def test_warm_and_unload_send_keep_alive(self):
        o = llm.Ollama(self.url)
        o.warm("m"); o.unload("m"); o.warm("e", embed=True)
        self.assertEqual([b.get("keep_alive") for p, b in SEEN[-3:]], [-1, 0, -1])
        self.assertEqual(o.embed("e", ["x"]), [[1, 2]])

    def test_down_gives_a_helpful_message(self):
        o = llm.Ollama("http://127.0.0.1:1")
        with self.assertRaises(llm.LLMUnavailable) as c:
            o.generate("m", "x")
        self.assertIn("Start Ollama", str(c.exception))
        ok, msg = o.available()
        self.assertFalse(ok)
        self.assertIn("Can't reach Ollama", msg)
        self.assertTrue(llm.Ollama(self.url).available()[0])

    def test_url_order(self):
        os.environ.pop("OLLAMA_URL", None)
        self.assertEqual(llm.base_url(), llm.DEFAULT_URL)
        self.assertEqual(llm.base_url(lambda k: "http://box:11434/"), "http://box:11434")
        os.environ["OLLAMA_URL"] = "http://env:1"
        self.assertEqual(llm.base_url(lambda k: "http://box:11434"), "http://env:1")
        os.environ.pop("OLLAMA_URL")


if __name__ == "__main__":
    unittest.main()
