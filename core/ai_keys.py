"""Your own API keys for a cloud AI (Claude or OpenAI), kept in the data folder and readable only by you, plus the model lists.

A key is never sent anywhere except to its own provider, never logged, and never returned to the dashboard (only whether one is set)."""
import json
import os
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

PROVIDERS = {"claude": "Claude (Anthropic)", "openai": "OpenAI"}
LEGACY = {"claude": "/secrets/anthropic.secret.txt"}  # where the key lived before it could be set from the dashboard


def path(data_dir, provider):
    return os.path.join(data_dir, "keys", f"{provider}.key")


def get(data_dir, provider):
    """The key, or "" when none is set."""
    for p in (path(data_dir, provider), LEGACY.get(provider)):
        try:
            if p:
                with open(p) as f:
                    k = f.read().strip()
                if k:
                    return k
        except OSError:
            pass
    return ""


def save(data_dir, provider, key):
    d = os.path.join(data_dir, "keys")
    os.makedirs(d, mode=0o700, exist_ok=True)
    p = path(data_dir, provider)
    if not key:
        try:
            os.remove(p)
        except OSError:
            pass
        return
    fd = os.open(p + ".tmp", os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        f.write(key.strip())
    os.replace(p + ".tmp", p)


def _get_json(url, headers, timeout=10):
    with urlopen(Request(url, headers=headers), timeout=timeout) as r:
        return json.loads(r.read())


def models(provider, key, fetch=_get_json):
    """(ok, [model ids] or the reason). Also how a new key is checked: a wrong key cannot list models."""
    try:
        if provider == "claude":
            d = fetch("https://api.anthropic.com/v1/models?limit=100", {"x-api-key": key, "anthropic-version": "2023-06-01"})
            ids = [m["id"] for m in d.get("data", []) if m.get("id")]
        elif provider == "openai":
            d = fetch("https://api.openai.com/v1/models", {"Authorization": f"Bearer {key}"})
            ids = sorted((m["id"] for m in d.get("data", []) if m.get("id", "").startswith(("gpt-", "o")) and not any(w in m["id"] for w in ("audio", "realtime", "tts", "transcribe", "image", "search"))), reverse=True)
        else:
            return False, "Unknown provider."
    except HTTPError as e:
        return False, "That key was not accepted. Check that you copied all of it." if e.code in (401, 403) else f"The provider answered with an error ({e.code}). Try again in a minute."
    except (URLError, OSError, ValueError):
        return False, "Could not reach the provider. Check the internet connection."
    return (True, ids) if ids else (False, "The key works, but no models are available to it.")


def suggest(provider, ids):
    """A small, cheap model that is good enough for news, from what the key can use."""
    order = {"claude": ("haiku", "sonnet"), "openai": ("mini", "nano")}.get(provider, ())
    for w in order:
        for i in ids:
            if w in i:
                return i
    return ids[0] if ids else ""
