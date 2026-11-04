"""Talking to Ollama. If it is missing or down the caller gets LLMUnavailable with a message that says how to fix it, never a stack trace."""
import json
import os
import threading
from datetime import datetime
from urllib.error import URLError
from urllib.request import Request, urlopen

from . import store

DEFAULT_URL = "http://ollama:11434"
FIX = "Start Ollama (or run the setup wizard again), or turn the AI features off in config.yaml."


class LLMUnavailable(Exception):
    pass


def base_url(cfg_get=None):
    """OLLAMA_URL in the environment wins, then ollama.url in config.yaml, then the compose service."""
    return (os.environ.get("OLLAMA_URL") or (cfg_get("ollama.url") if cfg_get else None) or DEFAULT_URL).rstrip("/")


class Usage:
    """Tokens in and out per day and kind: {"2026-11-03": {"Chat": {"in": 10, "out": 5, "calls": 1}}}. Same file shape as before."""

    def __init__(self, path, today=lambda: datetime.now().strftime("%Y-%m-%d")):
        self.path, self.today, self.lock = path, today, threading.Lock()
        self.data = store.read_json(path, {}) or {}

    def add(self, kind, tokens_in, tokens_out, usd=0.0):
        if not tokens_in and not tokens_out:
            return
        with self.lock:
            k = self.data.setdefault(self.today(), {}).setdefault(kind, {"in": 0, "out": 0, "calls": 0})
            k["in"], k["out"], k["calls"] = k["in"] + tokens_in, k["out"] + tokens_out, k["calls"] + 1
            if usd:
                k["usd"] = round(k.get("usd", 0) + usd, 6)
            store.write_json(self.path, self.data)


class Ollama:
    def __init__(self, url=None, usage=None, timeout=120):
        self.url, self.usage, self.timeout = url or DEFAULT_URL, usage, timeout

    def call(self, path, body=None, timeout=None):
        req = Request(self.url + path, data=None if body is None else json.dumps(body).encode(), headers={"Content-Type": "application/json"})
        try:
            with urlopen(req, timeout=timeout or self.timeout) as r:
                return json.loads(r.read() or b"{}")
        except (URLError, OSError) as e:
            raise LLMUnavailable(f"Can't reach Ollama at {self.url} ({getattr(e, 'reason', e)}). {FIX}") from e

    def generate(self, model, prompt, kind="Other", **body):
        j = self.call("/api/generate", {"model": model, "prompt": prompt, "stream": False, **body})
        if self.usage:
            self.usage.add(kind, int(j.get("prompt_eval_count") or 0), int(j.get("eval_count") or 0))
        return j

    def embed(self, model, texts, **body):
        return self.call("/api/embed", {"model": model, "input": texts, **body}).get("embeddings", [])

    def loaded(self):
        """Models in memory right now, by name."""
        return {m["name"]: m for m in self.call("/api/ps", timeout=10).get("models", [])}

    def warm(self, model, embed=False):
        """Load a model and keep it in memory until unloaded."""
        if embed:
            self.call("/api/embed", {"model": model, "input": ["warm"], "keep_alive": -1}, timeout=300)
        else:
            self.call("/api/generate", {"model": model, "keep_alive": -1}, timeout=300)

    def unload(self, model):
        self.call("/api/generate", {"model": model, "keep_alive": 0}, timeout=60)

    def available(self):
        """(True, "") if Ollama answers, else (False, plain-English message)."""
        try:
            self.call("/api/ps", timeout=5)
            return True, ""
        except LLMUnavailable as e:
            return False, str(e)
