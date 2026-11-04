"""Medicines on your own schedule and appointments you add yourself. Reminders only, never medical advice."""
import json
import os
import re
import time
from datetime import date, datetime, timedelta

from core import host
from core.helpers import cached, esc, http, now, safe, t12

host.need(globals(), "DATA")

# ================================================================ Health: medicines and appointments you add yourself
# Reminders only. This is a tick-list, not medical advice: never change a dose or skip one because of it.
from modules.health.meds import EVERY, clean, convert_old, dose_no, doses_on, early, key, next_due, split_key  # noqa: E402
from modules.health.meds import at as dose_at  # noqa: E402

SG_FILE = f"{DATA}/sg.json"
SG_SEED = {
    "meds": [],     # medicines, see modules/health/meds.py: name, dose, how often, times, reminders
    "health": [],   # [{"id", "name", "due": "YYYY-MM-DD", "why"}]  appointments and tests
    "log": {},      # {"2026-10-22": {"<med id>@0800": true}}  ticks by meds day
}


def _sg_load():
    try:
        d = {**SG_SEED, **json.load(open(SG_FILE))}
    except Exception:
        return json.loads(json.dumps(SG_SEED))
    convert_old(d, date.today())  # migration 0002 does this on update; this covers a copy restored from an old backup
    return d


sg = _sg_load()


def sg_save():
    with _lock:
        tmp = SG_FILE + ".tmp"
        json.dump(sg, open(tmp, "w"), indent=1)
        os.replace(tmp, SG_FILE)


def meds_day():
    return date.fromisoformat(journal_day())  # meds turn over at 4 AM like the journal


def telegram_on():
    return not CAPS.missing(["telegram"])


def new_id(prefix, taken):
    while (i := prefix + os.urandom(3).hex()) in taken:
        pass
    return i


def sg_view():
    t = meds_day()
    with _lock:
        meds = [{**m, "next": (n.isoformat() if (n := next_due(m, t)) else None)} for m in sg["meds"]]
        doses = [{"key": key(m["id"], tm), "id": m["id"], "name": m["name"], "dose": m.get("dose", ""), "time": tm, "every": m["every"], "n": n,
                  "of": m.get("stop_after"), "remind": m.get("remind", False)} for m, tm, n in doses_on(sg["meds"], t)]
        return {"today": t.isoformat(), "date": now().date().isoformat(), "meds": meds, "doses": doses, "health": sg["health"], "telegram": telegram_on(),
                "log": {k: v for k, v in sg["log"].items() if k >= (t - timedelta(days=60)).isoformat()}}


def sg_api(path, b):
    b = b or {}
    with _lock:
        if path == "/sg/tick":  # {date, id: "<med id>@HHMM", done}
            d, k = str(b.get("date", "")), str(b.get("id", ""))
            if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", d) or d > now().date().isoformat() or not k:
                return {"ok": False}, 400
            day = sg["log"].setdefault(d, {})
            if b.get("done"):
                day[k] = True
            else:
                day.pop(k, None)
        elif path == "/sg/med":  # add (no id) or change one medicine
            m, why = clean(b, meds_day())
            if not m:
                return {"ok": False, "msg": why}, 400
            if m["remind"] and not telegram_on():  # the form hides the switch; this covers anything that calls the API directly
                return {"ok": False, "msg": "Connect Telegram first (Settings, Telegram), then turn reminders on."}, 400
            old = next((x for x in sg["meds"] if x["id"] == m["id"]), None)
            if m["id"] and not old:
                return {"ok": False, "msg": "That medicine is gone. Refresh and try again."}, 404
            if old:
                old.clear(); old.update(m)
            else:
                m["id"] = new_id("m", {x["id"] for x in sg["meds"]})
                sg["meds"].append(m)
        elif path == "/sg/med/delete":  # {id}; its past ticks stay in the log, nothing shows them
            sg["meds"] = [x for x in sg["meds"] if x["id"] != b.get("id")]
        elif path == "/sg/appt":  # add (no id) or change an appointment: {id?, name, due, why}
            name, due = str(b.get("name") or "").strip()[:60], str(b.get("due") or "")
            if not name or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", due):
                return {"ok": False, "msg": "Give it a name and a date."}, 400
            h = {"name": name, "due": due, "why": str(b.get("why") or "").strip()[:80]}
            old = next((x for x in sg["health"] if x["id"] == b.get("id")), None)
            if old:
                old.update(h)
            else:
                sg["health"].append({"id": new_id("a", {x["id"] for x in sg["health"]}), **h})
        elif path == "/sg/appt/delete":
            sg["health"] = [x for x in sg["health"] if x["id"] != b.get("id")]
        elif path == "/sg/health":  # {id, due}
            for h in sg["health"]:
                if h["id"] == b.get("id") and re.fullmatch(r"\d{4}-\d{2}-\d{2}", str(b.get("due", ""))):
                    h["due"] = b["due"]
        else:
            return {"error": "not found"}, 404
        sg_save()
    return {"ok": True, **sg_view()}, 200


def check_sg():
    """Telegram nudges for appointments, 2 weeks and 2 days ahead."""
    t = now()
    if t.hour < 9 or not telegram_on():
        return
    d = t.date()
    for h in sg["health"]:
        left = (date.fromisoformat(h["due"]) - d).days
        if left in (14, 2) and once(f"health:{h['id']}:{h['due']}:{left}"):
            send(f"🩸 <b>{esc(h['name'])} in {left} days</b>\nDue {date.fromisoformat(h['due']):%a %d %b}. {esc(h.get('why', ''))}")


def med_text(m, tm, again=False):
    when = t12(datetime.strptime(tm, "%H:%M"))
    return f"💊 <b>{esc(m['name'])}, {when}</b>" + (f"\n{esc(m['dose'])}" if m.get("dose") else "") + ("\n<i>Reminding you again.</i>" if again else "")


def med_buttons(k, d):
    return [[B("✅ Done", f"sgmed:done:{k}:{d}"), B("💤 5 min", f"sgmed:5:{k}:{d}"), B("💤 15 min", f"sgmed:15:{k}:{d}")]]


def find_dose(k):
    """The medicine and time for a dose key. An old button (a slot or course id with no time) finds that medicine's first time."""
    mid, tm = split_key(k)
    m = next((x for x in sg["meds"] if x["id"] == mid), None)
    if not m:
        return None, None
    return m, tm if tm in m["times"] else m["times"][0]


def check_meds():
    """A dose with reminders on, still unticked at its time, gets one Telegram message, and another each time a snooze runs out.
    Nothing is sent while Telegram is not connected."""
    if not telegram_on():
        return
    t, today = now(), meds_day()
    snz = state.setdefault("med_snooze", {})
    for d in (today, today - timedelta(days=1)):
        for m, tm, _ in doses_on([x for x in sg["meds"] if x.get("remind")], d):
            k = key(m["id"], tm)
            sk, start = f"{k}:{d}", dose_at(d, tm, TZ)
            if (sg["log"].get(d.isoformat()) or {}).get(k):
                if snz.pop(sk, None):
                    save()
                continue
            if start <= t < start + timedelta(hours=3) and once(f"med:{sk}"):
                send(med_text(m, tm), med_buttons(k, d))
                nudged("med", sid=k, d=str(d))
            elif sk in snz and snz[sk] <= time.time():
                snz.pop(sk); save()
                send(med_text(m, tm, again=True), med_buttons(k, d))
                nudged("med", sid=k, d=str(d))


def med_snooze(k, d, minutes):
    """💤 on a reminder: ask again in a few minutes. -> the reply for the message."""
    m, tm = find_dose(k)
    if not m:
        return "That medicine is no longer in your list."
    with _lock:
        state.setdefault("med_snooze", {})[f"{key(m['id'], tm)}:{d}"] = time.time() + minutes * 60
        save()
    return f"💤 I'll remind you about <b>{esc(m['name'])}</b> again at {t12(now() + timedelta(minutes=minutes))}."


def nudged(kind, **kw):
    """The last meds nudge or reminder sent, for a bare "done" typed back."""
    with _lock:
        state["last_nudge"] = {"kind": kind, "at": time.time(), **kw}
        save()


def med_tick(k, d):
    """Ticks one dose for a day (the button and typed "took my meds" both land here). k is the dose key, or a medicine with one time."""
    m, tm = find_dose(k)
    if not m:
        return "That medicine is no longer in your list."
    d, k = str(d), key(m["id"], tm)
    with _lock:
        was = (sg["log"].get(d) or {}).get(k)
        sg["log"].setdefault(d, {})[k] = True
        sg_save()
        state.setdefault("med_snooze", {}).pop(f"{k}:{d}", None)
        save()
    what = esc(m["name"]) + (f" ({t12(datetime.strptime(tm, '%H:%M'))})" if len(m["times"]) > 1 else "")
    return f"✅ <b>{what}</b> was already ticked." if was else f"✅ <b>{what}</b> ticked. Nice."


MEDS_WORDS = r"\b(meds?|medicines?|medications?|tablets?|pills?|supplements?|vitamins?|capsules?|doses?)\b"
MEDS_TOOK = r"\b(took|taken|take[dn]|had|done|finished|ticked?|mark(ed)?|swallowed|popped|completed?)\b"
PARTS = {"morning": (r"\b(morning|empty stomach|breakfast)\b", 4, 12), "lunch": (r"\b(lunch|afternoon)\b", 12, 17),
         "night": (r"\b(night|tonight|sleep|bed|bedtime|dinner|evening)\b", 17, 28)}  # hours in the meds day; 28 is 4 AM the next morning


def med_words(m):
    return {w for w in re.findall(r"[a-z0-9]{3,}", m["name"].lower()) if w not in ("vitamin", "mk", "fish", "oil")}


def open_doses(t0):
    """Unticked doses from 18 hours ago to 4 hours ahead: [(seconds from now, medicine, time, day)]."""
    out = []
    for d in (meds_day(), meds_day() - timedelta(days=1)):
        for m, tm, _ in doses_on(sg["meds"], d):
            a = dose_at(d, tm, TZ)
            if not (sg["log"].get(d.isoformat()) or {}).get(key(m["id"], tm)) and t0 - timedelta(hours=18) <= a <= t0 + timedelta(hours=4):
                out.append((abs((a - t0).total_seconds()), m, tm, d))
    return out


def typed_meds(t):
    """ "Took my morning meds", "had the magnesium": ticks those doses. None when it isn't about taking meds."""
    if re.match(r"^(did|have|has|should|shall|when|what|which|do|does|is|are|remind|set|how)\b", t) or t.endswith("?"):
        return None
    words = set(re.findall(r"[a-z0-9]+", t))
    if not re.search(MEDS_TOOK, t) or not (re.search(MEDS_WORDS, t) or any(med_words(m) & words for m in sg["meds"])):
        return None
    t0, parts = now(), [(lo, hi) for rx, lo, hi in PARTS.values() if re.search(rx, t)]
    opened = open_doses(t0)
    named = [x for x in opened if med_words(x[1]) & words or any(lo * 60 <= early(x[2]) < hi * 60 for lo, hi in parts)]
    if named:
        return "\n".join(med_tick(key(m["id"], tm), d) for _, m, tm, d in sorted(named, key=lambda x: (x[3], early(x[2]))))
    if any(med_words(m) & words for m in sg["meds"]) or parts:
        return "✅ Those are already ticked for now."
    if not opened:
        return "✅ All your meds are already ticked for now."
    _, m, tm, d = min(opened, key=lambda x: x[0])  # nothing named: the unticked dose nearest to now
    return med_tick(key(m["id"], tm), d)


BARE_DONE = r"^(done|done it|did it|did that|all done|yes,? done|taken|took (it|them|those)|had (it|them)|finished|completed)[\s.!👍✅]*$"


def bare_done():
    """A bare "done": answers the last meds nudge or reminder from the past 4 hours."""
    with _lock:
        n = state.pop("last_nudge", None)
        save()
    if not n or time.time() - n["at"] > 4 * 3600:
        return send("🤔 Done with what? Tap ✅ Done on the reminder, or say something like <i>took my morning meds</i>.")
    if n["kind"] == "med":
        return send(med_tick(n["sid"], n["d"]))
    return send(f"✅ Done:\n<i>{esc(n['text'])}</i>")


def register(app):
    host.need(globals(), "B", "CAPS", "TZ", "_lock", "journal_day", "once", "save", "send", "state")

    app.router.add("GET", "/sg", lambda req: sg_view())
    app.router.add_prefix("POST", "/sg/", lambda req: sg_api(req.path, req.json()))

