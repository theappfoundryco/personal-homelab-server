"""Changes to saved data that a new version needs. Each file is named NNNN_what.py and has run(data_dir).
They run once, in order, and are recorded in migrations.json in the data folder. A migration must be safe to run twice."""
import importlib
import os
import re

from core import store

LEDGER = "migrations.json"
NAME = re.compile(r"^(\d{4})_[a-z0-9_]+\.py$")


class MigrationError(Exception):
    pass


def available():
    here = os.path.dirname(os.path.abspath(__file__))
    return sorted(f[:-3] for f in os.listdir(here) if NAME.match(f))


def done(data_dir):
    raw = store.read_json(os.path.join(data_dir, LEDGER), {}) or {}
    return list(raw.get("done", [])) if isinstance(raw, dict) else []


def pending(data_dir):
    seen = set(done(data_dir))
    return [n for n in available() if n not in seen]


def run_all(data_dir, log=print):
    """Runs what has not run yet. Stops at the first failure and keeps what already finished. Returns the names that ran."""
    os.makedirs(data_dir, exist_ok=True)
    ran = []
    for name in pending(data_dir):
        try:
            importlib.import_module(f"core.migrations.{name}").run(data_dir)
        except Exception as e:
            raise MigrationError(f"{name} failed: {e}") from e
        store.write_json(os.path.join(data_dir, LEDGER), {"done": done(data_dir) + [name]})
        log(f"migrated {name}")
        ran.append(name)
    return ran
