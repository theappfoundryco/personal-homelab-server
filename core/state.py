"""Shared state (notes, reminders, sent alerts) and the once-only claims for scheduled jobs."""
import json, os, threading, time

from core.store import write_json

DATA = os.environ.get("HL_DATA", "/data")
STATE_FILE = f"{DATA}/state.json"
_lock = threading.RLock()


def load_state():
    try:
        return json.load(open(STATE_FILE))
    except Exception:
        return {}


state = {"notes": [], "reminders": [], "goals": [], "sent": {}, "history": [], **load_state()}


def save():
    with _lock:
        write_json(STATE_FILE, state, indent=1)


def once(key, ttl_days=14):
    """True the first time a key is seen (for alerts that must only fire once)."""
    with _lock:
        if key in state["sent"]:
            return False
        state["sent"][key] = time.time()
        cutoff = time.time() - ttl_days * 86400
        state["sent"] = {k: v for k, v in state["sent"].items() if v > cutoff}
        save()
        return True


BOOT_AT = time.time()  # when this run of the bot started


def claim(key, ttl_days=14):
    """once() for scheduled jobs: True if the job hasn't finished and isn't already running in this run of the bot.
    finish(key) marks it done, so a job that a power cut or crash stopped halfway runs again after the restart."""
    with _lock:
        done, run = state.setdefault("jobs_done", {}), state.setdefault("jobs_run", {})
        if key in done or key in state["sent"] or run.get(key, 0) >= BOOT_AT:  # "sent": the same job from before 2026-10-29
            return False
        run[key] = time.time()
        cut = time.time() - ttl_days * 86400
        state["jobs_done"] = {k: v for k, v in done.items() if v > cut}
        state["jobs_run"] = {k: v for k, v in run.items() if v > cut}
        save()
        return True


def finish(key):
    with _lock:
        state.setdefault("jobs_run", {}).pop(key, None)
        state.setdefault("jobs_done", {})[key] = time.time()
        save()


def claimed_run(key, fn):
    """Runs a claimed job and marks it done (a failed run counts as done; only a cut-off one runs again)."""
    try:
        return fn()
    finally:
        finish(key)
