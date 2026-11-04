"""Keeps the AI models in check: tokens used, the quick model kept loaded, big models loaded and unloaded by hand."""
import json
import re
import threading
import time
import uuid
from datetime import timedelta

from core import llm as _llm

from core import host
from core.helpers import cached, esc, http, now, safe

host.need(globals(), "DATA")

# ---------------------------------------------------------------- AI usage: tokens in and out of the model, per day (midnight to midnight IST) and feature
USAGE_FILE = f"{DATA}/ai-usage.json"
USAGE = _llm.Usage(USAGE_FILE, today=lambda: f"{now():%Y-%m-%d}")
ai_usage, _ulock = USAGE.data, USAGE.lock


def count_tokens(kind, j, usd=0.0):
    """Ollama reports prompt_eval_count (in) and eval_count (out) on every finished reply. Claude calls also pass their cost."""
    i, o = int(j.get("prompt_eval_count") or 0), int(j.get("eval_count") or 0)
    if not i and not o:
        return
    st, p = getattr(_run, "stack", None), getattr(_run, "purpose", None) or kind
    job = st[-1] if st else None
    if job is not None:
        job["ai"][p] = job["ai"].get(p, 0) + 1
    ns = lambda k: round((j.get(k) or 0) / 1e9, 1)
    safe(lambda: run_write({"t": "ai", "at": round(time.time(), 1), "job": job and job["id"], "kind": kind, "model": j.get("model") or kind, "purpose": p,
                            "attempt": job["ai"][p] if job else 1, "in": i, "out": o, "secs": ns("total_duration") or None, "load": ns("load_duration") or None,
                            "read": ns("prompt_eval_duration") or None, "write": ns("eval_duration") or None, **({"usd": usd} if usd else {})}))
    USAGE.add(kind, i, o, usd)


def ai_usage_view():
    t = now().date()
    since = (t - timedelta(days=t.weekday() + 7)).isoformat()  # this week and last, Monday to Sunday
    days, first, total = {}, t.isoformat(), {"in": 0, "out": 0, "calls": 0}
    with _ulock:
        for src in (ai_usage,):
            for d, kinds in src.items():
                first = min(first, d)
                if d >= since:
                    days.setdefault(d, {}).update({k: dict(v) for k, v in kinds.items()})
                for v in kinds.values():
                    for k in total:
                        total[k] += v.get(k, 0)
    return {"today": t.isoformat(), "first": first, "days": days, "total": total}


# ---------------------------------------------------------------- keeping the quick AI loaded (2026-10-30)
# The 4B and the intent embedder stay in memory (no GPU here, so "loaded" means held in RAM, about 3.8 GB) so nothing waits on
# a load. The big models (news, Gemma: 18 GB each) need that room: any call to one first moves the 4B out and raises the busy
# flag, whatever the time (a catch-up after a power cut too). The watchdog puts it back once no big call has run for AI_GRACE.
# "Free AI memory" holds it off until the AI is next used.
AI_GRACE = 150  # longer than the news model's own 2 minute keep_alive, so the two are never in memory together
_big, _big_lock = {}, threading.Lock()
_ai = {"last_big": 0.0, "label": None, "held": False}


def ai_busy():
    """What a big model is doing now (or did within the grace), or None."""
    with _big_lock:
        if _big:
            return next(iter(_big.values()))
    return _ai["label"] if time.time() - _ai["last_big"] < AI_GRACE else None


def _tag(name):
    return name if ":" in name else name + ":latest"


def ai_loaded():
    return {m["name"]: m for m in http(f"{OLLAMA}/api/ps", timeout=10).get("models", [])}


def big_call(label, fn):
    """One call to a big model, with the 4B moved out of memory first."""
    key = uuid.uuid4().hex
    with _big_lock:
        first = not _big
        _big[key] = label
        _ai["label"] = label
    if first and _tag(MODEL) in (safe(ai_loaded, {}) or {}):
        safe(lambda: http(f"{OLLAMA}/api/generate", {"model": MODEL, "keep_alive": 0}, timeout=60))
    try:
        return fn()
    finally:
        with _big_lock:
            _big.pop(key, None)
            _ai["last_big"] = time.time()


def ai_keep():
    """keep_alive for the quick model: forever, except while a big job needs the room. Using it ends a "Free AI memory" hold."""
    _ai["held"] = False
    return -1 if not ai_busy() else "1m"


def ai_warm():
    """Loads the 4B and the embedder if they're missing (startup, Ollama restarts, after a big job). Never during one, or a hold."""
    if ai_busy() or _ai["held"] or CAPS.skip("AI warm-up", "ollama"):
        return
    loaded, have = ai_loaded(), safe(ai_tags, {}) or {}
    if _tag(MODEL) not in loaded and _tag(MODEL) in have:  # a model that was never downloaded is shown as such, never "loading" forever
        http(f"{OLLAMA}/api/generate", {"model": MODEL, "keep_alive": -1}, timeout=300)
    if _tag(EMBED_MODEL) not in loaded and _tag(EMBED_MODEL) in have:
        http(f"{OLLAMA}/api/embed", {"model": EMBED_MODEL, "input": ["warm"], "keep_alive": -1}, timeout=300)


def ai_status():
    """For the Server page, the Planner box and the server reply: each model, what it's doing, and the busy flag."""
    loaded, busy = safe(ai_loaded, None), ai_busy()
    if loaded is None:
        return {"reachable": False, "busy": busy, "models": []}
    tags = safe(ai_tags, None)
    known, tags = tags is not None, tags or {}
    gb = lambda n: round(ai_size(n, loaded, tags) / 1e9, 1) if n in loaded else 0
    def quick(n, role):
        state = "ready" if n in loaded else "missing" if known and n not in tags else "paused" if busy else "off" if _ai["held"] else "loading"
        note = {"ready": "Ready", "paused": "Paused to make room", "off": "Freed until next use", "loading": "Loading", "missing": "Not downloaded yet"}[state]
        return {"name": n, "role": role, "state": state, "note": note, "gb": gb(n), "params": ai_params(n, tags)}
    rows = [quick(_tag(MODEL), "Quick model"), quick(_tag(EMBED_MODEL), "Understanding model")]
    for n in loaded:
        if busy and n in (_tag(NEWS_MODEL), _tag(JOURNAL_MODEL)):
            rows.insert(0, {"name": n, "role": "News model" if n == _tag(NEWS_MODEL) else "Journal model",
                            "state": "working", "note": busy, "gb": gb(n), "params": ai_params(n, tags)})
    return {"reachable": True, "busy": busy, "models": rows, "others": safe(lambda: ai_others(loaded, tags), []), "mem": ai_mem(loaded, tags)}


# ---------------------------------------------------------------- loading other models by hand (2026-11-02)
# The Server page lists every installed model besides the two kept loaded, each with Load / Unload. A model loads only when
# free memory (MemAvailable, read live) covers its size plus AI_ROOM; the check runs again here at the tap, not just on the page.
# Loaded by hand means keep_alive -1, so it stays until Unload (or until Ollama needs the room for a big job).
AI_ROOM = 1.0  # GB on top of the file: a running model needs more than its weights
AI_SLOTS = 4  # OLLAMA_MAX_LOADED_MODELS in compose.yaml: one more would push a kept-loaded model out
_loading, _caps, _unloading = set(), {}, {}  # _unloading: name -> when Unload was tapped, until it leaves memory


def ai_size(n, loaded, tags):
    """Bytes a loaded model really holds. On CPU Ollama can report less than it uses (Gemma 26B: 8.9 GB reported, 18.7 GB held),
    so never count it as smaller than its file."""
    return max(loaded[n]["size"], (tags.get(n) or {}).get("size", 0))


def ai_mem(loaded=None, tags=None):
    """Free and total memory in GB, and how much of the used part is AI models."""
    info = {}
    for line in open("/proc/meminfo"):
        k, v = line.split(":", 1)
        info[k] = int(v.split()[0]) * 1024
    ai = sum(ai_size(n, loaded, tags or {}) for n in (loaded or {}))
    return {"total": round(info["MemTotal"] / 1e9, 1), "free": round(info["MemAvailable"] / 1e9, 1), "ai": round(ai / 1e9, 1)}


def ai_nice(n):
    if n == _tag(JOURNAL_MODEL):
        return "Journal model"
    if n == _tag(NEWS_MODEL):
        return "Old news model"
    fam = n.split(":")[0]  # qwen3.5 -> Qwen 3.5, gemma4 -> Gemma 4, nomic-embed-text -> Nomic embed text; the size goes on its own badge
    fam = re.sub(r"^([a-z]+)(\d)", r"\1 \2", fam).replace("-", " ")
    return fam[:1].upper() + fam[1:]


def ai_tags():
    return {m["name"]: m for m in http(f"{OLLAMA}/api/tags", timeout=10).get("models", [])}


def ai_params(n, tags):
    """The model's size in parameters, as people call it: from the tag (gemma4:26b -> 26B), else Ollama's count (307.58M -> 308M)."""
    if m := re.search(r":(\d+(?:\.\d+)?)([bm])\b", n):
        return m[1] + m[2].upper()
    raw = ((tags.get(n) or {}).get("details") or {}).get("parameter_size") or ""
    if m := re.match(r"([\d.]+)([BM])$", raw):
        v = float(m[1])
        return (f"{v:.0f}" if v >= 10 else f"{v:.1f}".rstrip("0").rstrip(".")) + m[2]
    return ""


def ai_others(loaded, tags):
    free = ai_mem()["free"]
    full = len(loaded) >= AI_SLOTS
    out = []
    for m in tags.values():
        n = m["name"]
        if n in (_tag(MODEL), _tag(EMBED_MODEL)):
            continue
        on = n in loaded
        gb = round((ai_size(n, loaded, tags) if on else m["size"]) / 1e9, 1)
        need = round(m["size"] / 1e9 + AI_ROOM, 1)
        why = f"All {AI_SLOTS} AI slots are in use. Unload a model first." if full else None if need <= free else f"Needs {need:.1f} GB free, only {free:.1f} GB is."
        out.append({"name": n, "label": ai_nice(n), "gb": gb, "need": need, "fits": not why, "why": why, "params": ai_params(n, tags),
                    "state": "loading" if n in _loading and not on else "unloading" if on and time.time() - _unloading.get(n, 0) < 300 else "on" if on else "off"})
    return sorted(out, key=lambda o: (o["state"] == "off", o["gb"]))


def ai_is_embed(n):
    if n not in _caps:
        _caps[n] = "embedding" in (http(f"{OLLAMA}/api/show", {"model": n}, timeout=10).get("capabilities") or [])
    return _caps[n]


def ai_load(name, act):
    """POST /server/ai/model: {name, act: load|unload}. Never the two kept loaded, never while a big job holds the memory."""
    tags = {m["name"]: m for m in http(f"{OLLAMA}/api/tags", timeout=10).get("models", [])}
    if name not in tags or name in (_tag(MODEL), _tag(EMBED_MODEL)):
        return {"ok": False, "error": "That model can't be changed here."}, 400
    url = f"{OLLAMA}/api/embed" if ai_is_embed(name) else f"{OLLAMA}/api/generate"
    body = {"model": name, "input": ["warm"]} if url.endswith("embed") else {"model": name}
    if act == "unload":  # only when it's in memory: a call to a model that isn't loads it first, and that can push a kept one out
        _loading.discard(name)
        if name in ai_loaded():  # in the background: Ollama lets a reply in progress (Open WebUI) finish first
            _unloading[name] = time.time()
            threading.Thread(target=lambda: safe(lambda: http(url, {**body, "keep_alive": 0}, timeout=600)), daemon=True).start()
        return {"ok": True}, 200
    if ai_busy():
        return {"ok": False, "error": f"Busy: {ai_busy().lower()}. Try again when it's done."}, 409
    if name in _loading or name in ai_loaded():
        return {"ok": True}, 200
    _unloading.pop(name, None)
    if len(ai_loaded()) >= AI_SLOTS:
        return {"ok": False, "error": f"All {AI_SLOTS} AI slots are in use. Unload a model first."}, 409
    need, free = tags[name]["size"] / 1e9 + AI_ROOM, ai_mem()["free"]
    if need > free:
        return {"ok": False, "error": f"Needs {need:.1f} GB free, only {free:.1f} GB is."}, 409
    _loading.add(name)
    def go():
        try:
            http(url, {**body, "keep_alive": -1}, timeout=900)
        finally:
            _loading.discard(name)
    threading.Thread(target=go, daemon=True).start()
    return {"ok": True}, 200


def llm_json(prompt, num_predict=120, timeout=120, kind="Other", model=None, ctx=None):
    big = bool(model) and model != MODEL
    body = {"model": model or MODEL, "prompt": prompt, "stream": False, "think": False, "format": "json", "keep_alive": "2m" if big else ai_keep(),
            "options": {"temperature": 0, "num_predict": num_predict, **({"num_ctx": ctx} if ctx else {})}}
    r = big_call("Writing the news", lambda: http(f"{OLLAMA}/api/generate", body, timeout=timeout)) if big else http(f"{OLLAMA}/api/generate", body, timeout=timeout)
    count_tokens(kind, r)
    return json.loads(r["response"])


def nice_when(dt):
    d = dt.date() - now().date()
    day = "today" if d.days == 0 else "tomorrow" if d.days == 1 else f"on {dt:%A %d %b}" if d.days < 7 else f"on {dt:%d %b}"
    return f"{day} at {dt:%-I:%M %p}" if day != "today" else f"at {dt:%-I:%M %p} today"


def register(app):
    host.need(globals(), "CAPS", "EMBED_MODEL", "JOURNAL_MODEL", "MODEL", "NEWS_MODEL", "OLLAMA", "_run", "run_write", "state")

    router = app.router
    router.add("GET", "/sg/ai", lambda req: ai_usage_view())
    router.add("GET", "/server/ai", lambda req: ai_status())

    @router.post("/server/ai/model")
    def server_ai_model(req):
        b = req.json()
        return safe(lambda: ai_load(str(b.get("name", "")), b.get("act")), ({"ok": False, "error": "The AI engine didn't answer."}, 502))

