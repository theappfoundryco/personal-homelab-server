"""Chat with the local model: streaming replies into one Telegram message, the context it is given, and the feature tags it can hand off to.
Things that live in the app or in modules are reached through core.host, bound once by bind() when the app has provided them."""
import json, re, time
from datetime import datetime, timedelta
from urllib.request import Request, urlopen

from core import host
from core.helpers import esc, now, safe, strip_tags

NEEDS = ("CAPS", "MODEL", "OLLAMA", "NAME", "OWNER", "TZ", "ai_keep", "count_tokens", "edit", "send", "tg", "typing", "location", "weather_lines", "flights",
         "nice_when", "has_calendar", "day_events", "event_line", "state", "_lock", "save", "search", "add_reminder", "full_briefing", "live_digest",
         "server", "my_day", "weather", "sports", "notes_view", "reminders_view")


def bind():
    """Called by the app once everything in NEEDS has been provided."""
    host.need(globals(), *NEEDS)
    global SYSTEM
    SYSTEM = (f"You are {NAME}'s friendly personal assistant, running privately on his home server. "
              "Be warm, clear and brief: usually 1 to 4 short sentences, or a few bullets. Plain language, no tables, no jargon. "
              "Use the context when it helps, and never invent events or facts about his schedule. "
              "You cannot set reminders or change anything yourself; never claim you did.")


def llm_stream(messages, images=None, num_predict=450, temperature=0.6, kind="Chat"):
    if images:
        messages[-1]["images"] = images
    body = {"model": MODEL, "messages": messages, "stream": True, "think": False, "keep_alive": ai_keep(),
            "options": {"temperature": temperature, "num_ctx": 6144, "num_predict": num_predict}}
    req = Request(f"{OLLAMA}/api/chat", json.dumps(body).encode(), {"Content-Type": "application/json"})
    with urlopen(req, timeout=600) as r:
        for line in r:
            j = json.loads(line)
            if j.get("message", {}).get("content"):
                yield j["message"]["content"]
            if j.get("done"):
                return count_tokens(kind, j)


def md_to_html(s):
    s = esc(s)
    s = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", s)
    s = re.sub(r"(?<![\w*])\*(?!\s)(.+?)(?<!\s)\*(?![\w*])", r"<i>\1</i>", s)
    s = re.sub(r"`([^`\n]+)`", r"<code>\1</code>", s)
    s = re.sub(r"^#{1,6}\s*(.+)$", r"<b>\1</b>", s, flags=re.M)
    s = re.sub(r"^\s*[-*]\s+", "• ", s, flags=re.M)
    return s


REFUSAL = (r"real[- ]time|live (data|information|updates|market)|don'?t have (access|the ability|information|live)|"
           r"can'?t (browse|access|check)|not able to (access|browse)|knowledge cutoff|as of my (last|latest)|recommend checking|\[\[search")


def stream_to_chat(chunks, prefix="", footer="", buttons=None, intercept=None, late_tags=None, on_refusal=None):
    """Streams LLM output into one Telegram message, editing it at most about once a second."""
    out, msg, last = "", None, 0
    for c in chunks:
        out += c
        s = out.strip()
        if intercept and (not s or (s.startswith("[") and len(s) < 20)):
            continue
        if intercept:
            if hit := intercept(s):
                return hit()
            intercept = None
        if on_refusal and len(out) < 400 and re.search(REFUSAL, out, re.I):
            if msg:
                tg("deleteMessage", chat_id=OWNER, message_id=msg["message_id"])
            return on_refusal()
        if time.time() - last > 1.1:
            last = time.time()
            body = prefix + md_to_html(out) + " ▍"
            msg = edit(msg, body) if msg else send(body)
    if intercept and (hit := intercept(out.strip())):
        return hit()
    tail = re.search(r"\[\[(\w+)\]\]\s*$", out)
    if tail and late_tags and f"[[{tail[1]}]]" in late_tags:
        out = out[:tail.start()]
        if msg:
            edit(msg, prefix + md_to_html(out.strip()))
        return late_tags[f"[[{tail[1]}]]"]()
    final = prefix + (md_to_html(out.strip()) or "(no answer)") + footer
    edit(msg, final, buttons) if msg else send(final, buttons)
    return out.strip()


def context():
    parts = [f"Now: {now():%A %d %B %Y, %H:%M} (your time). {NAME} is in {location()['city']}."]
    loc = location()
    w = safe(lambda: strip_tags(" ".join(weather_lines(loc)[:3])))
    if w:
        parts.append(f"Weather in {loc['city']} (where he is now): " + w)
    tl = location(now().date() + timedelta(1))
    if tl["city"] != loc["city"]:
        parts.append(f"Tomorrow he will be in {tl['city']}.")
    fl = flights(2)
    if fl:
        parts.append("Flights: " + "; ".join(f"{f['title']} departs {nice_when(f['start'])}, leave home by {f['leave_by']:%-I:%M %p}" for f in fl))
    if has_calendar():
        today, tom = now().date(), now().date() + timedelta(1)
        parts.append("Today: " + ("; ".join(strip_tags(event_line(e, False))[2:] for e in day_events(today)) or "nothing"))
        parts.append("Tomorrow: " + ("; ".join(strip_tags(event_line(e, False))[2:] for e in day_events(tom)) or "nothing"))
    if state["notes"]:
        parts.append("Notes: " + "; ".join(n["text"] for n in state["notes"][:10]))
    if state["reminders"]:
        parts.append("Reminders: " + "; ".join(f"{nice_when(datetime.fromtimestamp(r['due'], TZ))} {r['text']}" for r in state["reminders"][:10]))
    return "\n".join(parts)


TAGS = "[[search]] (anything needing current info: news, prices, scores, results, events, facts that change) [[remind]] (set a reminder, alarm or notification) [[brief]] [[fresh]] [[news]] [[server]] [[myday]] [[weather]] [[sports]] [[notes]] [[reminders]]"


def cannot(what, needs=("ollama",)):
    """The shared reply when a feature's dependency is missing: says what cannot be done yet and what to do about it."""
    gone = CAPS.missing(list(needs))
    return send(f"🤖 I can't {esc(what)} yet. {esc(' '.join(gone))}") if gone else None


def chat(text):
    if cannot("chat"):
        return
    typing()
    tags = {"[[search]]": lambda: search(text), "[[remind]]": lambda: add_reminder(text), "[[brief]]": full_briefing, "[[fresh]]": full_briefing, "[[news]]": live_digest,
            "[[server]]": server, "[[myday]]": my_day, "[[weather]]": weather, "[[sports]]": sports,
            "[[notes]]": notes_view, "[[reminders]]": reminders_view}
    system = (SYSTEM + f"\nIf he is clearly asking for one of these features, reply with ONLY its tag: {TAGS}.\n\n" + context())
    msgs = [{"role": "system", "content": system}, *state["history"][-8:], {"role": "user", "content": text}]
    intercept = lambda s: tags.get(s.split()[0]) if s.startswith("[[") else None
    try:
        out = stream_to_chat(llm_stream(msgs), intercept=intercept, late_tags={"[[remind]]": tags["[[remind]]"], "[[search]]": tags["[[search]]"]},
                             on_refusal=lambda: search(text))
    except OSError:  # the AI went away mid-answer
        CAPS.items["ollama"]._val = None
        return send("🤖 I can't chat right now, the AI stopped answering. " + esc(" ".join(CAPS.missing(["ollama"]))))
    if isinstance(out, str) and re.search(r"real[- ]time|live (data|information|updates)|don'?t have (access|the ability|information)|"
                                          r"can'?t (browse|access|check)|not able to (access|browse)|knowledge cutoff|as of my (last|latest)|"
                                          r"recommend checking", out, re.I):
        send("🔎 Let me look that up for you…", silent=True)
        return search(text)
    if isinstance(out, str):
        with _lock:
            state["history"] = (state["history"] + [{"role": "user", "content": text}, {"role": "assistant", "content": out}])[-12:]
            save()
