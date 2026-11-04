"""Profiles: each kind of machine gets the profile and the warnings it should."""
import unittest

import harness  # noqa: F401
from core.hardware import profiles
from test_hardware import PI, NVIDIA, M2, LAPTOP, hardware


def hw(**kw):
    base = {"os": "linux", "arch": "amd64", "ram_gb": 16, "disk_free_gb": 200, "gpu": {"kind": "none", "name": None, "vram_gb": None}}
    return {**base, **kw}


class Profiles(unittest.TestCase):
    def test_the_four_machines(self):
        got = {n: profiles.choose(hardware.probe(**m)) for n, m in (("pi", PI), ("nvidia", NVIDIA), ("m2", M2), ("laptop", LAPTOP))}
        self.assertEqual(got, {"pi": "tiny", "nvidia": "large", "m2": "medium", "laptop": "small"})

    def test_edges(self):
        self.assertEqual(profiles.choose(hw(ram_gb=None)), "tiny")  # unreadable: the safe choice
        self.assertEqual(profiles.choose(hw(ram_gb=32)), "large")
        self.assertEqual(profiles.choose(hw(ram_gb=16, gpu={"kind": "nvidia", "vram_gb": 4})), "medium")
        self.assertEqual(profiles.choose(hw(ram_gb=8, gpu={"kind": "apple", "vram_gb": None})), "small")

    def test_every_model_a_profile_names_is_listed(self):
        d = profiles.load()
        for n, p in d["profiles"].items():
            for role in ("chat", "journal", "embed"):
                self.assertTrue(p[role] is None or p[role] in d["models"], f"{n}.{role}")
        self.assertEqual({r["profile"] for r in d["rules"]}, set(d["profiles"]))

    def test_models_match_what_the_config_defaults_use(self):
        import yaml, os
        cfg = yaml.safe_load(open(os.path.join(harness.ROOT, "stack", "config.example.yaml")))["models"]
        known = profiles.load()["models"]
        for role in ("chat", "embed", "journal"):
            self.assertIn(cfg[role], known, role)

    def test_a_model_that_does_not_fit_is_flagged_with_numbers(self):
        w = profiles.check_model("gemma4:26b", hw(ram_gb=8, disk_free_gb=10))
        self.assertEqual(len(w), 2)
        self.assertIn("22 GB", w[0])
        self.assertIn("8 GB", w[0])
        self.assertEqual(profiles.check_model("qwen3.5:4b", hw()), [])
        self.assertEqual(profiles.check_model("some-custom-model", hw()), [])

    def test_recommend(self):
        r = profiles.recommend(hardware.probe(**NVIDIA))
        self.assertEqual((r["profile"], r["gpu_override"], r["whisper"]), ("large", "nvidia", "medium"))
        self.assertEqual([m["role"] for m in r["models"]], ["chat", "journal", "embed"])
        self.assertGreater(r["download_gb"], 20)
        t = profiles.recommend(hardware.probe(**PI))
        self.assertEqual((t["models"], t["download_gb"], t["lite_monitoring"]), ([], 0, True))
        self.assertIsNone(profiles.recommend(hardware.probe(**M2))["gpu_override"])


class Render(unittest.TestCase):
    def test_text_for_every_profile_has_no_em_dash_and_names_a_next_step(self):
        for m in (PI, NVIDIA, M2, LAPTOP):
            h = hardware.probe(**m)
            text = hardware.render({"summary": hardware.describe(h), "recommendation": profiles.recommend(h)})
            self.assertIn("Profile:", text)
            self.assertNotIn("\u2014", text)
        pi = hardware.render({"summary": "x", "recommendation": profiles.recommend(hardware.probe(**PI))})
        self.assertIn("another machine's Ollama", pi)
        blind = hardware.probe(system="Linux", release="6", machine="x86_64", sh=lambda c: None, read=lambda p: None, which=lambda n: None, disk_path="/")
        text = hardware.render({"hardware": blind, "summary": hardware.describe(blind), "recommendation": profiles.recommend(blind)})
        self.assertIn("Memory could not be read", text)


if __name__ == "__main__":
    unittest.main()
