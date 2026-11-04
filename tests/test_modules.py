import os, shutil, tempfile, threading, unittest
from http.server import ThreadingHTTPServer

import harness
from core import capabilities, config, http_api, registry, scheduler, store
from core.app import App


class TemplateTests(unittest.TestCase):
    def build(self, switches=None):
        root = tempfile.mkdtemp()
        shutil.copytree(os.path.join(harness.ROOT, "modules", "_template"), os.path.join(root, "hello"))
        p = os.path.join(root, "hello", "module.yaml")
        text = open(p).read().replace("name: _template", "name: hello")
        open(p, "w").write(text)
        mods = registry.discover(root, log=lambda m: None)
        order, notes = registry.plan(mods, switches)
        router = http_api.Router()
        app = App(config.Config({"owner": {"name": "Sam"}}), router, scheduler.Scheduler("UTC"), capabilities.Capabilities(), store.Store(tempfile.mkdtemp()))
        app.caps.register("ollama", "Ollama", lambda: False, "Start Ollama.", ttl=0)
        started = [n for n in order if registry.start(mods[n], app, log=lambda m: None)]
        return app, started, notes

    def test_template_is_a_working_module(self):
        app, started, _ = self.build()
        self.assertEqual(started, ["hello"])
        self.assertEqual(app.router.find("GET", "/hello")(None), {"message": "Hello, Sam!"})
        self.assertEqual(app.scheduler.describe(), ["Hello: every day at 8:00 AM"])
        self.assertEqual(app.intents["hello"]("hi"), "Hello! Start Ollama.")

    def test_module_can_be_switched_off(self):
        app, started, notes = self.build({"hello": False})
        self.assertEqual(started, [])
        self.assertIn("switched off", notes["hello"])

    def test_a_broken_module_does_not_stop_the_rest(self):
        root = tempfile.mkdtemp()
        for n, code in (("bad", "def register(app): raise RuntimeError('no')"), ("good", "def register(app): app.intents['g'] = 1")):
            os.makedirs(os.path.join(root, n))
            open(os.path.join(root, n, "module.yaml"), "w").write(f"name: {n}\n")
            open(os.path.join(root, n, "__init__.py"), "w").write(code)
        mods = registry.discover(root)
        app = App(config.Config(), http_api.Router(), scheduler.Scheduler("UTC"), capabilities.Capabilities(), store.Store(tempfile.mkdtemp()))
        msgs = []
        self.assertEqual([registry.start(mods[n], app, msgs.append) for n in ("bad", "good")], [False, True])
        self.assertIn("could not start", msgs[0])
        self.assertEqual(app.intents, {"g": 1})


if __name__ == "__main__":
    unittest.main()
