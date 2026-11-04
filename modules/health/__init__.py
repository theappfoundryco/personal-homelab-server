"""Medicine times, weekly courses and appointments you add yourself. Reminders only, never medical advice."""
import json
import os
import re
import time
from datetime import date, datetime, timedelta

from core import host
from core.helpers import cached, esc, http, now, safe

host.need(globals(), "DATA")

# ================================================================ Health: medicines, courses and appointments you add yourself
# Reminders only. This is a tick-list, not medical advice: never change a dose or skip one because of it.
SG_FILE = f"{DATA}/sg.json"
SG_SEED = {
    "slots": [],    # [{"id", "label", "when", "items": [names]}]  daily medicine times, ticked off each day
    "courses": [],  # [{"id", "name", "weekday": 0-6, "start": "YYYY-MM-DD", "weeks": n}]  a weekly dose for a few weeks
    "health": [],   # [{"id", "name", "due": "YYYY-MM-DD", "why"}]  appointments and tests
    "log": {},      # {"2026-10-22": {"morning": true, "course-id": true}}
}


def _sg_load():
    try:
        return {**SG_SEED, **json.load(open(SG_FILE))}
    except Exception:
        return json.loads(json.dumps(SG_SEED))


sg = _sg_load()


def sg_save():
    with _lock:
        tmp = SG_FILE + ".tmp"
        json.dump(sg, open(tmp, "w"), indent=1)
        os.replace(tmp, SG_FILE)


SUB_PAID_SINCE = "2026-10-28"  # paid ticks started here; older charges are never shown as unpaid


def course_info(c, today=None):
    t = today or now().date()
    start = date.fromisoformat(c["start"])
    doses = [start + timedelta(weeks=i) for i in range(c["weeks"])]
    taken = [d for d in doses if (sg["log"].get(d.isoformat()) or {}).get(c["id"])]
    nxt = next((d for d in doses if d >= t), None)
    return {"doses": [d.isoformat() for d in doses], "taken": len(taken), "next": nxt.isoformat() if nxt else None,
            "dose_today": doses.index(t) + 1 if t in doses else None, "ends": doses[-1].isoformat()}


def sg_view():
    t = date.fromisoformat(journal_day())  # meds turn over at 4 AM like the journal
    with _lock:
        return {"today": t.isoformat(), "date": now().date().isoformat(), "slots": sg["slots"],
                "courses": [{**c, **course_info(c, t)} for c in sg["courses"]], "health": sg["health"],
                "log": {k: v for k, v in sg["log"].items() if k >= (t - timedelta(days=60)).isoformat()}}


def sg_api(path, b):
    with _lock:
        if path == "/sg/tick":  # {date, id, done}: a meds slot or a course dose
            d, k = str(b.get("date", "")), str(b.get("id", ""))
            if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", d) or d > now().date().isoformat() or not k:
                return {"ok": False}, 400
            day = sg["log"].setdefault(d, {})
            if b.get("done"):
                day[k] = True
            else:
                day.pop(k, None)
        elif path == "/sg/health":  # {id, due}
            for h in sg["health"]:
                if h["id"] == b.get("id") and re.fullmatch(r"\d{4}-\d{2}-\d{2}", str(b.get("due", ""))):
                    h["due"] = b["due"]
        else:
            return {"error": "not found"}, 404
        sg_save()
    return {"ok": True, **sg_view()}, 200


def check_sg():
    """Telegram nudges: a course dose on its day, and an appointment 2 weeks and 2 days ahead."""
    t = now()
    if t.hour < 9:
        return
    d = t.date()
    for c in sg["courses"]:
        ci = course_info(c, d)
        if ci["dose_today"] and not (sg["log"].get(d.isoformat()) or {}).get(c["id"]) and once(f"course:{c['id']}:{d}"):
            send(f"💊 <b>{esc(c['name'])} today</b>\nDose {ci['dose_today']} of {c['weeks']}.", [[B("✅ Taken", f"sgtake:{c['id']}:{d}")]])
    for h in sg["health"]:
        left = (date.fromisoformat(h["due"]) - d).days
        if left in (14, 2) and once(f"health:{h['id']}:{h['due']}:{left}"):
            send(f"🩸 <b>{esc(h['name'])} in {left} days</b>\nDue {date.fromisoformat(h['due']):%a %d %b}. {esc(h.get('why', ''))}")


MED_DUE = {"morning": 9 * 60 + 30, "lunch": 14 * 60, "night": 24 * 60}  # minutes after the day's midnight; night is due by 12 am


def med_text(sl):
    return f"💊 <b>{esc(sl['label'])} not ticked yet</b>\n{esc(', '.join(sl['items']))}"


def med_buttons(sid, d):
    return [[B("✅ Done", f"sgmed:done:{sid}:{d}"), B("💤 5 min", f"sgmed:5:{sid}:{d}"), B("💤 10 min", f"sgmed:10:{sid}:{d}")]]


def check_meds():
    """A slot still unticked after its time gets a Telegram nudge (once), and again when a snooze runs out."""
    t = now()
    for sl in list(sg["slots"]):
        due = MED_DUE.get(sl["id"])
        if due is None:
            continue
        for d in (t.date(), t.date() - timedelta(days=1)):
            at = datetime.combine(d, datetime.min.time(), TZ) + timedelta(minutes=due)
            done = (sg["log"].get(d.isoformat()) or {}).get(sl["id"])
            key = f"{sl['id']}:{d}"
            snz = state.setdefault("med_snooze", {})
            if done:
                if snz.pop(key, None):
                    save()
                continue
            if at <= t < at + timedelta(hours=3) and once(f"med:{key}"):
                send(med_text(sl), med_buttons(sl["id"], d))
                nudged("med", sid=sl["id"], d=str(d))
            elif key in snz and snz[key] <= time.time():
                snz.pop(key); save()
                send(med_text(sl), med_buttons(sl["id"], d))
                nudged("med", sid=sl["id"], d=str(d))


def nudged(kind, **kw):
    """The last meds nudge or reminder sent, for a bare "done" typed back."""
    with _lock:
        state["last_nudge"] = {"kind": kind, "at": time.time(), **kw}
        save()


def med_tick(sl, d):
    """Ticks one meds slot for a day (the button and typed "took my meds" both land here)."""
    d = str(d)
    with _lock:
        was = (sg["log"].get(d) or {}).get(sl["id"])
        sg["log"].setdefault(d, {})[sl["id"]] = True
        sg_save()
        state.setdefault("med_snooze", {}).pop(f"{sl['id']}:{d}", None)
        save()
    if was:
        return f"✅ <b>{esc(sl['label'])}</b> was already ticked: {esc(', '.join(sl['items']))}."
    return f"✅ <b>{esc(sl['label'])}</b> ticked: {esc(', '.join(sl['items']))}. Nice."


MEDS_WORDS = r"\b(meds?|medicines?|medications?|tablets?|pills?|supplements?|vitamins?|capsules?|doses?)\b"
MEDS_TOOK = r"\b(took|taken|take[dn]|had|done|finished|ticked?|mark(ed)?|swallowed|popped|completed?)\b"
MEDS_SLOT_WORDS = {"morning": r"\b(morning|empty stomach|breakfast)\b", "lunch": r"\b(lunch|afternoon)\b",
                   "night": r"\b(night|tonight|sleep|bed|bedtime|dinner)\b"}


def med_words(sl):
    return {w for i in sl["items"] for w in re.findall(r"[a-z0-9]{3,}", i.lower()) if w not in ("vitamin", "mk", "fish", "oil")}


def typed_meds(t):
    """ "Took my morning meds", "had the magnesium": ticks those slots. None when it isn't about taking meds."""
    if re.match(r"^(did|have|has|should|shall|when|what|which|do|does|is|are|remind|set|how)\b", t) or t.endswith("?"):
        return None
    named = [sl for sl in sg["slots"] if sl["id"] in MEDS_SLOT_WORDS and re.search(MEDS_SLOT_WORDS[sl["id"]], t)
             or med_words(sl) & set(re.findall(r"[a-z0-9]+", t))]
    if not re.search(MEDS_TOOK, t) or not (re.search(MEDS_WORDS, t) or any(med_words(sl) & set(re.findall(r"[a-z0-9]+", t)) for sl in sg["slots"])):
        return None
    t0 = now()
    if named:  # night is due at midnight, so after midnight it's still last night's
        return "\n".join(med_tick(sl, t0.date() - timedelta(days=1) if sl["id"] == "night" and t0.hour < 6 else t0.date()) for sl in named)
    open_ = []  # nothing named: the unticked slot nearest to now
    for sl in sg["slots"]:
        if sl["id"] not in MED_DUE:
            continue
        for d in (t0.date(), t0.date() - timedelta(days=1)):
            at = datetime.combine(d, datetime.min.time(), TZ) + timedelta(minutes=MED_DUE[sl["id"]])
            if not (sg["log"].get(d.isoformat()) or {}).get(sl["id"]) and t0 - timedelta(hours=18) <= at <= t0 + timedelta(hours=4):
                open_.append((abs((at - t0).total_seconds()), sl, d))
    if not open_:
        return "✅ All your meds are already ticked for now."
    _, sl, d = min(open_, key=lambda x: x[0])
    return med_tick(sl, d)


BARE_DONE = r"^(done|done it|did it|did that|all done|yes,? done|taken|took (it|them|those)|had (it|them)|finished|completed)[\s.!👍✅]*$"


def bare_done():
    """A bare "done": answers the last meds nudge or reminder from the past 4 hours."""
    with _lock:
        n = state.pop("last_nudge", None)
        save()
    if not n or time.time() - n["at"] > 4 * 3600:
        return send("🤔 Done with what? Tap ✅ Done on the reminder, or say something like <i>took my morning meds</i>.")
    if n["kind"] == "med":
        sl = next((x for x in sg["slots"] if x["id"] == n["sid"]), None)
        return send(med_tick(sl, n["d"])) if sl else None
    return send(f"✅ Done:\n<i>{esc(n['text'])}</i>")


def register(app):
    host.need(globals(), "B", "TZ", "_lock", "journal_day", "once", "save", "send", "state")

    app.router.add("GET", "/sg", lambda req: sg_view())
    app.router.add_prefix("POST", "/sg/", lambda req: sg_api(req.path, req.json()))

