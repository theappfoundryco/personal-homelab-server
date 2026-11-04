import os, tempfile, unittest

import harness  # noqa: F401
from core import store as S


class StoreTests(unittest.TestCase):
    def setUp(self):
        self.s = S.Store(tempfile.mkdtemp())

    def test_roundtrip_and_missing(self):
        self.s.write("notes/a.json", {"x": [1, 2]})
        self.assertEqual(self.s.read("notes/a.json"), {"x": [1, 2]})
        self.assertEqual(self.s.read("nope.json", "d"), "d")

    def test_no_temp_file_left(self):
        self.s.write("a.json", {})
        self.assertEqual(os.listdir(self.s.base), ["a.json"])

    def test_broken_file_gives_default(self):
        with open(self.s.path("bad.json"), "w") as f:
            f.write("{oops")
        self.assertEqual(self.s.read("bad.json", []), [])

    def test_fresh_folder_is_version_1(self):
        self.assertEqual(self.s.version(), 1)


class MigrateTests(unittest.TestCase):
    def setUp(self):
        self.s = S.Store(tempfile.mkdtemp())
        self.s.write("gym.json", {"days": []})
        self.msgs = []

    def test_applies_in_order_and_records_version(self):
        def two(st): st.write("gym.json", {"days": [], "units": "kg"})
        def three(st): st.write("gym.json", {**st.read("gym.json"), "v3": True})
        self.assertEqual(S.migrate(self.s, {3: three, 2: two}, self.msgs.append), 3)
        self.assertEqual(self.s.read("gym.json"), {"days": [], "units": "kg", "v3": True})
        self.assertEqual(self.s.version(), 3)
        self.assertEqual(S.migrate(self.s, {3: three, 2: two}), 3)  # nothing left to do

    def test_failure_restores_everything(self):
        def two(st): st.write("gym.json", {"days": ["changed"]})
        def three(st): raise RuntimeError("boom")
        self.assertEqual(S.migrate(self.s, {2: two, 3: three}, self.msgs.append), 1)
        self.assertEqual(self.s.read("gym.json"), {"days": []})
        self.assertEqual(self.s.version(), 1)
        self.assertIn("put back as they were", self.msgs[-1])

    def test_snapshot_is_kept(self):
        S.migrate(self.s, {2: lambda st: st.write("gym.json", {})})
        self.assertEqual(S.read_json(self.s.path("backups", "before-v2", "gym.json")), {"days": []})


if __name__ == "__main__":
    unittest.main()
