import os, tempfile, unittest

import harness  # noqa: F401
from core import config, registry


def tree(**modules):
    root = tempfile.mkdtemp()
    for name, text in modules.items():
        os.makedirs(os.path.join(root, name))
        with open(os.path.join(root, name, "module.yaml"), "w") as f:
            f.write(text)
    return root


def mods(**specs):
    return registry.discover(tree(**{n: f"name: {n}\n{t}" for n, t in specs.items()}), log=lambda m: None)


class DiscoverTests(unittest.TestCase):
    def test_finds_modules_and_skips_bad_ones(self):
        msgs = []
        root = tree(gym="name: gym\ntitle: Gym\n", bad="title: no name\n", wrong="name: other\n", _template="name: _template\n")
        found = registry.discover(root, log=msgs.append)
        self.assertEqual(list(found), ["gym"])
        self.assertEqual(len(msgs), 2)
        self.assertIn("needs a name", msgs[0] + msgs[1])

    def test_dashboard_declaration_is_read(self):
        m = mods(a="dashboard: {home_cards: [x, y]}\n", b="")
        self.assertEqual(m["a"].dashboard, {"home_cards": ["x", "y"]})
        self.assertEqual(m["b"].dashboard, {})

    def test_missing_folder_is_fine(self):
        self.assertEqual(registry.discover("/nope"), {})

    def test_bad_platform_is_reported(self):
        msgs = []
        registry.discover(tree(x="name: x\nplatforms: [amiga]\n"), log=msgs.append)
        self.assertIn("platforms should be from", msgs[0])


class PlanTests(unittest.TestCase):
    def test_dependencies_start_first(self):
        m = mods(a="requires: [b]\n", b="requires: [c]\n", c="")
        order, notes = registry.plan(m)
        self.assertEqual(order, ["c", "b", "a"])
        self.assertEqual(notes, {})

    def test_switching_off_a_dependency_turns_off_dependents(self):
        m = mods(a="requires: [b]\n", b="")
        order, notes = registry.plan(m, {"b": False})
        self.assertEqual(order, [])
        self.assertIn("needs b", notes["a"])

    def test_default_off_module_needs_switching_on(self):
        m = mods(a="default: false\n")
        self.assertEqual(registry.plan(m)[0], [])
        self.assertEqual(registry.plan(m, {"a": True})[0], ["a"])

    def test_missing_requirement(self):
        order, notes = registry.plan(mods(a="requires: [ghost]\n"))
        self.assertEqual(order, [])
        self.assertIn("not installed", notes["a"])

    def test_cycle_is_caught_not_looped(self):
        m = mods(a="requires: [b]\n", b="requires: [a]\n", c="")
        self.assertEqual(set(registry.find_cycle(m)), {"a", "b"})
        order, notes = registry.plan(m)
        self.assertEqual(order, ["c"])
        self.assertIn("loop", notes["a"])

    def test_platform_gating_explains(self):
        m = mods(net="title: Network fallback\nplatforms: [linux]\n", gym="")
        order, notes = registry.plan(m, platform="mac")
        self.assertEqual(order, ["gym"])
        self.assertIn("hidden", notes["net"])
        self.assertEqual(registry.plan(m, platform="linux")[0], ["gym", "net"])

    def test_unknown_switch_is_reported(self):
        msgs = []
        registry.plan(mods(a=""), {"typo": False}, log=msgs.append)
        self.assertIn("no module called 'typo'", msgs[0])

    def test_modules_section_is_checked_by_config(self):
        self.assertEqual(config.check({"modules": {"gym": False}}), [])
        self.assertTrue(config.check({"modules": {"gym": "no"}}))


if __name__ == "__main__":
    unittest.main()
