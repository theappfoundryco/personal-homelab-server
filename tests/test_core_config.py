import os, tempfile, unittest

import harness  # noqa: F401  (puts the repo root on sys.path)
from core import config


def write(text):
    f = tempfile.NamedTemporaryFile("w", suffix=".yaml", delete=False)
    f.write(text)
    f.close()
    return f.name


class CheckTests(unittest.TestCase):
    def test_example_file_is_clean(self):
        c = config.load(os.path.join(harness.ROOT, "stack", "config.example.yaml"), log=lambda m: None)
        self.assertEqual(c.problems, [])

    def test_bad_time_is_explained(self):
        p = config.check({"schedule": {"briefing": "soon"}})
        self.assertEqual(len(p), 1)
        self.assertIn("schedule.briefing should look like 4:30 AM", p[0])

    def test_bad_timezone_and_typo(self):
        p = config.check({"timezone": "Mars/Base", "owner": {"nmae": "x"}})
        self.assertTrue(any("timezone should look like" in m for m in p))
        self.assertTrue(any("owner.nmae is not a setting" in m for m in p))

    def test_list_entries(self):
        p = config.check({"schedule": {"news_at": ["6:30 AM", "late"]}, "world_clock": [{"label": "X", "tz": "nope"}]})
        self.assertTrue(any("news_at[2]" in m for m in p))
        self.assertTrue(any("world_clock[1].tz" in m for m in p))

    def test_wrong_shape(self):
        self.assertTrue(config.check({"world_clock": "Paris"}))
        self.assertTrue(config.check(["a"]))
        self.assertEqual(config.check({"home": {"lat": 51.5}, "features": {"therapy_recap": False}}), [])


class LoadTests(unittest.TestCase):
    def test_missing_file_gives_defaults(self):
        msgs = []
        c = config.load("/nope/config.yaml", log=msgs.append)
        self.assertEqual(c.get("owner.name", "friend"), "friend")
        self.assertIn("not found", msgs[0])

    def test_broken_yaml_never_raises(self):
        msgs = []
        c = config.load(write("owner:\n  name: [oops\n"), log=msgs.append)
        self.assertEqual(c.get("owner.name", "friend"), "friend")
        self.assertIn("typing mistake", msgs[0])

    def test_values_and_defaults(self):
        c = config.load(write("owner:\n  name: Sam\nschedule:\n  briefing: 6:15 pm\n"), log=lambda m: None)
        self.assertEqual(c.get("owner.name"), "Sam")
        self.assertEqual(c.time("schedule.briefing", (7, 0)), (18, 15))
        self.assertEqual(c.time("schedule.evening_plan", (21, 0)), (21, 0))
        self.assertTrue(c.feature("anything"))

    def test_bad_value_still_loads_with_default_time(self):
        c = config.load(write("schedule:\n  briefing: soon\n"), log=lambda m: None)
        self.assertEqual(len(c.problems), 1)
        self.assertEqual(c.time("schedule.briefing", (7, 0)), (7, 0))


if __name__ == "__main__":
    unittest.main()
