"""scripts/check-needs.py: a name that core.host hands to a module is fine, a name nobody defines is caught. Needs ruff (skipped without it)."""
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RUFF = shutil.which("ruff") or (os.path.join(ROOT, ".cache", "venv", "bin", "ruff") if os.path.exists(os.path.join(ROOT, ".cache", "venv", "bin", "ruff")) else None)


@unittest.skipUnless(RUFF, "ruff is not installed")
class CheckNeeds(unittest.TestCase):
    def run_on(self, **files):
        d = tempfile.mkdtemp(prefix="hl-needs-")
        self.addCleanup(shutil.rmtree, d, ignore_errors=True)
        for name, text in files.items():
            with open(os.path.join(d, name + ".py"), "w") as f:
                f.write(text)
        env = {**os.environ, "PATH": os.path.dirname(RUFF) + os.pathsep + os.environ["PATH"]}
        r = subprocess.run([sys.executable, os.path.join(ROOT, "scripts", "check-needs.py"), d], capture_output=True, text=True, env=env, cwd=ROOT)
        return r.returncode, r.stdout + r.stderr

    def test_a_name_listed_in_host_need_is_fine(self):
        rc, out = self.run_on(mod='from core import host\nhost.need(globals(), "send")\n\ndef go():\n    send("hi")\n')
        self.assertEqual(rc, 0, out)

    def test_a_name_in_a_needs_tuple_is_fine(self):
        rc, out = self.run_on(mod='NEEDS = ("send", "state")\n\ndef go():\n    send(state)\n')
        self.assertEqual(rc, 0, out)

    def test_a_name_nobody_provides_is_caught_with_its_place(self):
        rc, out = self.run_on(mod='from core import host\nhost.need(globals(), "send")\n\ndef go():\n    send("hi")\n    sned("typo")\n')
        self.assertEqual(rc, 1)
        self.assertIn("`sned`", out)
        self.assertIn("mod.py:6", out)
        self.assertNotIn("`send`", out)

    def test_a_name_listed_in_another_file_does_not_count(self):
        rc, out = self.run_on(a='from core import host\nhost.need(globals(), "send")\n', b='def go():\n    send("hi")\n')
        self.assertEqual(rc, 1)
        self.assertIn("b.py", out)


if __name__ == "__main__":
    unittest.main()
