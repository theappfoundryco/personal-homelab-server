"""Jobs that modules declare: at set times of day (in the user's timezone) or every N seconds. A failing job is logged and never stops the others."""
import threading
import time
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

DAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]


def show_time(h, m):
    """4:30 AM style, always 12-hour."""
    return f"{h % 12 or 12}:{m:02d} {'AM' if h < 24 and h % 24 < 12 else 'PM'}"


class Job:
    def __init__(self, name, fn, at=None, every=None, weekdays=None, catch_up=True):
        """at: [(hour, minute)] times of day. every: seconds. weekdays: 0 = Monday ... 6 = Sunday (default all).
        catch_up: if the machine was off at the set time, run once when it is back (the same day)."""
        if bool(at) == bool(every):
            raise ValueError(f"job {name}: give either at= or every=")
        self.name, self.fn, self.at, self.every = name, fn, sorted(at or []), every
        self.weekdays, self.catch_up = set(weekdays) if weekdays is not None else set(range(7)), catch_up

    def describe(self):
        days = "every day" if len(self.weekdays) == 7 else "on " + ", ".join(DAYS[d] for d in sorted(self.weekdays))
        if self.every:
            return f"{self.name}: every {self.every // 60} min" if self.every >= 120 else f"{self.name}: every {self.every} sec"
        return f"{self.name}: {days} at " + " and ".join(show_time(*t) for t in self.at)


class Scheduler:
    def __init__(self, tz="UTC", log=print, clock=time.time):
        self.tz, self.log, self.clock = ZoneInfo(tz), log, clock
        self.jobs, self.ran, self.last = [], set(), {}
        self.lock = threading.Lock()

    def add(self, job):
        self.jobs.append(job)
        return job

    def now(self):
        return datetime.fromtimestamp(self.clock(), self.tz)

    def due(self, now=None):
        """Jobs that should run right now, and no job twice for the same slot."""
        now = now.astimezone(self.tz) if now else self.now()
        out = []
        for j in self.jobs:
            if j.every:
                if now.timestamp() - self.last.get(j.name, 0) >= j.every:
                    out.append((j, f"{j.name}:{int(now.timestamp() // j.every)}"))
            elif now.weekday() in j.weekdays:
                for h, m in j.at:
                    slot = now.replace(hour=h, minute=m, second=0, microsecond=0)
                    late = now - slot
                    if timedelta(0) <= late < (timedelta(hours=24) if j.catch_up else timedelta(minutes=1)):
                        out.append((j, f"{j.name}:{slot:%Y%m%d%H%M}"))
        return [(j, k) for j, k in out if k not in self.ran]

    def tick(self, now=None, wait=False):
        """Start everything that is due, each in its own thread. Returns the job names started."""
        started, threads = [], []
        for j, key in self.due(now):
            with self.lock:
                self.ran.add(key)
                self.last[j.name] = (now.timestamp() if now else self.clock())
            t = threading.Thread(target=self._run, args=(j,), daemon=True)
            t.start()
            threads.append(t)
            started.append(j.name)
        if wait:
            for t in threads:
                t.join()
        return started

    def _run(self, job):
        try:
            job.fn()
        except Exception as e:
            self.log(f"job {job.name} failed ({e}); it will try again at its next time.")

    def run_forever(self, every=20):
        while True:
            try:
                self.tick()
            except Exception as e:
                self.log(f"scheduler hiccup ({e})")
            time.sleep(every)

    def describe(self):
        return [j.describe() for j in self.jobs]
