"""Notes, reminders, goals of life, and the planner box that decides which one you meant."""
import json
import re
import time
import uuid
from datetime import datetime, timedelta

from core import host
from core.helpers import esc, now, safe
from core.store import write_json

host.need(globals(), "DATA")

def notes_view(msg=None):
    notes = state["notes"]
    if not notes:
        text = "📝 <b>Your notes</b>\nNothing here yet.\n\nTo add one, just type <i>note buy milk</i>."
        return edit(msg, text) if msg else send(text)
    text = ("📝 <b>Your notes</b>\n" + "\n".join(f"{i}. {esc(n['text'])}" for i, n in enumerate(notes, 1))
            + "\n\n<i>Tap ✓ when a note is done (you can undo). Or just tell me: “delete note 2”, “add Canada to the countries note”.</i>")
    buttons = [[B(f"✓ Done: {i}. {n['text'][:24]}", f"note-done:{n['id']}")] for i, n in enumerate(notes, 1)]
    edit(msg, text, buttons) if msg else send(text, buttons)


def add_note(text):
    text = text.strip(" :-,.")
    if not text:
        return notes_view()
    with _lock:
        state["notes"].append({"id": uuid.uuid4().hex[:8], "text": text, "added": time.time()})
        save()
    send(f"📝 Saved: <i>{esc(text)}</i>\n<i>You have {len(state['notes'])} note(s). They show up in your morning briefing.</i>",
         [[B("📝 See all notes", "notes")]])


# ---------------------------------------------------------------- goals of life: only what he names as a goal, and never deleted
GOAL_SAID = r"^\s*(?:add (?:a |my )?|new |my |long[- ]term |life(?:time)? )*goals?(?: (?:of|in) life)?(?: (?:is|are))?(?: to)?\b\s*[:,.-]?\s*"
GOAL_ADD = r"^\s*(?:(?:add (?:a |my )?|new )?(?:life |long[- ]term |lifetime )?goal\s*[:,-]|(?:add (?:a |my )?|new )(?:life |long[- ]term )?goal\b|(?:life|long[- ]term|lifetime) goal\b|my (?:life |long[- ]term )?goal (?:is|in life)\b|goal (?:of|in) life\b)"


def goal_text(text):
    t = re.sub(GOAL_SAID, "", text.strip(), count=1, flags=re.I).strip(" :-,.") or text.strip()
    return t[:1].upper() + t[1:300]


def save_goal(text):
    g = {"id": uuid.uuid4().hex[:8], "text": goal_text(text), "added": time.time()}
    with _lock:
        state.setdefault("goals", []).append(g)
        save()
    return g


def achieve_goal(gid, undo=False):
    """Achieved goals stay, with the date; undo puts one back."""
    with _lock:
        g = next((g for g in state.setdefault("goals", []) if g["id"] == gid), None)
        if g:
            g.pop("achieved", None) if undo else g.__setitem__("achieved", time.time())
            save()
    return g


def edit_goal(gid, text):
    with _lock:
        g = next((g for g in state.get("goals", []) if g["id"] == gid), None)
        if g and text.strip():
            g["text"] = text.strip()[:300]
            save()
    return g


def delete_goal(gid):
    with _lock:
        gone = [g for g in state.get("goals", []) if g["id"] == gid]
        state["goals"] = [g for g in state.get("goals", []) if g["id"] != gid]
        arch = state.setdefault("deleted_goals", []) + [dict(g, deleted=time.time()) for g in gone]
        state["deleted_goals"] = [g for g in arch if time.time() - g["deleted"] < 30 * 86400][-50:]
        save()
    return gone[0] if gone else None


def goals_view(msg=None):
    gs = [g for g in state.get("goals", []) if not g.get("achieved")]
    done = [g for g in state.get("goals", []) if g.get("achieved")]
    if not gs and not done:
        text = "🎯 <b>Your goals</b>\nNone yet.\n\nTo add one, type <i>goal: learn Dutch</i>."
        return edit(msg, text) if msg else send(text)
    text = "🎯 <b>Your goals</b>\n" + ("\n".join(f"{i}. {esc(g['text'])}" for i, g in enumerate(gs, 1)) or "All achieved 🎉")
    if done:
        text += "\n\n<b>Achieved</b>\n" + "\n".join(f"✓ {esc(g['text'])} <i>({datetime.fromtimestamp(g['achieved'], TZ):%d %b %Y})</i>" for g in done[-5:])
    buttons = [[B(f"🏁 Achieved: {i}. {g['text'][:22]}", f"goal-done:{g['id']}")] for i, g in enumerate(gs, 1)]
    edit(msg, text, buttons) if msg else send(text, buttons)


def add_goal(text):
    g = save_goal(text)
    send(f"🎯 Goal saved: <i>{esc(g['text'])}</i>\n<i>It closes your morning briefing.</i>", [[B("🎯 All goals", "goals")]])


# ---------------------------------------------------------------- Planner box: note, reminder or goal? The local model decides on Add, code checks the times
CAPTURE_LEARNED = f"{DATA}/capture-learned.json"  # his corrections; the latest go into the prompt, so no rules to maintain
_cap_cache = {}


def capture_ai(text):
    """note, reminder or goal, from the bot's model (loaded on Add, freed after 5 idle minutes). Only the type comes back, so it's quick;
    the times are worked out by plan_reminders, which asks the model itself when the rules can't. Raises if the AI is down."""
    if text in _cap_cache:
        return _cap_cache[text]
    learned = safe(lambda: json.load(open(CAPTURE_LEARNED)), []) or []
    ex = "\n".join(f'"{x["text"]}" -> {x["kind"]}' for x in learned[-20:])
    j = llm_json("Sort what he said into ONE type:\n"  # fixed text first, so the model reuses it between calls
                 "goal = a long-term life goal or ambition (he often starts with \"goal\").\n"
                 "reminder = something he has to do at a time or on a day (a call, a payment, an appointment), or he says remind me.\n"
                 "note = anything else: ideas, lists, facts, and notes that only mention a time.\n"
                 + (f"His own corrections, follow them:\n{ex}\n" if ex else "")
                 + f'\nHe said: "{text}"\nReply JSON: {{"type": "note|reminder|goal"}}', num_predict=12, timeout=60, kind="Planner")
    out = j.get("type") if j.get("type") in ("note", "reminder", "goal") else "note"
    _cap_cache[text] = out
    while len(_cap_cache) > 30:
        _cap_cache.pop(next(iter(_cap_cache)))
    return out


NOTE_ASK = (r"^\s*(?:(?:please|pls|hey|ok|okay|can you|could you)[\s,]+)*"
            r"(?:(?:make|take|save|add|keep|create|put|write)(?: down)? (?:a |me a |another |one more |a quick |quick |this as a )?notes?\b"
            r"|(?:add|put|save) (?:this|it|that) (?:to|in) (?:my )?notes\b|notes?\s*[:,-])")
NOTE_LEAD = (NOTE_ASK + r"(?: (?:to|in) (?:my )?notes)?(?: (?:of|that|about|saying|to say|to)\b)?"
             r"|^\s*(?:note(?: this| that| down| to self)?\b|jot(?: this| it)?(?: down)?(?: that)?\b|write (?:this |it |that )?down(?: that)?\b"
             r"|remember (?:this|that)\b|save (?:this|that)(?: for later)?\b)")


def note_text(text):
    """The note without how he asked for it: "add a note that I need to call Kartik" saves "I need to call Kartik"."""
    t = re.sub(NOTE_LEAD, "", text.strip(), count=1, flags=re.I).strip(" :,.-")
    return t or text.strip()


CAPTURE_TIDY = f"{DATA}/capture-tidy.json"  # his words next to what was saved, last 50, in case a rewrite ever goes wrong


def tidy(text):
    """Proper English for what he said through Wispr: same meaning, names and numbers, nothing added. Falls back to his words."""
    if len(text) < 4:
        return text
    j = safe(lambda: llm_json("Rewrite his note in clear, correct English: fix grammar, spelling and punctuation.\n"
                              "Keep the meaning and every name, number, date and time exactly. Keep his voice (I, my). "
                              "Don't add or drop details. If it's already fine, return it unchanged.\n"
                              f'Note: "{text}"\nReply JSON: {{"text": "..."}}', num_predict=200, timeout=90, kind="Planner")) or {}
    out = str(j.get("text") or "").strip().strip('"').strip()
    if out.endswith(".") and not text.endswith(".") and out.count(".") == 1:
        out = out[:-1]  # his lists have no full stops; keep them alike
    nums = lambda x: sorted(re.findall(r"\d+", x))
    if not out or nums(out) != nums(text) or not 0.5 * len(text) <= len(out) <= 1.6 * len(text) + 20:
        return text  # a dropped number or a big change in length means the model wandered
    if out != text:
        with _lock:
            d = (safe(lambda: json.load(open(CAPTURE_TIDY)), []) or []) + [{"said": text, "saved": out, "at": time.time()}]
            write_json(CAPTURE_TIDY, d[-50:])
    return out


def capture_learn(text, kind):
    with _lock:
        d = [x for x in (safe(lambda: json.load(open(CAPTURE_LEARNED)), []) or []) if x["text"] != text] + [{"text": text[:200], "kind": kind}]
        write_json(CAPTURE_LEARNED, d[-50:])


def capture_save(b):
    """Saves from the Planner box. kind is his pick (or empty: the AI decides); guess is the quick rules' label he overrode."""
    text = b.get("text", "").strip()[:300]
    if not text:
        return {"ok": False, "error": "Nothing to save."}
    kind = b.get("kind")
    if b.get("guess") and kind and kind != b["guess"]:
        capture_learn(text, kind)
    if not kind and re.match(NOTE_ASK, text, re.I):
        kind = "note"  # he said it's a note
    if not kind:
        kind = safe(lambda: capture_ai(text)) or ("goal" if re.match(GOAL_ADD, text, re.I) else "reminder" if quick_plan(text)[1] or quick_plan(text)[5] else "note")
    if kind == "goal":
        g = save_goal(tidy(goal_text(text)))
        return {"ok": True, "kind": "goal", "msg": f"Goal saved: {g['text']}"}
    if kind == "note":
        t = tidy(note_text(text))
        with _lock:
            state["notes"].append({"id": uuid.uuid4().hex[:8], "text": t[:1].upper() + t[1:], "added": time.time()})
            save()
        return {"ok": True, "kind": "note", "msg": "Saved as a note"}
    repeat = None
    if b.get("when"):  # picked with a chip or the time picker (local time, "YYYY-MM-DDTHH:MM")
        when = safe(lambda: datetime.fromisoformat(b["when"]).replace(tzinfo=TZ))
        items = [(when, quick_plan(text)[3] or text)] if when else []
    else:
        items, repeat = plan_reminders(text, chat=False)  # rules, or the model for several times / "the same"
    items = [(w, t) for w, t in items if w and w > now() - timedelta(minutes=1)]
    items = [(w, tidy(t)) for w, t in items]  # times come from his words; only the task is rewritten
    if not items:
        return {"ok": False, "kind": "reminder", "error": "I couldn't tell when. Add a time, like “at 6pm”, or pick one below."}
    added = save_reminders(items, repeat)
    if not added:
        return {"ok": False, "kind": "reminder", "error": "You already have that reminder."}
    return {"ok": True, "kind": "reminder", "msg": " • ".join(f"{t}, {nice_when(w)}" + (f", repeats {repeat}" if repeat else "") for _, w, t in added)}


PAST = f"{DATA}/planner-past.json"  # every note he ticked and reminder that went off, kept for good: the Planner's Past sheet


def past_load():
    p = safe(lambda: json.load(open(PAST)))
    if p is None:  # first run: start from the notes still in the 30-day archive
        p = [{"id": n["id"], "kind": "note", "text": n["text"], "at": n["done"], "added": n.get("added")} for n in state.get("done_notes", [])]
        write_json(PAST, p)
    return p


def past_add(kind, text, at, iid, added=None):
    with _lock:
        p = past_load()
        if kind == "reminder" and any(x["kind"] == "reminder" and x["text"] == text and 0 <= at - x["at"] < 6 * 3600 for x in p[-30:]):
            return  # a snoozed reminder going off again is the same one
        p = [x for x in p if x["id"] != iid] + [{"id": iid, "kind": kind, "text": text, "at": at, "added": added}]
        write_json(PAST, p[-5000:])


def past_drop(ids):
    with _lock:
        p = past_load()
        write_json(PAST, [x for x in p if x["id"] not in ids])


def past_view():
    with _lock:
        p = sorted(past_load(), key=lambda x: -x["at"])
        gs = sorted((g for g in state.get("goals", []) if g.get("achieved")), key=lambda g: -g["achieved"])
    return {"reminders": [x for x in p if x["kind"] == "reminder"], "notes": [x for x in p if x["kind"] == "note"], "goals": gs}


def past_restore(iid):
    """Bring back from the Past sheet: from the 30-day archive if it's there, else from the log."""
    if undo_note(iid):
        return True
    with _lock:
        x = next((x for x in past_load() if x["id"] == iid and x["kind"] == "note"), None)
        if not x:
            return False
        state["notes"].append({"id": x["id"], "text": x["text"], "added": x.get("added") or time.time()})
        save()
    past_drop({iid})
    return True


def done_note(nid):
    """Moves a note to the archive (kept 30 days) so it can be restored, and to the Past log for good."""
    with _lock:
        gone = [n for n in state["notes"] if n["id"] == nid]
        state["notes"] = [n for n in state["notes"] if n["id"] != nid]
        arch = state.setdefault("done_notes", []) + [dict(n, done=time.time()) for n in gone]
        state["done_notes"] = [n for n in arch if time.time() - n["done"] < 30 * 86400][-50:]
        save()
        for n in gone:
            past_add("note", n["text"], time.time(), n["id"], n.get("added"))
    return gone[0] if gone else None


def undo_note(nid):
    with _lock:
        back = [n for n in state.get("done_notes", []) if n["id"] == nid]
        state["done_notes"] = [n for n in state.get("done_notes", []) if n["id"] != nid]
        for n in back:
            n.pop("done", None)
            state["notes"].append(n)
        save()
    past_drop({n["id"] for n in back})
    return back[0] if back else None


def update_note(nid, text):
    with _lock:
        for n in state["notes"]:
            if n["id"] == nid:
                n["text"] = text
        save()


def update_reminder(rid, due=None, text=None):
    with _lock:
        for r in state["reminders"]:
            if r["id"] == rid:
                if due:
                    r["due"] = due.timestamp()
                if text:
                    r["text"] = text
        save()


MANAGE_STOP = set("the a an my note notes reminder reminders delete remove clear cancel drop erase scrap forget mark done finished "
                  "tick cross off edit change update rename move reschedule push to from for about of on at in with that this "
                  "can you please pls it is one and also add put append into".split())


def pick(items, text, key, sure=False):
    """Which note/reminder he means: by number ("note 2", "the second one") or by the words they share.
    sure=True: only a clear match (two shared words, or every word he used), never a lone word in passing."""
    t = text.lower()
    m = re.search(r"\b(?:note|reminder|number|no\.?|#)\s*(\d+)\b|\b(\d+)(?:st|nd|rd|th)? (?:note|reminder|one)\b", t)
    order = {"first": 1, "second": 2, "third": 3, "fourth": 4, "fifth": 5, "last": len(items)}
    n = int(m[1] or m[2]) if m else next((v for k, v in order.items() if re.search(rf"\b{k}\b", t)), None)
    if n and 1 <= n <= len(items):
        return items[n - 1]
    words = {w for w in re.findall(r"[a-z0-9]+", t) if w not in MANAGE_STOP and len(w) > 2}
    stem = lambda w: w[:5]
    best, score = None, 0
    for it in items:
        have = {stem(w) for w in re.findall(r"[a-z0-9]+", key(it).lower())}
        sc = sum(1 for w in words if stem(w) in have)
        if sc > score:
            best, score = it, sc
    return best if not sure or score >= 2 or score == len(words) else None


def manage_notes(text):
    t = text.lower()
    notes = state["notes"]
    if not notes:
        return send("📝 You don't have any notes.")
    if re.search(r"\b(clear|delete|remove|wipe) (all|every|all my)( of my)? notes\b", t):
        return send(f"🗑 Clear all {len(notes)} notes? (You can still undo each one.)", [[B("Yes, clear all", "notes-clear!"), B("Cancel", "noop")]])
    target = pick(notes, text, lambda n: n["text"])
    if not target:
        return send("📝 Which note do you mean?", [[B(f"{i}. {n['text'][:30]}", f"note-pick:{n['id']}")] for i, n in enumerate(notes, 1)])
    if re.search(r"\b(delete|remove|clear|drop|erase|scrap|forget|done|finished|tick|cross(ed)? off|completed?|get rid|ditch)\b|"
                 r"(don'?t|do not|no longer) need|not needed|not relevant", t) and \
            not re.search(r"\b(add|append|put|include|change|edit|update|rename|replace)\b", t):
        if not pick(notes, text, lambda n: n["text"], sure=True):
            return send("📝 Which note do you mean?", [[B(f"{i}. {n['text'][:30]}", f"note-pick:{n['id']}")] for i, n in enumerate(notes, 1)])
        done_note(target["id"])
        return send(f"🗑 Removed: <i>{esc(target['text'])}</i>", [[B("↩️ Undo", f"note-undo:{target['id']}"), B("📝 All notes", "notes")]])
    # Edit or add to a note: let the AI rewrite just that note
    typing()
    try:
        j = llm_json(f'Note: "{target["text"]}"\nInstruction: "{text}"\nApply the instruction to the note. Keep everything else the same. '
                     'Reply JSON {"note": "the updated note"}', num_predict=200)
        new = (j.get("note") or "").strip()
    except Exception:
        new = ""
    if not new or new == target["text"]:
        return send("📝 I couldn't work out the change. Try: <i>change note 1 to …</i>")
    old = target["text"]
    update_note(target["id"], new)
    state.setdefault("note_undo", {})[target["id"]] = old
    send(f"✏️ Updated note:\n<i>{esc(new)}</i>", [[B("↩️ Undo", f"note-revert:{target['id']}"), B("📝 All notes", "notes")]])


def manage_reminders(text):
    t = text.lower()
    rs = sorted(state["reminders"], key=lambda r: r["due"])
    if not rs:
        return send("⏰ You don't have any reminders.")
    if re.search(r"\b(clear|delete|remove|cancel) (all|every|all my)( of my)? reminders\b", t):
        return send(f"🗑 Cancel all {len(rs)} reminders?", [[B("Yes, cancel all", "rem-clear!"), B("Keep them", "noop")]])
    by_time = None
    if tm := re.search(r"\b(\d{1,2})(?:[:.](\d{2}))? ?(am|pm)\b", t):
        h = int(tm[1]) % 12 + (12 if tm[3] == "pm" else 0)
        mins = int(tm[2] or 0)  # "11pm" means 23:00, not 23:30
        by_time = [r for r in rs if (datetime.fromtimestamp(r["due"], TZ).hour, datetime.fromtimestamp(r["due"], TZ).minute) == (h, mins)]
    moving = re.search(r"\b(move|reschedule|push|change|shift|postpone|make it)\b", t)
    target = None
    if by_time and not moving:
        target = by_time[0] if len(by_time) == 1 else None
    target = target or pick(rs, re.sub(r"\bto\b.*$", "", t) if moving else t, lambda r: r["text"], sure=True)
    if not target:
        return send("⏰ Which reminder do you mean?", [[B(f"{r['text'][:34]}", f"rem-pick:{r['id']}")] for r in rs])
    if moving:
        when, _, _ = parse_when(re.split(r"\bto\b", t, maxsplit=1)[-1] if " to " in t else t)
        if not when:
            return send("⏰ To when? Try: <i>move the visa reminder to 10:30pm</i>")
        update_reminder(target["id"], due=when)
        return send(f"⏰ Moved to <b>{nice_when(when)}</b>: <i>{esc(target['text'])}</i>", [[B("⏰ All reminders", "reminders")]])
    del_reminder(target["id"])
    state.setdefault("rem_undo", {})[target["id"]] = target
    send(f"❌ Cancelled: <i>{esc(target['text'])}</i> ({nice_when(datetime.fromtimestamp(target['due'], TZ))})",
         [[B("↩️ Undo", f"rem-undo:{target['id']}"), B("⏰ All reminders", "reminders")]])


WEEKDAYS = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]


def parse_when(text):
    """Common phrasings: 'in 20 min', 'at 6pm', 'tomorrow 9am', 'tonight', 'on friday at 3', 'every day at 8'."""
    t, base = text.lower(), now()
    used = []
    repeat = None
    if m := re.search(r"\bevery ?day\b|\bdaily\b", t):
        repeat = "daily"; used.append(m[0])
    if re.search(r"\bevery (monday|tuesday|wednesday|thursday|friday|saturday|sunday)\b", t):
        repeat = "weekly"
    if m := re.search(r"\bin (\d+|an?|half an?) ?(min(?:ute)?s?|hours?|hrs?|h|days?)\b", t):
        n = {"a": 1, "an": 1, "half a": 0.5, "half an": 0.5}.get(m[1]) or float(m[1])
        unit = m[2][0]
        delta = timedelta(minutes=n) if unit == "m" else timedelta(hours=n) if unit == "h" else timedelta(days=n)
        return base + delta, repeat, [m[0]]
    hour = minute = None
    tm = None
    if tm := re.search(r"\b(?:at |@ ?|by )?(\d{1,2})(?:[:.](\d{2}))? ?(am|pm|a\.m\.|p\.m\.)", t):
        hour, minute = int(tm[1]) % 12 + (12 if tm[3].startswith("p") else 0), int(tm[2] or 0)
    elif tm := re.search(r"\b(?:at |@ ?|by )(\d{1,2})(?:[:.](\d{2}))?\b", t):
        hour, minute = int(tm[1]), int(tm[2] or 0)
    elif tm := re.search(r"\b(\d{1,2})[:.](\d{2})\b", t):
        hour, minute = int(tm[1]), int(tm[2])
    elif tm := re.search(r"\b(?:at |by |in the |this )?(noon|midday|morning|afternoon|evening|night|tonight)\b", t):
        hour, minute = {"noon": 12, "midday": 12, "morning": 9, "afternoon": 14, "evening": 18, "night": 21, "tonight": 20}[tm[1]], 0
    if tm:
        used.append(tm[0])

    # A day word only counts next to the time ("tomorrow at 9", "at 9 on friday") or at the start,
    # so "at 10pm to pack for my flight tomorrow" stays tonight.
    def near(m):
        return not tm or m.start() < 3 or abs(m.start() - tm.end()) < 14 or abs(tm.start() - m.end()) < 14
    day = base.date()
    dm = next((m for m in re.finditer(r"\b(day after tomorrow|today|tonight|tomorrow)\b", t) if near(m)), None)
    wm = next((m for m in re.finditer(r"\b(?:on |every |next )?(monday|tuesday|wednesday|thursday|friday|saturday|sunday)\b", t) if near(m)), None)
    if dm:
        day += timedelta(2 if dm[1] == "day after tomorrow" else 1 if dm[1] == "tomorrow" else 0); used.append(dm[0])
    elif wm:
        day += timedelta((WEEKDAYS.index(wm[1]) - base.weekday()) % 7 or 7); used.append(wm[0])
    if tm and hour < 12 and not tm[0].rstrip().endswith(("am", "pm", "a.m.", "p.m.")) and tm[1] not in ("noon", "midday", "morning"):
        if "tonight" in t:
            hour += 12
        elif not repeat and day == base.date() and (base.hour, base.minute) >= (hour, minute or 0):
            hour += 12  # "at 6" said after 6am means 6pm
    if hour is None:
        if day == base.date():
            return None, repeat, used
        hour, minute = 9, 0
    when = datetime.combine(day, datetime.min.time(), TZ).replace(hour=min(hour, 23), minute=minute)
    if when <= base and day == base.date():
        when += timedelta(days=1)
    return when, repeat, used


TIME_WORDS = r"\b\d{1,2}(?:[:.]\d{2})? ?(?:am|pm|a\.m\.|p\.m\.)|\b(?:at|by) \d{1,2}(?:[:.]\d{2})?\b|\bin \d+ ?(?:min|hour|hr|day)"
DATE_WORDS = r"\b(jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)[a-z]*\b|\b\d{1,2}(st|nd|rd|th)\b|\b\d{1,2}[/-]\d{1,2}\b|\bnext (week|month|year)\b"  # the rules can't place these: the model does
REFERS = r"\b(same|also|as well|again|both|too|that one|this one|that reminder|previous|last one|each|every \d|and at)\b"


def save_reminders(items, repeat=None):
    """items: [(datetime, task)]. Skips exact duplicates. Returns what was added."""
    added = []
    with _lock:
        for when, task in items:
            task = task.strip(" ,.-") or "Reminder"
            task = task[:1].upper() + task[1:]
            key = re.sub(r"\W+", "", task.lower())[:20]
            if any(abs(r["due"] - when.timestamp()) < 60 and re.sub(r"\W+", "", r["text"].lower())[:20] == key for r in state["reminders"]):
                continue
            rid = uuid.uuid4().hex[:8]
            state["reminders"].append({"id": rid, "text": task, "due": when.timestamp(), "repeat": repeat})
            added.append((rid, when, task))
        save()
    return added


def reminders_from_ai(raw):
    """For messages the quick parser can't handle: dates, several times, or 'the same', 'also', 'again'."""
    existing = ""
    if re.search(REFERS, raw, re.I):  # only then: the list confuses the small model otherwise
        existing = "His existing reminders:\n" + ("\n".join(f"- {datetime.fromtimestamp(r['due'], TZ):%Y-%m-%d %H:%M}: {r['text']}"
                                                          for r in sorted(state["reminders"], key=lambda r: r["due"])) or "(none)") + "\n"
    j = llm_json(f"Now is {now():%A %Y-%m-%d %H:%M}.\n{existing}He said: \"{raw}\"\n\n"
                 "List each reminder he wants: when (YYYY-MM-DD HH:MM, the next time it fits; a date with no time means 09:00; "
                 "dates are day/month; \"the 1st\" means the 1st of the next month) and the task (short, no time words). "
                 "Exactly one entry per time he said. If he refers to an existing reminder (\"the same\", \"that one\", \"again\"), copy its task text exactly. "
                 "A time without am/pm means its next occurrence that fits the task (dinner or 'tonight' means evening).\n"
                 'Reply JSON: {"reminders": [{"when": "YYYY-MM-DD HH:MM", "task": "..."}]}', num_predict=200)
    out = []
    for r in j.get("reminders", []):
        when = datetime.strptime(r["when"].strip()[:16], "%Y-%m-%d %H:%M").replace(tzinfo=TZ)
        if when <= now() and when.date() == now().date():
            when += timedelta(days=1)  # "7am" said in the evening means tomorrow morning
        if when > now():
            out.append((when, r.get("task") or "Reminder"))
    return out


ASKED = r"^(please |can you |could you )?(remind me|notify me|ping me|alert me|nudge me|wake me( up)?|set an? (reminder|alarm)( for)?|reminder:?|remember to)(\s+(to|that)\b)?\s*"


def quick_plan(text):
    """Rules only, no AI: (raw, when, repeat, task, tricky, asked)."""
    raw = text.strip()
    raw = re.sub(r"^(please )?(don'?t let me forget|make sure i( don'?t forget)?)\b", "remind me", raw, flags=re.I)
    asked = bool(re.match(ASKED, raw, re.I))
    body = re.sub(ASKED, "", raw, flags=re.I)
    when, repeat, used = parse_when(body)
    task = body
    for u in used:  # parse_when matched them lowercased: "Noon" or "6PM" from dictation must go too
        task = re.sub(re.escape(u), " ", task, count=1, flags=re.I)
    task = re.sub(r"\b(every ?day|daily|every|on|at|to|that|about|for)\s*$", "", re.sub(r"\s+", " ", task).strip(" ,.-")).strip(" ,.-")
    task = re.sub(r"^(to|that)\s+", "", task, flags=re.I)
    if not task and re.match(r"^(please )?(wake me|set an? alarm)", raw, re.I):
        task = "Time to wake up! ☀️"
    tricky = (len(re.findall(TIME_WORDS, body, re.I)) > 1 or re.search(REFERS, body, re.I) or re.search(DATE_WORDS, body, re.I)
              or not when or len(task) < 3 or re.match(r"^(for|,|and)\b", task, re.I))
    return raw, when, repeat, task, tricky, asked


def plan_reminders(text, chat=True):
    """Works out what to remind and when. Returns ([(datetime, task)], repeat); empty list if no time was found."""
    raw, when, repeat, task, tricky, _ = quick_plan(text)
    if not tricky:
        return [(when, task)], repeat
    if chat:
        typing()
    try:
        return reminders_from_ai(raw), None
    except Exception:
        return [], None


def add_reminder(text):
    items, repeat = plan_reminders(text)
    if not items:
        return send("⏰ Sorry, I didn't catch when. Try: <i>remind me at 6pm to call mum</i> or <i>remind me in 20 minutes to check the oven</i>.")
    added = save_reminders(items, repeat)
    if not added:
        return send("⏰ You already have that reminder.", [[B("⏰ All reminders", "reminders")]])
    if len(added) == 1:
        rid, w, t = added[0]
        return send(f"⏰ Got it. I'll remind you <b>{nice_when(w)}</b>{' and repeat ' + repeat if repeat else ''}:\n<i>{esc(t)}</i>",
                    [[B("❌ Cancel", f"rem-del:{rid}"), B("⏰ All reminders", "reminders")]])
    send("⏰ Got it. I'll remind you:\n" + "\n".join(f"• <b>{nice_when(w)}</b>: {esc(t)}" for _, w, t in added),
         [[B("⏰ All reminders", "reminders")]])


def reminders_view(msg=None):
    rs = sorted(state["reminders"], key=lambda r: r["due"])
    if not rs:
        text = "⏰ <b>Reminders</b>\nNo reminders set.\n\nJust type something like <i>remind me tomorrow at 9 to pack</i>."
        return edit(msg, text) if msg else send(text)
    text = "⏰ <b>Reminders</b>\n" + "\n".join(
        f"• {nice_when(datetime.fromtimestamp(r['due'], TZ))}{' 🔁' if r.get('repeat') else ''}: {esc(r['text'])}" for r in rs)
    buttons = [[B(f"❌ {r['text'][:30]}", f"rem-del:{r['id']}")] for r in rs]
    edit(msg, text + "\n\n<i>Tap one to cancel it.</i>", buttons) if msg else send(text + "\n\n<i>Tap one to cancel it.</i>", buttons)


def del_reminder(rid):
    with _lock:
        state["reminders"] = [r for r in state["reminders"] if r["id"] != rid]
        save()


def snooze(rid, minutes, text):
    with _lock:
        state["reminders"].append({"id": rid + "s", "text": text, "due": (now() + timedelta(minutes=minutes)).timestamp(), "repeat": None})
        save()


def fire_reminders():
    due = []
    with _lock:
        for r in list(state["reminders"]):
            if r["due"] <= time.time():
                due.append(dict(r))
                if r.get("repeat"):
                    r["due"] += 86400 if r["repeat"] == "daily" else 7 * 86400
                else:
                    state["reminders"].remove(r)
        if due:
            save()
    for r in due:
        rid = uuid.uuid4().hex[:8]
        with _lock:
            state.setdefault("fired", {})[rid] = r["text"]
            state["fired"] = dict(list(state["fired"].items())[-50:])
            save()
        if not r["text"].startswith("⏰ Time to wake up"):
            past_add("reminder", r["text"], time.time(), rid)
        send(f"⏰ <b>Reminder</b>\n{esc(r['text'])}",
             [[B("✅ Done", f"remdone:{rid}"), B("💤 10 min", f"snooze:{rid}:10"), B("💤 1 hour", f"snooze:{rid}:60")]])
        if not r["text"].startswith("⏰ Time to wake up"):
            nudged("reminder", text=r["text"])

def _routes(router):
    """The dashboard's notes, reminders, goals and quick-capture API."""
    bad = ({"error": "bad request"}, 400)

    @router.get("/past")
    def past(req):
        return past_view()

    @router.get("/notes")
    def notes(req):
        gs = state.get("goals", [])
        with _lock:
            pc = {"reminders": sum(x["kind"] == "reminder" for x in past_load()), "notes": sum(x["kind"] == "note" for x in past_load())}
        return {"notes": state["notes"], "past": pc, "goals": [g for g in gs if not g.get("achieved")],
                "achieved": sorted((g for g in gs if g.get("achieved")), key=lambda g: -g["achieved"]), "reminders": [
                    {**r, "when": nice_when(datetime.fromtimestamp(r["due"], TZ))} for r in sorted(state["reminders"], key=lambda r: r["due"])]}

    @router.post("/notes")
    def notes_add(req):
        b = req.json()
        if not b.get("text", "").strip():
            return bad
        with _lock:
            state["notes"].append({"id": uuid.uuid4().hex[:8], "text": b["text"].strip()[:300], "added": time.time()})
            save()
        return {"ok": True}

    @router.post("/capture/peek")
    def capture_peek(req):
        text = req.json().get("text", "").strip()[:300]
        _, when, repeat, task, tricky, asked = quick_plan(text) if text else (0, None, None, "", 0, False)
        if text and re.match(GOAL_ADD, text, re.I):
            return {"kind": "goal"}
        if not (when or asked) or re.match(r"^(note|notes|idea)\b", text, re.I):  # "note: 3pm call went well" stays a note
            return {"kind": "note"}
        return {"kind": "reminder", "task": task, "sure": not tricky, "need": not when and not re.search(DATE_WORDS, text, re.I),
                "when": when and nice_when(when) + (f", repeats {repeat}" if repeat else "")}

    router.add("POST", "/capture/save", lambda req: capture_save(req.json()))
    router.add("POST", "/goals/edit", lambda req: (lambda b: {"ok": bool(edit_goal(b.get("id", ""), b.get("text", "")))})(req.json()))
    router.add("POST", "/goals/delete", lambda req: {"ok": bool(delete_goal(req.json().get("id", "")))})
    router.add("POST", "/goals/achieve", lambda req: (lambda b: {"ok": bool(achieve_goal(b.get("id", ""), bool(b.get("undo"))))})(req.json()))
    router.add("POST", "/past/restore", lambda req: {"ok": past_restore(req.json().get("id", ""))})

    @router.post("/notes/done")
    def notes_done(req):
        done_note(req.json().get("id", ""))
        return {"ok": True}

    @router.post("/reminders")
    def reminders_add(req):
        b = req.json()
        if not b.get("text", "").strip():
            return bad
        text = b["text"].strip()[:300]
        if b.get("when"):  # picked in the time picker (local time, "YYYY-MM-DDTHH:MM")
            when = safe(lambda: datetime.fromisoformat(b["when"]).replace(tzinfo=TZ))
            items, repeat = ([(when, re.sub(r"^(remind me( to)?|reminder:?)\s*", "", text, flags=re.I) or text)] if when else []), None
        else:
            items, repeat = plan_reminders(text, chat=False)
        items = [(w, t) for w, t in items if w and w > now() - timedelta(minutes=1)]
        if not items:
            return {"ok": False, "error": "I couldn't tell when. Add a time, like \u201cat 6pm\u201d or \u201cin 20 minutes\u201d, or pick one below."}
        added = save_reminders(items, repeat)
        if not added:
            return {"ok": False, "error": "You already have that reminder."}
        return {"ok": True, "added": [{"text": t, "when": nice_when(w) + (f", repeats {repeat}" if repeat else "")} for _, w, t in added]}

    @router.post("/reminders/delete")
    def reminders_delete(req):
        del_reminder(req.json().get("id", ""))
        return {"ok": True}


def register(app):
    host.need(globals(), "B", "TZ", "_lock", "edit", "llm_json", "nice_when", "nudged", "save", "send", "state", "typing")
    _routes(app.router)
