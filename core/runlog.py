"""The run log: one JSON line per job and per AI call, kept 90 days. Times, counts and error messages only, never journal words."""
import json, os, threading, time, traceback, uuid

from core.helpers import safe

# One JSON line per job (scheduled vs actual start, end, seconds, status, waits, retries, errors) and per AI call
# (model, purpose, tokens, seconds, attempt). Times, counts and error messages only: never journal words. Kept 90 days.
# The Night log on Server & Apps reads it (GET /runs); the host adds its backup timers to the same file.
RUN_LOG = os.environ.get("HL_RUN_LOG", "/data/runs.jsonl")
_runl = threading.Lock()
_run = threading.local()


def run_write(rec):
    with _runl:
        with open(RUN_LOG, "a") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")


def run_info(key, val, add=False):
    """Adds a detail to the innermost job running on this thread (no-op outside one)."""
    st = getattr(_run, "stack", None)
    if not st:
        return
    if add:
        st[-1]["info"].setdefault(key, [])
        if len(st[-1]["info"][key]) < 8:
            st[-1]["info"][key].append(val)
    else:
        st[-1]["info"][key] = val


def run_job(name, fn, sched=None):
    """Runs fn as a logged job. sched is when it was meant to start ("04:30"), if it has a fixed time."""
    st = _run.__dict__.setdefault("stack", [])
    j = {"id": uuid.uuid4().hex[:8], "name": name, "info": {}, "ai": {}, "t0": time.time()}
    safe(lambda: run_write({"t": "start", "id": j["id"], "parent": st[-1]["id"] if st else None, "job": name, "sched": sched, "start": round(j["t0"], 1)}))
    st.append(j)
    status, err, out = "ok", None, None
    try:
        out = fn()
        if out == "skipped":
            status = "skipped"
    except Exception as e:
        status, err = "failed", f"{type(e).__name__}: {e}"[:300]
        traceback.print_exc()
    finally:
        st.pop()
        t1 = time.time()
        if j["info"].get("errors") and status == "ok":
            status = "warn"
        rec = {"t": "job", "id": j["id"], "parent": st[-1]["id"] if st else None, "job": name, "sched": sched,
               "start": round(j["t0"], 1), "end": round(t1, 1), "secs": round(t1 - j["t0"], 1), "status": status, "err": err, **j["info"]}
        safe(lambda: run_write(rec))
    return out


def run_purpose(p):
    """What the next AI calls on this thread are for ("deep read 2026-10-27"); repeats inside one job count as retries."""
    _run.purpose = p


def run_prune():
    """Drops lines older than 90 days (once a day)."""
    cut = time.time() - 90 * 86400
    with _runl:
        rows = [l for l in safe(lambda: open(RUN_LOG).read().splitlines(), []) or [] if safe(lambda l=l: json.loads(l).get("start", json.loads(l).get("at", 0)), 0) >= cut]
        tmp = RUN_LOG + ".tmp"
        open(tmp, "w").write("".join(l + "\n" for l in rows))
        os.replace(tmp, RUN_LOG)


def run_view(hours=100):
    """What the Night log shows: the jobs of the last day and a half, each with its AI calls."""
    cut = time.time() - hours * 3600
    rows = []
    for l in safe(lambda: open(RUN_LOG).read().splitlines(), []) or []:
        r = safe(lambda l=l: json.loads(l), None)
        if r and (r.get("start") or r.get("at") or 0) >= cut:
            rows.append(r)
    # the backup and the git copy are run by the host helper, which keeps its own record beside the run log
    helper = safe(lambda: json.load(open(os.path.join(os.path.dirname(RUN_LOG), "night-runs.json"))).get("runs") or [], []) or []
    names = {"backup": "Backup", "github": "Copy settings to git"}
    rows += [{"t": "job", "id": f"h{int(r['start'])}{r['job'][:2]}", "parent": None, "job": names.get(r["job"], r["job"]), "sched": None, "start": r["start"],
              "end": r.get("end"), "secs": round((r.get("end") or r["start"]) - r["start"], 1), "status": "ok" if r.get("ok") else "failed",
              "err": None if r.get("ok") else r.get("msg")} for r in helper if r.get("ok") is not None and r["start"] >= cut]
    return {"jobs": [r for r in rows if r["t"] == "job"], "ai": [r for r in rows if r["t"] == "ai"], "starts": [r for r in rows if r["t"] == "start"],
            "boots": [r["at"] for r in rows if r["t"] == "boot"], "now": time.time(), "since": run_since()}


def run_since():
    """When the bot started logging (its first boot line): nights before it show as not logged, not as missed."""
    for l in safe(lambda: open(RUN_LOG).read().splitlines(), []) or []:
        if '"t": "boot"' in l:
            return safe(lambda: json.loads(l)["at"], 0)
    return time.time()
