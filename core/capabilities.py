"""What is available right now (Ollama, Telegram, calendar, internet ...), with a plain-English fix when it is not.
Modules declare the capabilities they can use under `optional:` and call degrade() so a missing one gives a message, never a crash."""
import socket
import threading
import time


class Capability:
    def __init__(self, name, title, check, fix, ttl=30, off=None):
        """check() returns True/False (or (ok, detail)). fix says what the user can do when it is missing.
        off(), when given, returns a sentence when this was left out on purpose (an app you did not choose, a link you did not add):
        it is still not available, but it is a choice, not something broken, so the needs card and the doctor do not flag it."""
        self.name, self.title, self.check, self.fix, self.ttl, self.off = name, title, check, fix, ttl, off
        self._at, self._val = 0.0, None

    def status(self, clock=time.time):
        if self._val is None or clock() - self._at > self.ttl:
            try:
                r = self.check()
                ok, detail = r if isinstance(r, tuple) else (bool(r), "")
            except Exception as e:
                ok, detail = False, str(e)
            self._val, self._at = {"name": self.name, "title": self.title, "ok": ok, "message": "" if ok else (detail + " " + self.fix).strip(),
                         "reason": "" if ok else detail, "fix": "" if ok else self.fix}, clock()
        if not self._val["ok"] and self.off:
            why = self.off()
            if why:
                return {**self._val, "off": True, "message": why, "reason": why, "fix": why}
        return self._val


class Capabilities:
    def __init__(self):
        self.items, self.lock = {}, threading.Lock()
        self._told = set()

    def register(self, name, title, check, fix, ttl=30, off=None):
        self.items[name] = Capability(name, title, check, fix, ttl, off)

    def ok(self, name):
        c = self.items.get(name)
        return bool(c and c.status()["ok"])

    def all(self):
        with self.lock:
            return [c.status() for c in self.items.values()]

    def missing(self, names):
        """Messages for the named capabilities that are not available (unknown names count as missing)."""
        out = []
        for n in names:
            c = self.items.get(n)
            s = c.status() if c else None
            if not s or not s["ok"]:
                out.append(s["message"] if s else f"{n} is not set up.")
        return out

    def degraded(self, optional):
        """For a module: what it can use but cannot right now, as [{capability, feature, reason, fix}]. Names that are not capabilities (other modules) are not listed."""
        out = []
        for n in optional:
            c = self.items.get(n)
            s = c.status() if c else None
            if s and not s["ok"]:
                out.append({"capability": n, "feature": s["title"], "reason": s["reason"], "fix": s["fix"]})
        return out

    def skip(self, job, needs, log=print):
        """For a scheduled job: True when something it needs is missing (the job should return). Says why once, then stays quiet until it is back."""
        gone = self.missing(needs if isinstance(needs, (list, tuple)) else [needs])
        if not gone:
            self._told.discard(job)
            return False
        if job not in self._told:
            self._told.add(job)
            log(f"skipping {job}: {' '.join(gone)}")
        return True

    def degrade(self, needs, fn, fallback=None):
        """Run fn() if everything in needs is available. Otherwise return fallback (or the fix messages), and never raise for that reason."""
        gone = self.missing(needs if isinstance(needs, (list, tuple)) else [needs])
        if gone:
            return fallback if fallback is not None else " ".join(gone)
        return fn()


def internet_check(host="1.1.1.1", port=443, timeout=3):
    try:
        socket.create_connection((host, port), timeout=timeout).close()
        return True
    except OSError:
        return False, "No internet connection."


def reachable(url, timeout=3):
    """True if something answers at url (any HTTP status counts: the service is up). Otherwise (False, why)."""
    from urllib.error import HTTPError
    from urllib.request import urlopen
    try:
        urlopen(url, timeout=timeout).close()
    except HTTPError:
        return True
    except Exception as e:
        return False, f"Cannot reach {url.split('//')[-1].split('/')[0]}."
    return True
