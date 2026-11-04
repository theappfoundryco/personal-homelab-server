"""Turns a hardware probe into a profile and a list of suggestions, from profiles.yaml. It only advises; nothing here installs or changes anything."""
import os

import yaml

HERE = os.path.dirname(os.path.abspath(__file__))
_cache = {}


def load():
    if "data" not in _cache:
        with open(os.path.join(HERE, "profiles.yaml")) as f:
            _cache["data"] = yaml.safe_load(f)
    return _cache["data"]


def _matches(rule, hw):
    ram, vram, gpu = hw.get("ram_gb") or 0, (hw.get("gpu") or {}).get("vram_gb") or 0, (hw.get("gpu") or {}).get("kind")
    return (ram >= rule.get("min_ram", 0) and vram >= rule.get("min_vram", 0)
            and (not rule.get("gpu") or gpu in rule["gpu"]) and (not rule.get("min_ram") or hw.get("ram_gb") is not None))


def choose(hw):
    """The profile name for this machine: tiny, small, medium or large."""
    return next(r["profile"] for r in load()["rules"] if _matches(r, hw))


def check_model(name, hw):
    """Warnings if a model will not fit: [] when it fits or when we cannot tell. Plain words, with the numbers."""
    spec = load()["models"].get(name)
    if not spec:
        return []
    out = []
    ram = hw.get("ram_gb")
    if ram and spec["ram_gb"] > ram:
        out.append(f"{name} needs about {spec['ram_gb']} GB of memory and this machine has {ram} GB.")
    free = hw.get("disk_free_gb")
    if free is not None and spec["size_gb"] > free:
        out.append(f"{name} is a {spec['size_gb']} GB download and only {free} GB of disk is free.")
    return out


def recommend(hw):
    """{profile, title, about, models: [{role, name, size_gb, warnings}], whisper, metrics_days, lite_monitoring, gpu_override, download_gb}."""
    name = choose(hw)
    p = load()["profiles"][name]
    models = []
    for role in ("chat", "journal", "embed"):
        if p.get(role):
            spec = load()["models"][p[role]]
            models.append({"role": role, "name": p[role], "size_gb": spec["size_gb"], "warnings": check_model(p[role], hw)})
    gpu = (hw.get("gpu") or {}).get("kind")
    return {"profile": name, "title": p["title"], "about": p["about"], "models": models, "whisper": p["whisper"],
            "metrics_days": p["metrics_days"], "lite_monitoring": p["lite_monitoring"],
            "gpu_override": gpu if gpu in ("nvidia", "amd") and hw.get("os") == "linux" else None,
            "download_gb": round(sum(m["size_gb"] for m in models), 1)}
