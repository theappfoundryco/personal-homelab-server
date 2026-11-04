"""Telegram side of the app: what a message or a button press means, and what runs for it. Things that live in the app or in modules
are reached through core.host, bound once by bind(). The classifier is called through core.intent so it can be swapped in tests."""
import re, time, traceback, uuid
from datetime import datetime, timedelta

from core import host, intent as _intent
from core.helpers import esc, now, t12

NEEDS = ("B", "BARE_DONE", "GOAL_ADD", "HOME", "KEYBOARD", "NAME", "OWNER", "TG", "TOPIC_GENERIC", "TOPIC_WORDS", "TZ", "_lock", "achieve_goal", "add_goal", "add_note", "add_reminder", "app_buttons", "app_name", "bare_done", "chat", "cricket_items", "del_reminder", "detect_topic", "done_note", "edit", "evening", "events_for", "extras", "feed_items", "find_app", "flight_text", "flights", "full_briefing", "fx", "gmail", "goal_text", "goals_view", "host_action", "ics_text", "journal", "journal_day", "journal_save", "live_digest", "logs", "manage_notes", "manage_reminders", "med_tick", "morning_briefing", "my_day", "news_search", "nice_when", "note_text", "notes_view", "past_drop", "photo", "reminders_view", "restart_app", "save", "search", "send", "server", "sg", "sg_save", "shared_location", "snooze", "sports", "state", "stored", "suggested_tags", "summarise_link", "summarise_topic", "tg", "topic_news", "typed_meds", "undo_note", "unload_ai", "update_note", "voice", "weather", "weather_data", "weekly", "world_clock")


def bind():
    """Called by the app once everything in NEEDS has been provided."""
    host.need(globals(), *NEEDS)
    global HELP
    HELP = f"""👋 Hi {NAME}! Just talk to me like a person. Some ideas:

☀️ <i>brief me</i> (fresh briefing + news) or <i>this morning's briefing</i>
📍 Share your location (📎 → Location) when you travel
📅 <i>what's on tomorrow?</i>
📝 <i>note buy a charger</i>
⏰ <i>remind me at 6pm to call mum</i>
🌦 <i>will it rain?</i>
💱 <i>100 sgd to inr</i>
🔎 <i>search best pizza in {HOME["city"]}</i>
🔗 Paste any link or YouTube video to get a summary
📸 Send a photo (receipt, menu, sign) and ask about it
🎤 Send a voice note instead of typing
🖥 <i>is the server ok?</i> • <i>restart n8n</i>

Or tap the buttons below. Anything else, just ask!"""


FRESH = r"\b(fresh|new|newer|update|updated|latest|current|now|rebuild|regenerate|re-?run|another)\b"
URL = re.compile(r"https?://\S+")


FILLER = (r"^(hey|hi|hello|yo|ok|okay|so|um|bot|buddy|please|pls|plz|kindly|can you|could you|would you|will you|can u|could u|"
          r"i want to|i want you to|i need you to|i'?d like to|i'?d like you to|just)[\s,!.]+")


def fresh_data():
    """He's asking now, so answer with live data, not cached copies."""
    for fn in (ics_text, events_for, weather_data, cricket_items, feed_items, extras):
        fn.clear()


def news_request(text, t):
    if re.search(r"this morning|morning'?s|7 ?am|earlier|resend", t):
        return stored("news")
    subject = re.sub(r"(?i)\b(give|show|tell|get|send|me|my|the|a|an|any|some|latest|recent|today'?s?|this|morning'?s?|news|headlines?|"
                     r"updates?|on|about|for|of|in|from|with|what'?s|whats|what|is|are|happening|going|new|please|pls|now|fresh|again|"
                     r"did|i|miss|anything)\b", " ", text)
    subject = re.sub(r"\s+", " ", re.sub(r"[^\w\s'-]", " ", subject)).strip()
    # A specific subject beats a broad topic: "India news" -> India headlines, "news about CJP India" -> search CJP.
    if topic := detect_topic(t):
        rest = re.sub(TOPIC_GENERIC[topic], " ", subject.lower())
        rest = re.sub(r"\b(sports?|world|national|international|politics|today|and)\b", " ", rest)
        if len(re.sub(r"\W", "", rest)) < 3:
            return topic_news(topic)
    if len(subject) >= 3:
        return news_search(subject)
    return live_digest()


def sports_request(t):
    if re.search(dict(TOPIC_WORDS)["cricket"] + r"|\bindia\b|live score", t) and not re.search(dict(TOPIC_WORDS)["f1"], t):
        return topic_news("cricket")
    if re.search(dict(TOPIC_WORDS)["f1"] + r"|\brace\b|standings|table", t):
        return topic_news("f1")
    return sports()


def dispatch(intent, text, t):
    if intent == "answer":
        return search(text)
    if intent == "chat":
        return chat(text)
    if intent == "briefing":
        return morning_briefing() if re.search(r"this morning|morning'?s|7 ?am|earlier|again|resend|that was sent|old one", t) else full_briefing()
    if intent == "news":
        return news_request(text, t)
    if intent == "sports":
        return sports_request(t)
    if intent == "weather":
        return weather(text)
    if intent == "my_day":
        return my_day()
    if intent == "evening_plan":
        return evening()
    if intent == "weekly_report":
        return weekly()
    if intent == "server":
        return server()
    if intent == "restart_app":
        app = find_app(t)
        return send(f"🔄 Restart <b>{esc(app_name(app))}</b>?", [[B("Yes, restart", f"restart!:{app}"), B("Cancel", "noop")]]) if app \
            else send("🔄 Which app should I restart?", app_buttons("restart"))
    if intent == "logs":
        app = find_app(t)
        return logs(app) if app else send("📜 Whose logs?", app_buttons("logs"))
    if intent == "free_ai_memory":
        return unload_ai()
    if intent == "reboot_server":
        return send("⏻ Restart the whole server? Everything will be offline for about 2 minutes.", [[B("Yes, restart", "reboot!"), B("Cancel", "noop")]])
    if intent == "manage_notes":
        if re.search(r"^restore (my )?notes", t):
            with _lock:
                back = state.get("done_notes", [])[-10:]
                for n in back:
                    n.pop("done", None)
                state["notes"] += back; state["done_notes"] = state.get("done_notes", [])[:-10]; save()
            past_drop({n["id"] for n in back})
            return send(f"↩️ Restored {len(back)} note(s).", [[B("📝 All notes", "notes")]])
        return manage_notes(text)
    if intent == "manage_reminders":
        return manage_reminders(text)
    if intent == "add_goal":
        return add_goal(text)
    if intent == "add_note":
        return add_note(note_text(text))
    if intent == "show_goals":
        return goals_view()
    if intent == "show_notes":
        return notes_view()
    if intent == "add_reminder":
        return add_reminder(text)
    if intent == "show_reminders":
        return reminders_view()
    if intent == "currency":
        return fx(t)
    if intent == "flights":
        fl = flights(3)
        return send("\n\n".join(flight_text(f) for f in fl) if fl else "✈️ No flights in your calendar for the next 3 days.")
    if intent == "email":
        return gmail()
    return chat(text)


EXACT = {  # keyboard buttons and commands: no guessing needed
    "briefing": "briefing", "/brief": "briefing", "/fresh": "briefing", "/morning": "morning", "my day": "my_day", "/cal": "my_day", "/tomorrow": "evening_plan", "tomorrow": "evening_plan",
    "/clock": "clock", "clock": "clock", "world clock": "clock", "world time": "clock", "time zones": "clock",
    "goals": "show_goals", "/goals": "show_goals", "show goals": "show_goals", "my goals": "show_goals", "show my goals": "show_goals",
    "notes": "show_notes", "/notes": "show_notes", "reminders": "show_reminders", "/reminders": "show_reminders",
    "news": "news", "/news": "news", "sports": "sports", "weather": "weather", "/weather": "weather", "server": "server",
    "/stats": "server", "stats": "server",
}
WRONG = r"^(no|nope|wrong|that'?s (not|wrong)|not (that|what i (asked|wanted|meant))|you misunderstood|i meant something else)\b"


def route(text):
    text = re.sub(r"^[^\w/@$₹]+\s*", "", text.strip())  # keyboard emoji like "☀️ "
    while re.match(FILLER, text, re.I):  # "hey, can you please remind me…" -> "remind me…"
        text = re.sub(FILLER, "", text, count=1, flags=re.I)
    t = text.lower().strip()
    fresh_data()
    if re.match(GOAL_ADD, text, re.I) and len(goal_text(text)) > 2:  # "goal: learn Dutch", "my life goal is…"
        return add_goal(text)
    if t in ("/start", "/help", "help", "hi", "hello", "hey", "menu", "what can you do", "what can you do?"):
        return send(HELP, keyboard=KEYBOARD)
    if t in ("/reset", "forget"):
        with _lock:
            state["history"] = []; save()
        return send("🧽 Fresh start. I've forgotten our chat.")
    if re.match(WRONG, t) and state.get("last_text"):
        rows, row = [], []
        for k, name in _intent.INTENT_NAMES.items():
            row.append(B(name, f"learn:{k}"))
            if len(row) == 2:
                rows.append(row); row = []
        rows += [row] if row else []
        return send(f"Sorry! What did you want when you said <i>“{esc(state['last_text'][:120])}”</i>? I'll remember for next time.", rows)
    if re.match(BARE_DONE, t):
        return bare_done()
    if (m := typed_meds(t)):
        return send(m)
    if (u := URL.search(text)):
        rest = URL.sub("", text).strip()
        return summarise_link(u.group(0).rstrip(").,"), rest if len(rest) > 8 else None)
    if re.match(r"^/?suggested ?tags?\b|^(show |any |see )?(my )?(suggested|new) (journal )?tags\b", t):
        return suggested_tags()
    if t in EXACT:
        intent, how = EXACT[t], "exact"
        if intent == "morning":
            return morning_briefing()
        if intent == "clock":
            return world_clock()
        if intent == "news":
            return live_digest()
        if intent == "sports":
            return sports()
    elif re.match(r"^(search|google|look ?up)\b", t):
        return search(re.sub(r"^(search( for)?|google|look ?up)\s*", "", text.strip(), flags=re.I))
    elif re.search(r"\b(delete|remove|clear|cancel|drop|erase|scrap|edit|change|update|rename|move|reschedule|postpone|"
                   r"cross off|tick off|mark)\b.*\b(note|notes|reminder|reminders)\b|\badd .+ to (the |my )?.*\bnote\b|"
                   r"\b(note|reminder)s? \d+\b.*\b(done|delete|remove|cancel)\b|^restore (my )?notes", t):
        intent, how = ("manage_reminders" if re.search(r"\breminders?\b", t) else "manage_notes"), "prefix"
    elif (re.match(r"^(note|notes?:)\b", t) and not re.match(r"^notes?$", t)) or re.match(r"^((make|take|save|add|keep|create) (a |me a )?note( of| that| about|:)?|note (this|that|down)|jot( this| it)?( down)?|write (this |it |that )?down|remember (this|that)|save (this|that)( for later)?)\b", t):
        intent, how = "add_note", "prefix"
    elif re.match(r"^(remind me|notify me|ping me|alert me|nudge me|wake me|set an? (reminder|alarm)|reminder:|remember to|don'?t let me forget)\b", t):
        intent, how = "add_reminder", "prefix"
    else:
        try:
            intent, how = _intent.classify(text)
        except Exception as e:
            print("classify failed:", e)
            intent, how = "chat", "fallback"
    print(f"route: {text[:60]!r} -> {intent} ({how})")
    with _lock:
        state["last_text"], state["last_intent"] = text, intent
    return dispatch(intent, text, t)


def on_callback(q):
    tg("answerCallbackQuery", callback_query_id=q["id"])
    print(f"tap: {q.get('data', '')}")
    data, msg = q.get("data", ""), q.get("message")
    if data.startswith("learn:"):
        intent, text = data[6:], state.get("last_text", "")
        if text:
            _intent.learn(text, intent)
            edit(msg, f"👍 Got it. Next time <i>“{esc(text[:80])}”</i> means {esc(_intent.INTENT_NAMES[intent])}.")
            return dispatch(intent, text, text.lower())
        return
    if data.startswith("jtag:"):
        _, act, t = data.split(":", 2)
        with _lock:
            lst = journal.setdefault("extra_tags" if act == "add" else "ignored_tags", [])
            if t not in lst:
                lst.append(t)
            journal_save()
        return edit(msg, f"🏷️ Added <b>{esc(t)}</b>. New entries can be tagged with it from now on." if act == "add"
                    else f"🙈 Ignored <b>{esc(t)}</b>. It won't be suggested again.")
    if data.startswith("jsnz:"):
        m = int(data[5:])
        with _lock:
            state.setdefault("journal", {}).update(next=time.time() + m * 60, auto=False, msg=None, day=journal_day())
            save()
        return edit(msg, f"💤 I'll remind you to write your <b>journal</b> at {t12(now() + timedelta(minutes=m))}.")
    if data.startswith("sgtake:"):
        _, cid, d = data.split(":", 2)
        with _lock:
            sg["log"].setdefault(d, {})[cid] = True
            sg_save()
        c = next((x for x in sg["courses"] if x["id"] == cid), None)
        return edit(msg, f"✅ <b>{esc(c['name'] if c else 'Dose')}</b> marked as taken. Nice.")
    if data.startswith("sgmed:"):
        _, act, sid, d = data.split(":", 3)
        sl = next((x for x in sg["slots"] if x["id"] == sid), None)
        if not sl:
            return
        if act == "done":
            if (state.get("last_nudge") or {}).get("sid") == sid:
                state.pop("last_nudge", None)
            return edit(msg, med_tick(sl, d))
        with _lock:
            state.setdefault("med_snooze", {})[f"{sid}:{d}"] = time.time() + int(act) * 60
            save()
        return edit(msg, f"💤 I'll remind you about <b>{esc(sl['label'])}</b> ({esc(', '.join(sl['items']))}) at {t12(now() + timedelta(minutes=int(act)))}.")
    if data == "jskip":
        with _lock:
            state.setdefault("journal", {}).update(skip=True, next=None, msg=None)
            save()
        return edit(msg, "👍 Skipping tonight. See you tomorrow.")
    if data == "noop":
        return tg("editMessageReplyMarkup", chat_id=OWNER, message_id=msg["message_id"], reply_markup={"inline_keyboard": []})
    if data.startswith("stored:"):
        return stored(data[7:])
    if data.startswith("fresh:"):
        return full_briefing() if data == "fresh:brief" else live_digest()
    if data == "full":
        return full_briefing()
    if data == "news":
        return live_digest()
    if data == "wx":
        return weather()
    if data == "clock":
        return world_clock()
    if data == "server":
        return server()
    if data == "apps:restart":
        return send("🔄 Which app should I restart?", app_buttons("restart"))
    if data == "apps:logs":
        return send("📜 Whose logs?", app_buttons("logs"))
    if data.startswith("restart?:"):
        n = data.split(":", 1)[1]
        return edit(msg, f"🔄 Restart <b>{esc(app_name(n))}</b>?", [[B("Yes, restart", f"restart!:{n}"), B("Cancel", "noop")]])
    if data.startswith("restart!:"):
        return restart_app(data.split(":", 1)[1], msg)
    if data.startswith("logs:"):
        return logs(data[5:])
    if data == "unload":
        return unload_ai()
    if data == "reboot?":
        return send("⏻ Restart the whole server? Everything will be offline for about 2 minutes.", [[B("Yes, restart", "reboot!"), B("Cancel", "noop")]])
    if data == "reboot!":
        edit(msg, "⏻ Restarting the server now. I'll be back in about 2 minutes.")
        return host_action("reboot")
    if data == "notes":
        return notes_view()
    if data == "goals":
        return goals_view()
    if data.startswith("goal-done:"):
        g = achieve_goal(data[10:])
        goals_view(msg)
        return send(f"🏁 Achieved: <i>{esc(g['text'])}</i>. Well done.", [[B("↩️ Undo", f"goal-undo:{g['id']}")]]) if g else None
    if data.startswith("goal-undo:"):
        g = achieve_goal(data[10:], undo=True)
        return edit(msg, f"↩️ Back in your goals: <i>{esc(g['text'])}</i>", [[B("🎯 All goals", "goals")]]) if g else None
    if data.startswith("note-done:"):
        n = done_note(data[10:])
        notes_view(msg)
        return send(f"✓ Done: <i>{esc(n['text'])}</i>", [[B("↩️ Undo", f"note-undo:{n['id']}")]]) if n else None
    if data.startswith("note-undo:"):
        n = undo_note(data[10:])
        return edit(msg, f"↩️ Restored: <i>{esc(n['text'])}</i>", [[B("📝 All notes", "notes")]]) if n else edit(msg, "That note was already restored.")
    if data.startswith("note-revert:"):
        nid = data[12:]
        old = state.get("note_undo", {}).pop(nid, None)
        if old:
            update_note(nid, old)
            return edit(msg, f"↩️ Back to: <i>{esc(old)}</i>", [[B("📝 All notes", "notes")]])
        return
    if data == "notes-clear!":
        for n in list(state["notes"]):
            done_note(n["id"])
        return edit(msg, "🗑 All notes cleared. Ask me to <i>restore my notes</i> if that was a mistake.")
    if data.startswith("note-pick:"):
        n = done_note(data[10:])
        return edit(msg, f"🗑 Removed: <i>{esc(n['text'])}</i>", [[B("↩️ Undo", f"note-undo:{n['id']}")]]) if n else None
    if data.startswith("rem-undo:"):
        r = state.get("rem_undo", {}).pop(data[9:], None)
        if r:
            with _lock:
                state["reminders"].append(r); save()
            return edit(msg, f"↩️ Reminder back: <i>{esc(r['text'])}</i> ({nice_when(datetime.fromtimestamp(r['due'], TZ))})")
        return
    if data == "rem-clear!":
        with _lock:
            state["rem_undo"] = {r["id"]: r for r in state["reminders"]}
            state["reminders"] = []; save()
        return edit(msg, "🗑 All reminders cancelled.")
    if data.startswith("rem-pick:"):
        r = next((x for x in state["reminders"] if x["id"] == data[9:]), None)
        if r:
            del_reminder(r["id"]); state.setdefault("rem_undo", {})[r["id"]] = r
            return edit(msg, f"❌ Cancelled: <i>{esc(r['text'])}</i>", [[B("↩️ Undo", f"rem-undo:{r['id']}")]])
        return
    if data == "reminders":
        return reminders_view()
    if data.startswith("rem-del:"):
        r = next((x for x in state["reminders"] if x["id"] == data[8:]), None)
        if r:
            state.setdefault("rem_undo", {})[r["id"]] = r
        del_reminder(data[8:])
        return edit(msg, "❌ Reminder cancelled.") if "Got it" in (msg.get("text") or "") else reminders_view(msg)
    if data.startswith("snooze:"):
        _, rid, mins = data.split(":")
        text = state.get("fired", {}).get(rid, "Reminder")
        snooze(rid, int(mins), text)
        return edit(msg, f"💤 I'll remind you again at {t12(now() + timedelta(minutes=int(mins)))}:\n<i>{esc(text)}</i>")
    if data.startswith("remdone:"):
        state.pop("last_nudge", None)
        return edit(msg, f"✅ Done:\n<i>{esc(state.get('fired', {}).get(data[8:], 'Reminder'))}</i>")
    if data.startswith("alarm:"):
        when = datetime.fromtimestamp(int(data[6:]), TZ)
        with _lock:
            state["reminders"].append({"id": uuid.uuid4().hex[:8], "text": "⏰ Time to wake up! Have a great day.", "due": when.timestamp(), "repeat": None})
            save()
        return send(f"⏰ I'll wake you {nice_when(when)}. (Telegram can't ring like an alarm, so set your phone alarm too.)")
    if data == "evening":
        return evening()
    if data.startswith("topic:"):
        return topic_news(data[6:])
    if data.startswith("sum:"):
        return summarise_topic(data[4:])
    if data.startswith("nsum:"):
        return search(f"latest news about {data[5:]}")


def handle(update):
    try:
        if not TG.is_owner(update):
            return
        if "callback_query" in update:
            return on_callback(update["callback_query"])
        m = update.get("message") or {}
        chat_id = m.get("chat", {}).get("id")
        if m.get("voice") or m.get("audio"):
            return voice(m)
        if m.get("photo"):
            return photo(m)
        if m.get("location"):
            return shared_location(m)
        text = (m.get("text") or "").strip()
        if text:
            return route(text)
        send("I can read text, photos and voice notes. 🙂")
    except Exception as e:
        traceback.print_exc()
        send(f"😕 Something went wrong: {esc(e)}")
