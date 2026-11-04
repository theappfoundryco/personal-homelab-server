"""Where data lives: power-cut-safe JSON files, plus a migrations runner that snapshots first and rolls back on failure.
Version 1 is today's file shapes, so wrapping them changes nothing."""
import json
import os
import shutil
import threading

VERSION_FILE = "schema.json"


def write_json(path, data, **kw):
    """Power-cut safe: a temp file, flushed to disk, then swapped in. A cut leaves the old file or the new one, never half of one."""
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        json.dump(data, f, **kw)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)
    fd = os.open(os.path.dirname(path) or ".", os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def read_json(path, default=None):
    """The file's contents, or default if it is missing or unreadable (never raises)."""
    try:
        with open(path) as f:
            return json.load(f)
    except Exception:
        return default


class Store:
    """A data folder. Modules ask it for their files by name; it creates the folder and serialises writes."""

    def __init__(self, base):
        self.base = base
        self.lock = threading.RLock()
        os.makedirs(base, exist_ok=True)

    def path(self, *parts):
        return os.path.join(self.base, *parts)

    def read(self, name, default=None):
        return read_json(self.path(name), default)

    def write(self, name, data, **kw):
        with self.lock:
            os.makedirs(os.path.dirname(self.path(name)), exist_ok=True)
            write_json(self.path(name), data, **kw)

    def version(self):
        return (self.read(VERSION_FILE, {}) or {}).get("version", 1)


def migrate(store, migrations, log=print):
    """Run each pending migration in order. migrations is {to_version: fn(store)}, applied when the folder is below that version.
    A snapshot of the data folder is taken first; if any step fails the snapshot is restored and the old version stays in place."""
    pending = sorted(v for v in migrations if v > store.version())
    if not pending:
        return store.version()
    snap = store.path("backups", f"before-v{pending[0]}")
    keep = [n for n in os.listdir(store.base) if n != "backups"]
    shutil.rmtree(snap, ignore_errors=True)
    os.makedirs(snap)
    for n in keep:
        src = store.path(n)
        shutil.copytree(src, os.path.join(snap, n)) if os.path.isdir(src) else shutil.copy2(src, snap)
    done = store.version()
    try:
        for v in pending:
            migrations[v](store)
            store.write(VERSION_FILE, {"version": v})
            done = v
            log(f"data updated to version {v}")
    except Exception as e:
        for n in os.listdir(store.base):
            if n != "backups":
                p = store.path(n)
                shutil.rmtree(p) if os.path.isdir(p) else os.remove(p)
        for n in os.listdir(snap):
            src = os.path.join(snap, n)
            shutil.copytree(src, store.path(n)) if os.path.isdir(src) else shutil.copy2(src, store.path(n))
        log(f"data update to version {v} failed ({e}); your files were put back as they were. Nothing is lost. Please report this.")
        return store.version()
    return done
