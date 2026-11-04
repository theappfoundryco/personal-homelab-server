"""Journal: write your day, get a private nightly summary, weekly recap and deep insights."""
import glob
import json
import os
import re
import shutil
import threading
import time
import uuid
from datetime import date, datetime, timedelta

from core import host
from core.helpers import cached, esc, http, now, safe

host.need(globals(), "DATA", "HOME", "NAME", "cfg", "feature")

# ================================================================ journal
JOURNAL_FILE = f"{DATA}/journal.json"  # the old single file, split into JOURNAL_DIR on first start (kept as journal.json.pre-split)
# journal/settings.json      approved and ignored tags
# journal/2026/index.json    every 2026 day: mood, summary, tags, feelings, people, words, times (no text)
# journal/2026/2026-10.json  the words: {"2026-10-22": "..."}
JOURNAL_DIR = f"{DATA}/journal"
JOURNAL_TAGS = ["work", "gym", "health", "sleep", "food", "family", "grief", "friends", "dating", "heartbreak", "therapy", "music", "shows",
                "travel", "celebration"]
# what each topic means, so the small model doesn't guess from the word alone
JOURNAL_TAG_MEANING = {
    "work": "his job, the office, colleagues at work, work from home",
    "gym": "workouts, training, the gym",
    "health": "his body, illness, tiredness, energy, rest days, doctors",
    "sleep": "sleep, lying awake at night, waking up at 2 to 3 AM",
    "food": "meals, eating out, fasting, diet, calories, cravings",
    "family": "parents, siblings, cousins, aunts, uncles, grandparents and other relatives",
    "grief": "mourning someone who has DIED. A breakup or an ex is NEVER grief (that is heartbreak)",
    "friends": "time with friends, gym friends, or colleagues as friends (drinks, parties, talks). A date or someone he is romantically interested in is NOT friends (that is dating)",
    "dating": "a NEW person he likes or is getting to know: meeting, dates, dating apps, texting them. Not his ex",
    "heartbreak": "his ex, the breakup, missing or dreaming about an ex, moving on",
    "therapy": "only when he describes an actual therapy session or his therapist's advice",
    "music": "making, writing or listening to music",
    "shows": "movies, TV series, watching something",
    "travel": f"he lives in {HOME['city']}; the entry happens somewhere else, like another city or country, or is about a trip",
    "celebration": "a birthday, festival, party or other special occasion",
}
JOURNAL_FEELINGS = ["sad", "lonely", "anxious", "hopeful", "calm", "happy", "grateful", "guilty", "proud", "heartbroken", "relieved"]


def journal_topics():
    """The fixed list plus any suggested tags he approved with /suggestedtags."""
    return JOURNAL_TAGS + [t for t in journal.get("extra_tags", []) if t not in JOURNAL_TAGS]
def _jwrite(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    write_json(path, data, indent=1, ensure_ascii=False)


def _journal_load():
    """All years into memory (small: the page is what loads lazily). Splits the old journal.json the first time."""
    if not os.path.isdir(JOURNAL_DIR) and os.path.exists(JOURNAL_FILE):
        old = json.load(open(JOURNAL_FILE))
        j = {"entries": old.get("entries", []), **{k: v for k, v in old.items() if k != "entries"}}
        for y in {e["date"][:4] for e in j["entries"]}:
            _journal_write_year(j, y)
        for m in {e["date"][:7] for e in j["entries"]}:
            _journal_write_month(j, m)
        _jwrite(f"{JOURNAL_DIR}/settings.json", {k: v for k, v in j.items() if k != "entries"})
        if _journal_read() == j:  # every entry read back word for word before the old file goes
            os.replace(JOURNAL_FILE, JOURNAL_FILE + ".pre-split")
        else:
            raise RuntimeError("journal split did not read back identically; journal.json left in place")
    return _journal_read() if os.path.isdir(JOURNAL_DIR) else {"entries": []}


def _journal_read():
    j = {"entries": [], **(safe(lambda: json.load(open(f"{JOURNAL_DIR}/settings.json")), {}) or {})}
    for y in sorted(x for x in os.listdir(JOURNAL_DIR) if re.fullmatch(r"\d{4}", x)):
        texts = {}
        for f in os.listdir(f"{JOURNAL_DIR}/{y}"):
            if re.fullmatch(r"\d{4}-\d{2}\.json", f):
                texts.update(json.load(open(f"{JOURNAL_DIR}/{y}/{f}")))
        for row in json.load(open(f"{JOURNAL_DIR}/{y}/index.json")):
            j["entries"].append({**row, "text": texts.get(row["date"], "")})
    j["entries"].sort(key=lambda x: x["date"])
    return j


def _journal_write_year(j, y):
    _jwrite(f"{JOURNAL_DIR}/{y}/index.json", [{k: v for k, v in e.items() if k != "text"} for e in j["entries"] if e["date"][:4] == y])


def _journal_write_month(j, m):
    path = f"{JOURNAL_DIR}/{m[:4]}/{m}.json"
    texts = {e["date"]: e["text"] for e in j["entries"] if e["date"][:7] == m}
    if texts:
        _jwrite(path, texts)
    elif os.path.exists(path):
        os.remove(path)


journal = _journal_load()


def journal_save(d=None):
    """Writes only what changed: that day's year index and month file, or just the settings."""
    with _lock:
        if d:
            _journal_write_year(journal, d[:4])
            _journal_write_month(journal, d[:7])
        else:
            _jwrite(f"{JOURNAL_DIR}/settings.json", {k: v for k, v in journal.items() if k != "entries"})


def journal_rows(years):
    """What the page loads up front: everything but the words, for these years."""
    return [{k: v for k, v in e.items() if k != "text"} for e in journal["entries"] if e["date"][:4] in years]


def journal_texts(month):
    return {e["date"]: e["text"] for e in journal["entries"] if e["date"][:7] == month}


def journal_day():
    """Talking at 12:40 AM is still about the day that just ended, so the journal day turns over at 4 AM."""
    return (now() - timedelta(hours=4)).date().isoformat()


def journal_date(b):
    d = b.get("date") or journal_day()
    try:
        day = datetime.strptime(str(d), "%Y-%m-%d").date()
    except ValueError:
        return None
    today = now().date()  # before 4 AM the calendar date can be written too, not just the night that is ending
    return day.isoformat() if today - timedelta(days=730) <= day <= today else None


def journal_entry(d):
    return next((e for e in journal["entries"] if e["date"] == d), None)


def journal_context(d):
    """What the server already knows about the day, so it doesn't have to be said again."""
    with _lock:
        names = {x["id"]: x["name"] for x in gym["days"]}
        out = [f"Trained {names.get(x['day'], 'at the gym')}" for x in gym["sessions"] if x["date"] == d]
    return out


def journal_away(d):
    """True when the calendar says he was outside home that day ("{name} in Singapore")."""
    for e in safe(lambda: day_events(date.fromisoformat(d)), []) or []:
        m = e["all_day"] and re.match(rf"^{NAME} in (.+)$", e["title"], re.I)
        if m and not re.search(re.escape(HOME["city"]), m.group(1), re.I):
            return True
    return False


# ---------------------------------------------------------------- journal AI: Gemma 4 26B on the server, once a night
# Since 2026-10-24. Smaller local models kept mixing up who did and said what; Gemma 26B doesn't (tested against Sonnet).
# About 3 minutes an entry with all 8 cores; unloaded straight after so its 19 GB is free again. claude() stays for comparison runs.
JOURNAL_MODEL = cfg("models.journal", "gemma4:26b")
CLAUDE_MODEL, CLAUDE_KEY = cfg("models.claude_journal", "claude-sonnet-5-5"), "/secrets/anthropic.secret.txt"
CLAUDE_PRICE = (2.00, 10.00)  # Sonnet 5.5, $ per million tokens in / out
_claude = None
JOURNAL_TIERS = ((250, 40, 70), (500, 70, 110), (900, 100, 150), (10 ** 9, 140, 190))  # entry under N words: summary lo to hi words
# the rules every journal AI job shares. Fixed and short on purpose: when the AI gets something wrong,
# ask it for less (fewer fields, no quotes) instead of adding a rule here.
JOURNAL_RULES = ("Rules:\n"
                 "- Use only what the entries say. Never guess, invent or add facts.\n"
                 "- Keep straight who did, said or wrote what. A message he pasted in was written by him to someone, or to him by someone: "
                 "say so, never present it as his own journal thoughts.\n"
                 '- Second person ("you"), plain and warm. No diagnosis, no advice, no "should", no therapy terms, no judging.\n'
                 "- Name people only by the first names he used.\n"
                 "- Gentle and plain about grief and his mum, never as a problem to fix.\n"
                 "- No em dashes.")
JOURNAL_SYSTEM = (f"You summarise {NAME}'s private journal entries so that, years from now, he can read the summary and remember the day "
                  "without rereading the entry. Accuracy matters more than anything: never mix up who did, said or felt what.\n" + JOURNAL_RULES)
# the rest of what the one read of a night notes, for the deep read's cards and trends (no quotes)
JOURNAL_NIGHT_ASK = ('triggers: up to 3 things that set off a hard moment, up to 10 words each.\n'
                     'coping: up to 3 things he did to get through something, each {"what": "up to 10 words", "helped": true, false, or null when the entry doesn\'t say}.\n'
                     'sleep: "good" or "poor" only when the entry says how he slept, else null. energy: "low", "ok" or "high" only when the entry says, else null.')


def claude(system, prompt, max_tokens=4000):
    """One Claude reply as text. Its tokens count on the SG page's AI usage, apart from the local models."""
    global _claude
    if _claude is None:
        import anthropic
        _claude = anthropic.Anthropic(api_key=open(CLAUDE_KEY).read().strip())
    r = _claude.beta.messages.create(model=CLAUDE_MODEL, max_tokens=max_tokens, system=system, output_config={"effort": "medium"},
                                     betas=["server-side-fallback-2026-07-01"], fallbacks="default",
                                     messages=[{"role": "user", "content": prompt}])
    count_tokens("Claude", {"prompt_eval_count": r.usage.input_tokens, "eval_count": r.usage.output_tokens},
                 (r.usage.input_tokens * CLAUDE_PRICE[0] + r.usage.output_tokens * CLAUDE_PRICE[1]) / 1e6)
    if r.stop_reason == "refusal":
        raise RuntimeError("Claude declined this one")
    return "".join(b.text for b in r.content if b.type == "text").strip()


_gemma_lock = threading.Lock()  # one Gemma job at a time (nightly entries, the weekly recap)


# Hindi family words, so Gemma never reads Maama as a partner. Fixed size: it lists words, never people.
# Only the words a prompt actually uses are added to it (a line or two on most nights, nothing on nights without any).
REL_WORDS = [
    (("maama", "mama", "mamu", "maamu", "mamaji", "maamaji", "mamuji"), "his mother's brother, his maternal uncle. Plain Maama is his own uncle; a name before it (Rachit Maama) is another uncle on his mother's side"),
    (("maami", "mami", "maamiji", "mamiji", "mamijaan"), "his maternal uncle's wife, his aunt"),
    (("nani", "naani", "nanima", "naanima", "naniji", "nanu"), "his mother's mother, his grandmother"),
    (("nana", "naana", "nanaji", "naanaji"), "his mother's father, his grandfather"),
    (("dadi", "daadi", "dadima", "daadima", "dadiji"), "his father's mother, his grandmother"),
    (("dada", "daada", "dadaji", "daadaji"), "his father's father, his grandfather"),
    (("mausi", "maasi", "masi", "mousi", "mausiji", "masiji"), "his mother's sister, his aunt"),
    (("mausa", "mausaji", "masaji", "mousaji", "maasaji"), "his mother's sister's husband, his uncle"),
    (("bua", "buaa", "buaji", "phuphi", "phuphu", "phuppo", "fufi"), "his father's sister, his aunt"),
    (("fufa", "phupha", "fufaji", "phuphaji", "foofa"), "his father's sister's husband, his uncle"),
    (("chacha", "chachu", "chachaji", "chachu", "kaka", "kakaji"), "his father's younger brother, his uncle"),
    (("chachi", "chachiji", "kaki", "kakiji"), "his father's younger brother's wife, his aunt"),
    (("tau", "tauji", "taya", "tayaji", "taaya", "bade papa"), "his father's elder brother, his uncle"),
    (("tai", "taiji", "tayi", "taai", "badi mummy", "badi mumma"), "his father's elder brother's wife, his aunt"),
    (("bhaiya", "bhaiyya", "bhaia", "bhaiyaa", "bhaisaab", "bhaisahab", "bhaijaan"), "an older brother, or said out of respect to any older man or friend (Jayant bhaiya is not his brother)"),
    (("bhai", "bhau"), "brother, or just \"bro\" between friends"),
    (("didi", "deedi", "didu", "dii"), "an older sister, or said out of respect to any older woman"),
    (("behen", "behan", "bahen", "bahan", "behna"), "sister"),
    (("bhabhi", "bhabi", "bhabhiji", "bhaabhi"), "an older brother's wife, or a friend's wife"),
    (("jiju", "jijaji", "jija", "jeeju"), "his sister's husband, his brother-in-law"),
    (("beta", "beti", "bacha", "bachcha"), "son or daughter, or said with affection to a younger person"),
    (("sir", "ma'am", "maam", "madam", "sirji"), "after a name, a teacher, coach or senior (Udit sir is a teacher)"),
    (("mummy", "mumma", "mamma"), "his own mother"),
    (("mom", "mum", "maa", "mother", "ammi", "mommy"), "his own mother (someone else's mum is theirs)"),
    (("papa", "pappa", "pitaji", "dad", "daddy"), "his father"),
]
_REL_RX = [(re.compile(r"(?<![A-Za-z])(?:" + "|".join(re.escape(v) for v in sorted(vs, key=len, reverse=True)) + r")(?:ji)?(?![A-Za-z])", re.I), vs[0], m) for vs, m in REL_WORDS]


def rel_hint(text):
    """The Hindi family words this text uses, one line each, or ''. "mamma" means Maama only when Mummy isn't meant: both lines show."""
    hits = [f"- {', '.join(dict.fromkeys(x.capitalize() for x in rx.findall(text)))}: {m}" for rx, w, m in _REL_RX if rx.search(text)]
    return ("\nFamily words in his writing (Hindi or Indian English), what they mean to him:\n" + "\n".join(hits)) if hits else ""


def gemma(system, prompt, max_tokens=600, ctx=8192):
    """One local Gemma reply as text, for journal summaries. Counts as Journal on the SG page's AI usage.
    The window is per request: 8k for a night, 16k only for the Wednesday recap."""
    system += rel_hint(prompt)
    mine = _tag(JOURNAL_MODEL) in (safe(ai_loaded, {}) or {})  # loaded by hand on the Server page: leave it loaded after
    with _gemma_lock:
        r = big_call("Reading your journal", lambda: http(f"{OLLAMA}/api/generate", {
            "model": JOURNAL_MODEL, "system": system, "prompt": prompt, "stream": False, "think": False, "format": "json", "keep_alive": -1 if mine else 0,
            "options": {"temperature": 0.3, "num_ctx": ctx, "num_predict": max_tokens}}, timeout=1800))
    count_tokens("Journal", r)
    return r["response"].strip()


def journal_calibration():
    """His last few score corrections that came with a reason, so the AI learns how he rates a day."""
    fixes = [e for e in journal["entries"] if e.get("mood_set") and e.get("mood_why") and e.get("mood_ai")][-5:]
    if not fixes:
        return ""
    return ("How he corrected past scores, so match how he rates a day: "
            + "; ".join(f'AI said {e["mood_ai"]}, he said {e["mood"]} ("{e["mood_why"]}")' for e in fixes) + ".\n")


def journal_ai(d):
    """Summary, mood, tags, feelings and people for one entry. His words are never changed."""
    with _lock:
        e = journal_entry(d)
        if not e or not e["text"].strip():
            return
        text, stamp = e["text"], e["updated"]
        cal = journal_calibration()
    lo, hi = next((x, y) for n, x, y in JOURNAL_TIERS if len(text.split()) < n)
    run_purpose(f"summary {d}")
    topics = journal_topics()
    out = gemma(JOURNAL_SYSTEM, f"Journal entry for {d}:\n<entry>\n{text}\n</entry>\n\n"
                 "Reply with JSON only, no code fence:\n"
                 '{"summary": "...", "mood": 0, "feelings": [], "tags": [], "people": [], "new_tag": "", "triggers": [], "coping": [], "sleep": null, "energy": null}\n\n'
                 f'summary: one paragraph in the second person ("You ..."), {lo} to {hi} words. Say what happened in order, who was involved, '
                 "how he felt and how the day ended. Squash long reflections into one sentence of what he concluded. Keep only the details that "
                 "help him remember. Use only what the entry says. When a pronoun is unclear, work out who it is from context; if you can't be sure, "
                 'say "someone" rather than guess a name. Before you put a name on what someone did (messaged, said, met), check the entry names that person '
                 'for that very moment: when two women (or two men) are in the night, "she" (or "he") is the one the nearest sentences are about, '
                 'not the first one mentioned. Plain and kind, no advice.\n'
                 "mood: a whole number for how the day felt to him overall, weighing the good parts as well as the bad: "
                 "1 to 2 only when almost nothing went right (a crisis, a loss, a day he calls one of his worst); 3 to 4 bad; "
                 "5 mixed, good things happened but something heavy sat over them; 6 to 7 okay or good; 8 to 10 great. "
                 'Strong words in the moment ("horrible", "shit") don\'t make the whole day awful when he also had good moments. '
                 "Use his own number if he gave one. It must fit the feelings you pick.\n"
                 + cal + f"feelings: 1 to 3 from {json.dumps(JOURNAL_FEELINGS)}.\n"
                 "tags: the 1 to 3 main topics, only from this list (by meaning, not because a word appears): "
                 + "; ".join(f"{t} = {JOURNAL_TAG_MEANING.get(t, t)}" for t in topics) + ".\n"
                 "people: first names of the people he wrote about (not himself), at most 6.\n"
                 "new_tag: one lowercase word for a main topic none of the tags covers, otherwise an empty string.\n" + JOURNAL_NIGHT_ASK, max_tokens=900)
    r = json.loads(out[out.index("{"):out.rindex("}") + 1])
    with _lock:
        e = journal_entry(d)
        if not e or e["updated"] != stamp:
            return  # edited meanwhile: it stays due for the next run
        mine = bool(e.get("mood_set"))  # he set the score himself: the AI's goes aside, for "Use AI's score"
        try:
            e["mood_ai" if mine else "mood"] = max(1, min(10, int(r.get("mood"))))
        except (TypeError, ValueError):
            pass
        e["tags"] = [t for t in (r.get("tags") or []) if t in topics][:3]
        if journal_away(d) and "travel" not in e["tags"]:
            e["tags"] = e["tags"][:2] + ["travel"]
        e["feelings_ai" if mine else "feelings"] = [t for t in (r.get("feelings") or []) if t in JOURNAL_FEELINGS][:3]
        e["people"] = [str(x).strip()[:30] for x in (r.get("people") or []) if str(x).strip() and str(x).strip().lower() != NAME.lower()][:6]
        nt = re.sub(r"[^a-z-]", "", str(r.get("new_tag") or "").lower())[:24]
        e["new_tag"] = nt if nt and nt not in topics and nt not in JOURNAL_FEELINGS else ""
        if str(r.get("summary") or "").strip():
            e["summary"] = str(r["summary"]).strip().replace("—", ",")
        e["ai_at"] = time.time()
        e.pop("sum_due", None)
        journal_save(d)
        sig = _dload(SIGNALS_FILE, {})
        sig[d] = night_signals(r, stamp)
        _jwrite(SIGNALS_FILE, sig)


def journal_night():
    """4:30 AM (again at 6:30 and 8:30 if the internet was down): every entry finished, or marked for a fresh summary, since the last run."""
    for d in [e["date"] for e in journal["entries"] if e.get("sum_due") and e.get("text", "").strip()]:
        if d != _jnow["run"]:  # Run now has that one
            safe(lambda d=d: journal_ai_due(d))


def journal_ai_due(d):
    """Waits its turn for Gemma, then writes d's summary only if it still needs one: the morning run (or a restart's
    catch-up) and Run now can both pick up the same day, and the second would just write it again."""
    with _gemma_lock:
        pass
    with _lock:
        due = (journal_entry(d) or {}).get("sum_due")
    if not due:
        return "skipped"  # shows as skipped in the job log
    journal_ai(d)


# Run now on the page: queued days written straight away, one at a time (Gemma does one job at a time), oldest first
_jnow = {"run": None, "wait": [], "busy": False}


def jnow_view():
    return {"run": _jnow["run"], "wait": list(_jnow["wait"])}


def jnow_worker():
    while True:
        with _lock:
            d = _jnow["run"]
        journal_work(lambda: run_job(f"Journal summary now {d}", lambda: journal_ai_due(d)))
        with _lock:
            if not _jnow["wait"]:
                _jnow.update(run=None, busy=False)
                return
            _jnow["run"] = _jnow["wait"].pop(0)


# ---------------------------------------------------------------- weekly recap for therapy (Wednesdays)
# Gemma reads the week's FULL entries (last Wednesday night to Tuesday night) at 8 AM, retries at 9, 10 and 11, and the
# Journal's "For your therapist" card shows it from 12 noon until midnight; then it's pending again for the next week.
# Edits or rescored moods before noon redo it once. One file per week in journal/weekly/<year of the Wednesday>/<first night>_to_<last night>.json, kept forever.
RECAP_DIR = f"{JOURNAL_DIR}/weekly"
RECAP_START, RECAP_SHOW = 8, 12  # first run, and when the card shows it
RECAP_WORDS = 9000  # past this, the shortest nights go in as their summaries so the week fits the 16k window
RECAP_SYSTEM = (f"You write a weekly journal recap for {NAME} to read before his Wednesday therapy session.\n"
                "You get up to 7 nights of his private journal. Each night has the date, his mood (1 to 10),\n"
                "feelings, topics, and the full entry in his own words.\n\n" + JOURNAL_RULES + "\n"
                "- Past tense. Refer to days by weekday (Thu, Fri...), never by date.\n"
                "- One moment per bullet: what happened, why it mattered to you, and who was there. Don't repeat yourself.\n"
                "- When a mood number is given for a day, you may mention it; never invent one.")
RECAP_ASK = ("Return JSON only:\n"
             "{\n"
             ' "line": "One sentence, up to 30 words: the shape of the week, how it started, turned, and ended.",\n'
             ' "happened": ["10 to 12 bullets, each up to 40 words, in the order the week went. Cover the biggest moments, what caused the lows and the highs, who was involved, and what helped."],\n'
             ' "bring_up": ["3 to 4 bullets, each up to 20 words: patterns, repeated feelings, or open threads worth talking about in therapy. Topics, not advice."],\n'
             ' "tags": ["the 3 to 4 topics that came up most"]\n'
             "}")
RECAP_PLAIN = set("you your i mon tue wed thu fri sat sun monday tuesday wednesday thursday friday saturday sunday january february march "
                  "april may june july august september october november december mum mom mummy dad papa".split())
_recap_busy = threading.Event()


def recap_wed(day=None):
    """The Wednesday the card is about: today if it's Wednesday, otherwise the next one (it turns over at midnight)."""
    d = day or now().date()
    return d + timedelta(days=(2 - d.weekday()) % 7)


def recap_days(wed):
    return [(wed - timedelta(days=7 - i)).isoformat() for i in range(7)]


def recap_path(wed):
    days = recap_days(wed)
    return f"{RECAP_DIR}/{str(wed)[:4]}/{days[0]}_to_{days[-1]}.json"


def recap_load(wed):
    return safe(lambda: json.load(open(recap_path(wed))), None)


def recap_stamp(days):
    """Moves whenever a night of the week is written, edited, rescored or summarised, so a stale recap can be redone."""
    with _lock:
        return max([max(e.get("updated") or 0, e.get("mood_set") or 0, e.get("ai_at") or 0) for e in map(journal_entry, days) if e] or [0])


def recap_input(days):
    """The prompt (full entries, with mood, feelings and topics), plus what the checks need: moods given, every word he used."""
    with _lock:
        es = {d: dict(e) for d in days if (e := journal_entry(d)) and (e.get("text") or "").strip()}
    full, words = set(es), sum(len(e["text"].split()) for e in es.values())
    for e in sorted(es.values(), key=lambda e: len(e["text"].split())):
        if words <= RECAP_WORDS:
            break
        if e.get("summary"):
            words -= len(e["text"].split()) - len(e["summary"].split())
            full.discard(e["date"])
    blocks, moods, said = [], set(), set()
    for d in days:
        head = f"[{datetime.fromisoformat(d):%a %-d %b}]"
        if d not in es:
            blocks.append(f"{head} not written")
            continue
        e = es[d]
        mood = ""
        if e.get("mood"):
            moods.add(int(e["mood"]))
            mood = (f' mood {e["mood"]} (your own score' + (f'; why: "{e["mood_why"]}")' if e.get("mood_why") else ")")) if e.get("mood_set") \
                else f' mood {e["mood"]} (AI score)'
        meta = f"{head}{mood} | feelings: {', '.join(e.get('feelings') or []) or 'none'} | topics: {', '.join(e.get('tags') or []) or 'none'}"
        body = e["text"].strip() if d in full else "(the night's summary, the entry was too long to include) " + e["summary"].strip()
        blocks.append(f"{meta}\n{body}")
        for x in (e["text"], e.get("summary") or "", " ".join(e.get("people") or [])):
            said.update(re.sub(r"'s$", "", w.lower()) for w in re.findall(r"[A-Za-z][A-Za-z'-]+", x))
    first, last = datetime.fromisoformat(days[0]), datetime.fromisoformat(days[-1])
    prompt = (f"Week: {first:%a %-d %b} to {last:%a %-d %b}. Nights written: {len(es)} of 7.\n\n" + "\n\n".join(blocks) + "\n\n" + RECAP_ASK)
    return prompt, len(es), len(full) == len(es), moods, said


def recap_clean(x, cap):
    t = re.sub(r"\s*—\s*|\s+–\s+", ", ", str(x or "")).strip().strip('"').lstrip("-•* ").strip()
    w = t.split()
    return " ".join(w[:cap]).rstrip(",;:") + "…" if len(w) > cap * 1.25 else t


def recap_ok(b, moods, said):
    """Drops a bullet that names someone or something he never wrote, or quotes a mood no day had."""
    toks = b.split()
    for i, raw in enumerate(toks):
        w = raw.strip(".,;:!?\"'()…")
        w = re.sub(r"'s$", "", w)
        if i and w[:1].isupper() and not toks[i - 1].endswith((".", "!", "?")) and w.lower() not in said and w.lower() not in RECAP_PLAIN:
            return False
    nums = re.findall(r"\b(10|[1-9])\s*(?:/|out of)\s*10\b", b) + re.findall(r"\bmoods?\s+(?:of\s+|was\s+|at\s+|to\s+|hit\s+|around\s+)?(10|[1-9])\b", b, re.I)
    return all(int(n) in moods for n in nums)


def recap_check(r, moods, said):
    line = recap_clean(r.get("line"), 30)
    happened = [c for x in (r.get("happened") or [])[:12] if (c := recap_clean(x, 40)) and recap_ok(c, moods, said)]
    bring = [c for x in (r.get("bring_up") or [])[:4] if (c := recap_clean(x, 20)) and recap_ok(c, moods, said)]
    topics = journal_topics()
    tags = [t for t in dict.fromkeys(str(t).lower().strip() for t in (r.get("tags") or [])) if t in topics][:4]
    if not line or not recap_ok(line, moods, said) or len(happened) < 3:
        return None
    return {"line": line, "happened": happened, "bring_up": bring, "tags": tags}


def recap_run(wed):
    """Writes one week's recap. News summaries wait while Gemma has the CPU."""
    if _recap_busy.is_set():
        return
    _recap_busy.set()
    try:
        days, t0 = recap_days(wed), time.time()
        stamp = recap_stamp(days)
        prompt, n, full, moods, said = recap_input(days)
        run_purpose("weekly recap")
        if n < 3:
            return
        if not _digest_lock.acquire(timeout=1800):
            return
        try:
            out = None
            for _ in range(2):  # one retry when the JSON is broken or fails the checks
                try:
                    raw = gemma(RECAP_SYSTEM, prompt, max_tokens=1600, ctx=16384)
                    out = recap_check(json.loads(raw[raw.index("{"):raw.rindex("}") + 1]), moods, said)
                except ValueError:
                    out = None
                if out:
                    break
        finally:
            _digest_lock.release()
        if not out:
            return
        if len(out["tags"]) < 3:  # Gemma often names too few: top up from the topics on the nights themselves
            with _lock:
                seen = [x for d in days if (e := journal_entry(d)) for x in (e.get("tags") or [])]
            out["tags"] += [x for x in sorted(dict.fromkeys(seen), key=seen.count, reverse=True) if x not in out["tags"]][:4 - len(out["tags"])]
        old = recap_load(wed) or {}
        _jwrite(recap_path(wed), {"week": str(wed), "from": days[0], "to": days[-1], "nights": n, "full": full, **out,
                                            "made": time.time(), "secs": round(time.time() - t0), "stamp": stamp, "runs": old.get("runs", 0) + 1})
    finally:
        _recap_busy.clear()


THERAPY_EVENT = "|".join(cfg("therapy.calendar_words", ["therap"]))  # calendar titles that mean a session


def recap_due():
    """Wednesday 8 AM to noon, every 10 minutes: first try at 8, retries at 9, 10 and 11, and one redo if the week changed."""
    t = now()
    if not feature("therapy_recap", False) or t.weekday() != 2 or not RECAP_START <= t.hour < RECAP_SHOW:
        return
    w = recap_load(t.date())
    if not w:
        if claim(k := f"recap:{t:%Y%m%d%H}"):
            claimed_run(k, lambda: recap_run(t.date()))
    elif w.get("runs", 1) < 2 and w.get("stamp", 0) < recap_stamp(recap_days(t.date())):
        recap_run(t.date())


def recap_card():
    """What the card shows: pending all week, being written on Wednesday morning, the recap from noon to midnight."""
    t = now()
    wed = recap_wed(t.date())
    days = recap_days(wed)
    with _lock:
        written = [bool((e := journal_entry(d)) and (e.get("text") or "").strip()) for d in days]
    card = {"week": str(wed), "from": days[0], "to": days[-1], "nights": sum(written), "written": written}
    noon = datetime.combine(wed, datetime.min.time(), t.tzinfo).replace(hour=RECAP_SHOW)
    if t.date() != wed:
        return {**card, "status": "pending"}
    if t >= noon:
        w = recap_load(wed)
        if w:
            sess = any(re.search(THERAPY_EVENT, e["title"], re.I) for e in safe(lambda: day_events(wed), []) or [])
            return {**card, **{k: w[k] for k in ("line", "happened", "bring_up", "tags", "full", "made")}, "status": "ready", "session": sess, "until": (noon + timedelta(hours=12)).timestamp()}
        return {**card, "status": "thin" if sum(written) < 3 else "missed"}
    if sum(written) < 3:
        return {**card, "status": "thin"}
    start = noon.replace(hour=RECAP_START)
    return {**card, "status": "writing" if t >= start else "pending", "until": (noon if t >= start else start).timestamp()}


def journal_replace(b):
    """Find a word or phrase this month or in every entry; with apply, replace it.
    Searches his words, the summaries and the people lists, in any case: whole words, or with mode "contains" inside words
    too. It says where each match is, so
    Replace changes exactly what the preview showed. Moods stay, nothing is re-summarised, and the journal is copied first."""
    find, new = str(b.get("find") or "").strip()[:100], str(b.get("replace") or "").strip()[:100]
    if len(find) < 2:
        return {"ok": True, "matches": [], "total": 0}
    rx = re.compile(re.escape(find) if b.get("mode") == "contains" else r"(?<!\w)" + re.escape(find) + r"(?!\w)", re.I)
    month = journal_day()[:7]
    pick = (lambda d: True) if b.get("scope") == "all" else (lambda d: d[:7] == month)
    apply = bool(b.get("apply")) and bool(new) and new != find
    # keep the case of what's replaced: "Mama" at the start of a sentence becomes "Maama", "MAMA" becomes "MAAMA"
    sub = lambda s: rx.sub(lambda m: (new.upper() if m.group(0).isupper() and len(m.group(0)) > 1
                                      else new[:1].upper() + new[1:] if m.group(0)[:1].isupper() else new), s)
    out, total = [], 0
    with _lock:
        for e in journal["entries"]:
            if not pick(e["date"]):
                continue
            snips, n = [], 0
            for where, s in (("text", e.get("text") or ""), ("summary", e.get("summary") or "")):
                hits = list(rx.finditer(s))
                n += len(hits)
                snips += [{"where": where, "pre": s[max(0, m.start() - 60):m.start()], "hit": m.group(0), "post": s[m.end():m.end() + 60]} for m in hits[:3]]
            ppl = ", ".join(e.get("people") or [])  # the whole list once, every match in it marked
            if hits := list(rx.finditer(ppl)):
                n += len(hits)
                cuts = [0] + [i for m in hits for i in (m.start(), m.end())] + [len(ppl)]
                snips.append({"where": "people", "parts": [[ppl[a:b], k % 2] for k, (a, b) in enumerate(zip(cuts, cuts[1:])) if a < b or k % 2]})
            if not n:
                continue
            total += n
            out.append({"date": e["date"], "n": n, "snips": snips})
        if apply and out:
            journal_replace_copy()
            for e in journal["entries"]:
                if not pick(e["date"]):
                    continue
                if rx.search(e.get("text") or ""):
                    e["text"] = sub(e["text"])
                    e["words"], e["updated"] = len(e["text"].split()), time.time()
                if rx.search(e.get("summary") or ""):
                    e["summary"] = sub(e["summary"])
                if any(rx.search(p) for p in e.get("people") or []):
                    e["people"] = journal_people(sub(p) for p in e["people"])
            for d in {m["date"] for m in out}:
                journal_save(d)
    return {"ok": True, "matches": out, "total": total, "replaced": apply and bool(out)}


def journal_people(names):
    """People lists hold first names, as Gemma writes them: no titles, and one entry per person whatever the case."""
    out = {}
    for p in names:
        p = re.sub(r"^(dr|mr|mrs|ms|miss|prof)(\.\s*|\s+)", "", str(p).strip(), flags=re.I)
        if p and (p.lower() not in out or out[p.lower()].islower()):  # a capitalised spelling wins
            out[p.lower()] = p
    return list(out.values())


def journal_replace_copy():
    """The whole journal as it was, before a find and replace; the last 3 are kept."""
    keep = f"{JOURNAL_DIR}/replace-copies"
    os.makedirs(keep, exist_ok=True)
    shutil.copytree(JOURNAL_DIR, f"{keep}/{datetime.now(TZ):%Y-%m-%d-%H%M%S-%f}", ignore=shutil.ignore_patterns("replace-copies"))
    for old in sorted(os.listdir(keep))[:-3]:
        shutil.rmtree(f"{keep}/{old}", ignore_errors=True)


# ---------------------------------------------------------------- deep insights (since 2026-10-28)
# The page works out the numbers (moods by topic, weekday, people, feelings) from the index it already has.
# Since 2026-10-30 Gemma writes only: forgotten wins (5 AM, when something changed), a short morning note about last night,
# the week in patterns on Sundays, and the chapters and a letter on the 1st. It reads the nights' summaries and picks no quotes.
# Also here: unsent letters (no AI ever reads them,
# they're never summarised or searched), and dates that matter (the page goes quieter around them).
INSIGHTS_FILE = f"{JOURNAL_DIR}/insights.json"
LETTERS_FILE = f"{JOURNAL_DIR}/letters.json"
INSIGHTS_WORDS = 9000  # past this, the oldest summaries shrink to their first two sentences
_insights_busy = threading.Event()
THERAPY_LINE = " He is working on his mental health with a therapist." if feature("therapy_recap", False) else ""
INSIGHTS_SYSTEM = (f"You read {NAME}'s private journal to help him understand himself.{THERAPY_LINE}\n"
                   "You get his nights oldest first, each as one line (date, mood 1 to 10, feelings, topics, people, what set things off,\n"
                   "what he did, sleep, energy) and the night's summary.\n\n" + JOURNAL_RULES)
INSIGHTS_ASK = ("Return JSON only:\n"
                '{"wins": [{"date": "YYYY-MM-DD", "win": "up to 18 words: something you did, handled or got through that is easy to forget"}]}\n'
                "wins: 3 to 6 different moments. Dates must be nights given above.")


def _jnorm(t):
    return re.sub(r"\s+", " ", re.sub(r"[“”]", '"', re.sub(r"[‘’]", "'", str(t or "")))).strip().lower()


def insights_stamp():
    with _lock:
        return max([max(e.get("updated", 0), e.get("ai_at", 0)) for e in journal["entries"] if (e.get("text") or "").strip()] or [0])


def insights_run():
    if _insights_busy.is_set():
        return
    _insights_busy.set()
    try:
        stamp, t0 = insights_stamp(), time.time()
        with _lock:
            es = [dict(e) for e in journal["entries"] if (e.get("text") or "").strip()]
        if len(es) < 5:
            return
        moods, said = {int(e["mood"]) for e in es if e.get("mood")}, set()
        for e in es:
            for x in (e["text"], e.get("summary") or "", " ".join(e.get("people") or [])):
                said.update(re.sub(r"'s$", "", w.lower()) for w in re.findall(r"[A-Za-z][A-Za-z'-]+", x))
        prompt = (f"{len(es)} nights, {es[0]['date']} to {es[-1]['date']}.\n\n" + deep_nights(es, _dload(SIGNALS_FILE, {}), INSIGHTS_WORDS)
                  + "\n\n" + INSIGHTS_ASK)
        run_purpose("deep insights")
        days = {e["date"] for e in es}
        if not _digest_lock.acquire(timeout=3600):
            return
        try:
            out = None
            for _ in range(2):
                try:
                    raw = gemma(INSIGHTS_SYSTEM, prompt, max_tokens=1500, ctx=16384)
                    out = insights_check(json.loads(raw[raw.index("{"):raw.rindex("}") + 1]), moods, said, days)
                except ValueError:
                    out = None
                if out:
                    break
        finally:
            _digest_lock.release()
        run_info("insights", "written" if out else "failed the checks twice")
        if out:
            _jwrite(INSIGHTS_FILE, {**out, "nights": len(es), "made": time.time(), "secs": round(time.time() - t0), "stamp": stamp})
    finally:
        _insights_busy.clear()


def insights_check(r, moods, said, days):
    seen = set()

    def ok(x, cap):  # the usual checks, and each line once across the page
        c = recap_clean(x, cap) if isinstance(x, str) else ""
        if not c or not recap_ok(c, moods, said) or _jnorm(c) in seen:
            return ""
        seen.add(_jnorm(c))
        return c
    out = {"wins": []}
    for w in (r.get("wins") or [])[:6]:
        if isinstance(w, dict) and w.get("date") in days and (c := ok(w.get("win"), 18)):
            out["wins"].append({"date": w["date"], "win": c})
    return out if out["wins"] else None


def insights_due():
    """5 AM, after the nightly summaries: once, when anything was written or rescored since the last run."""
    if CAPS.skip("Deep insights", "ollama"):
        return "skipped"
    old = safe(lambda: json.load(open(INSIGHTS_FILE)), {}) or {}
    if insights_stamp() > old.get("stamp", 0):
        insights_run()
    else:
        return "skipped"  # nothing new since the last run


def deep_view():
    with _lock:
        dates = list(journal.get("dates", []))
    recaps = []
    for f in sorted(glob.glob(f"{RECAP_DIR}/*/*.json"), reverse=True):
        w = safe(lambda f=f: json.load(open(f)), None)
        if w and w.get("line"):
            recaps.append({k: w.get(k) for k in ("from", "to", "line", "happened", "bring_up", "tags", "nights", "full", "made")})  # in full: For your therapist shows them
    return {"ai": safe(lambda: json.load(open(INSIGHTS_FILE)), None), "busy": _insights_busy.is_set(), "dates": dates,
            "recaps": recaps,
            "letters": len(safe(lambda: json.load(open(LETTERS_FILE)), []) or []), **(safe(deep_extra, {}) or {})}


def deep_api(path, b):
    if path == "/journal/deep/letter":  # {to, text, id?} saves; {id, delete} removes. Kept apart from the journal: no AI reads these.
        with _lock:
            ls = safe(lambda: json.load(open(LETTERS_FILE)), []) or []
            if b.get("delete"):
                ls = [x for x in ls if x["id"] != b.get("id")]
            else:
                text, to = str(b.get("text") or "").strip()[:20000], re.sub(r"\s+", " ", str(b.get("to") or "")).strip()[:40]
                if not text:
                    return {"ok": False, "msg": "Write something first."}, 400
                x = next((x for x in ls if x["id"] == b.get("id")), None)
                if x:
                    x.update(to=to, text=text, updated=time.time())
                else:
                    x = {"id": uuid.uuid4().hex[:8], "to": to, "text": text, "created": time.time(), "updated": time.time()}
                    ls.insert(0, x)
            _jwrite(LETTERS_FILE, ls)
        return {"ok": True, "letters": ls}, 200
    if path == "/journal/deep/date":  # {label, md: "MM-DD"} adds; {id, delete} removes
        with _lock:
            ds = journal.setdefault("dates", [])
            if b.get("delete"):
                journal["dates"] = [x for x in ds if x["id"] != b.get("id")]
            else:
                label, md = re.sub(r"\s+", " ", str(b.get("label") or "")).strip()[:40], str(b.get("md") or "")
                if not label or not re.fullmatch(r"(0[1-9]|1[0-2])-(0[1-9]|[12]\d|3[01])", md):
                    return {"ok": False, "msg": "Give it a name and a date."}, 400
                ds.append({"id": uuid.uuid4().hex[:8], "label": label, "md": md})
                ds.sort(key=lambda x: x["md"])
            journal_save()
            return {"ok": True, "dates": journal["dates"]}, 200
    return {"ok": False, "msg": "bad request"}, 400


# ---------------------------------------------------------------- the nightly deep read (since 2026-10-28, simpler since 2026-10-29)
# Runs straight after the nightly summaries (4:30, retried 6:30 and 8:30). Each night is read once, by the summary
# (journal_ai), which also notes what set things off, what he did and whether it helped, sleep and energy. Everything
# after that (the morning note, the week, the month's letter, the chapters, Deep insights) reads those summaries, never
# the raw nights again, and never picks quotes: a small model can't tell whose sentence it is.
# Nothing here ever goes to Telegram or the brief.
DEEP_DIR = f"{JOURNAL_DIR}/deep"
SIGNALS_FILE, NOTES_FILE, CHAPTERS_FILE = (f"{DEEP_DIR}/{x}.json" for x in ("signals", "notes", "chapters"))
LETTER_WORDS, LETTER_MIN = (700, 1000), 600  # the month's letter
NOTE_WORDS = (50, 70)  # the morning note: not so short it says nothing, not a paragraph
_deep_busy = threading.Event()  # set while the deep read runs or waits: the news digests stand aside


def _dload(p, d):
    return safe(lambda: json.load(open(p)), None) or d


def night_signals(r, stamp):
    """What the night's one read noted besides the summary: short phrases, no quotes."""
    cl = lambda x: recap_clean(x, 10) if isinstance(x, str) else ""
    return {"triggers": [{"what": w} for x in (r.get("triggers") or [])[:3] if (w := cl(x))],
            "coping": [{"what": w, "helped": x.get("helped") if isinstance(x.get("helped"), bool) else None}
                       for x in (r.get("coping") or [])[:3] if isinstance(x, dict) and (w := cl(x.get("what")))],
            "sleep": {"quality": r.get("sleep") if r.get("sleep") in ("good", "poor") else None},
            "energy": r.get("energy") if r.get("energy") in ("low", "ok", "high") else None, "stamp": stamp, "at": time.time()}


def deep_line(d, e, s):
    """One night's facts on a single line."""
    bits = [f"[{d} {datetime.fromisoformat(d):%a}] mood {e.get('mood') or '?'}", "feelings: " + (", ".join(e.get("feelings") or []) or "none"),
            "topics: " + (", ".join(e.get("tags") or []) or "none"), "people: " + (", ".join(e.get("people") or []) or "none")]
    if s:
        bits += ["set off by: " + ("; ".join(x["what"] for x in s.get("triggers", [])) or "nothing noted"),
                 "you did: " + ("; ".join(x["what"] + {True: " (helped)", False: " (didn't help)"}.get(x.get("helped"), "") for x in s.get("coping", [])) or "nothing noted"),
                 "sleep: " + ((s.get("sleep") or {}).get("quality") or "?"), f"energy: {s.get('energy') or '?'}"]
    return " | ".join(bits)


def deep_nights(es, sig, cap=9000):
    """Nights (oldest first) the way every job after the summary reads them: the night's line, then its summary.
    Past cap words, the oldest summaries shrink to their first two sentences."""
    out, words = [], 0
    for e in reversed(es):
        s = (e.get("summary") or "").strip()
        if words + len(s.split()) > cap:
            s = ". ".join(s.split(". ")[:2])
        words += len(s.split())
        out.append(f"{deep_line(e['date'], e, sig.get(e['date'], {}))}\n{s or '(no summary yet)'}")
    return "\n\n".join(reversed(out))


TREND_SYSTEM = (f"You are the deep read of {NAME}'s private journal. You get his nights as their summaries and tell him what is worth knowing, "
                "the way a wise, kind friend who has read it all would. He is working on his mental health.\n" + JOURNAL_RULES)


def _note_fit(t):
    """The note within NOTE_WORDS: whole sentences, dropping from the end while it runs long."""
    ss = re.split(r"(?<=[.!?])\s+", recap_clean(t, 999))
    while len(ss) > 1 and len(" ".join(ss).split()) > NOTE_WORDS[1]:
        ss.pop()
    t = " ".join(ss)
    return t if NOTE_WORDS[0] - 10 <= len(t.split()) <= NOTE_WORDS[1] + 5 else ""


def deep_note(sig, es, fresh):
    """This morning's note: mostly last night, with the 3 nights before it as background."""
    notes, today = _dload(NOTES_FILE, []), now().date().isoformat()
    night = max((e["date"] for e in es if e["date"] in sig), default=None)
    mine = next((n for n in notes if n["date"] == today), None)
    if not night or (mine and mine.get("text") and mine.get("night") == night and not fresh):
        return "skipped"  # today's note is done (a failed one is tried again at 6:30 and 8:30)
    byd = {e["date"]: e for e in es}
    four = [byd[d] for d in sorted(byd) if d <= night][-4:]
    moods, said = {int(e["mood"]) for e in four if e.get("mood")}, set()
    for e in four:
        for x in (e["text"], e.get("summary") or "", " ".join(e.get("people") or [])):
            said.update(re.sub(r"'s$", "", w.lower()) for w in re.findall(r"[A-Za-z][A-Za-z'-]+", x))
    prompt = (f"Last night ({night}):\n{deep_nights(four[-1:], sig)}\n\n"
              + (f"The {len(four) - 1} nights before it, as background only:\n{deep_nights(four[:-1], sig)}\n\n" if len(four) > 1 else "")
              + "Write his morning note: what is worth knowing about last night. Mostly last night; bring in the nights before only where they clearly connect. "
              f"{NOTE_WORDS[0]} to {NOTE_WORDS[1]} words, 2 or 3 sentences.\n"
              'Return JSON only: {"note": "..."}')
    run_purpose("morning note")
    text = ""
    for _ in range(2):
        try:
            raw = gemma(TREND_SYSTEM, prompt, max_tokens=400)
            text = _note_fit(json.loads(raw[raw.index("{"):raw.rindex("}") + 1]).get("note"))
        except (ValueError, AttributeError):
            text = ""
        if text and recap_ok(text, moods, said):
            break
        text = ""
    run_info("note", "written" if text else "failed the checks twice")
    if not text:
        return "skipped"
    notes = [n for n in notes if n["date"] != today] + [{"date": today, "night": night, "text": text, "made": time.time()}]
    _jwrite(NOTES_FILE, notes[-400:])


def deep_week(sig, es, t=None):
    """Sunday: the last 7 nights in patterns. t is that Sunday (a run the server missed catches up until Saturday)."""
    t = t or now().date()
    p = f"{DEEP_DIR}/weeks/{t}.json"
    days = [(t - timedelta(days=i)).isoformat() for i in range(7, 0, -1)]
    wk = [e for e in es if e["date"] in days]
    if os.path.exists(p) or len(wk) < 3:
        return
    run_purpose("week in patterns")
    raw = safe(lambda: gemma(TREND_SYSTEM, f"The week from {days[0]} to {days[-1]}:\n\n{deep_nights(wk, sig)}\n\nReturn JSON only:\n" + "{\n"
               ' "line": "One sentence, up to 25 words: the shape of your week.",\n'
               ' "patterns": [{"text": "up to 25 words: a pattern in this week, like what followed what", "dates": []}],\n'
               ' "helped": ["up to 10 words each: what helped this week"],\n'
               ' "hard": ["up to 10 words each: what was hard this week"],\n'
               ' "keep": "One thing from this week worth keeping close, in your own spirit, up to 20 words."\n'
               "}\npatterns: 2 to 4. helped and hard: up to 4 each.", max_tokens=1200, ctx=16384), "")
    r = safe(lambda: json.loads(raw[raw.index("{"):raw.rindex("}") + 1]), None)
    if not r:
        return
    cl = lambda x, cap: recap_clean(x, cap) if isinstance(x, str) else ""
    _jwrite(p, {"week": str(t), "from": days[0], "to": days[-1], "nights": len(wk), "line": cl(r.get("line"), 25),
                "patterns": [{"text": c, "dates": sorted({d for d in x.get("dates") or [] if d in days})} for x in (r.get("patterns") or [])[:4] if isinstance(x, dict) and (c := cl(x.get("text"), 25))],
                "helped": [c for x in (r.get("helped") or [])[:4] if (c := cl(x, 10))], "hard": [c for x in (r.get("hard") or [])[:4] if (c := cl(x, 10))],
                "keep": cl(r.get("keep"), 20), "made": time.time()})


def deep_month(sig, es):
    """The 1st: a letter from his journal about the month that ended (or the first run after, within the first week).
    The Journal page shows it as a card until midnight on the day it's made, then under Letters from your journal."""
    t = now().date()
    m = (t.replace(day=1) - timedelta(days=1)).strftime("%Y-%m")
    p = f"{DEEP_DIR}/months/{m}.json"
    ms = [e for e in es if e["date"].startswith(m)]
    if os.path.exists(p) or len(ms) < 3:
        return
    run_purpose("month letter")
    raw = safe(lambda: gemma(TREND_SYSTEM, f"His nights in {datetime.strptime(m, '%Y-%m'):%B %Y}:\n\n" + deep_nights(ms, sig) + "\n\nReturn JSON only:\n"
               f'{{"letter": "A letter to him from his journal about this month, {LETTER_WORDS[0]} to {LETTER_WORDS[1]} words, in short paragraphs '
               'with a blank line between them. Starts with \\"Dear ' + NAME + ',\\". '
               'Warm, honest, specific: what the month held, what he carried, what he did well, what changed, and the people in it. '
               'Walk through the month in order, naming real nights and moments. Only what the nights say. '
               'Ends with a new line and \\"Your journal\\"."}', max_tokens=2600, ctx=16384), "")
    r = safe(lambda: json.loads(raw[raw.index("{"):raw.rindex("}") + 1]), None)
    if r and isinstance(r.get("letter"), str) and len(r["letter"].split()) >= LETTER_MIN:  # too short: the next run tries again
        _jwrite(p, {"month": m, "letter": re.sub(r"\s*—\s*", ", ", r["letter"].strip()), "nights": len(ms), "made": time.time()})


def deep_chapters(es):
    """The chapters of his life so far, rewritten on the 1st (and the first time there are 10 nights)."""
    if len(es) < 10:
        return
    run_purpose("chapters")
    es = es[-200:]
    full = sum(len((e.get("summary") or "").split()) for e in es) <= 9000  # whole summaries while they fit the 16k window, else their first two sentences
    lines = "\n".join(f"[{e['date']}] mood {e.get('mood') or '?'} | {', '.join(e.get('tags') or [])} | "
                      + ((e.get("summary") or "") if full else ". ".join((e.get("summary") or "").split(". ")[:2])) for e in es)
    raw = safe(lambda: gemma(TREND_SYSTEM, f"Every night so far, with its summary:\n{lines}\n\nReturn JSON only:\n"
               '{"chapters": [{"title": "2 to 5 words, like a chapter in a book", "from": "first night", "to": "last night", "line": "up to 25 words: what this chapter was"}]}\n'
               "Chapters are in order, don't overlap, and together cover every night. Usually 2 to 6 weeks each; a new one starts when life clearly turned.\n"
               "Balanced tone: name the hard parts and the good parts of each chapter plainly, as the nights tell them, making neither bigger or smaller. "
               "No silver linings, no drama.",
               max_tokens=1000, ctx=16384), "")
    r = safe(lambda: json.loads(raw[raw.index("{"):raw.rindex("}") + 1]), None)
    days = {e["date"] for e in es}
    ch = [{"title": recap_clean(x.get("title"), 6), "from": x["from"], "to": x["to"], "line": recap_clean(x.get("line"), 25)}
          for x in (r or {}).get("chapters") or [] if isinstance(x, dict) and x.get("from") in days and x.get("to") in days and x["from"] <= x["to"] and x.get("title")]
    ch = [c for i, c in enumerate(ch) if not i or c["from"] > ch[i - 1]["to"]]
    order = sorted(days)
    for i, c in enumerate(ch):  # close the gaps: the first starts on the first night, each runs to the night before the next, the last to the latest
        c["from"] = order[0] if not i else c["from"]
        c["to"] = max(d for d in order if d < ch[i + 1]["from"]) if i + 1 < len(ch) else order[-1]
    if ch:
        _jwrite(CHAPTERS_FILE, {"chapters": ch, "made": time.time()})


def deep_night(force=False):
    if _deep_busy.is_set():
        return
    _deep_busy.set()
    try:
        w0 = time.time()
        if not _digest_lock.acquire(timeout=3600):
            run_info("errors", "waited an hour for the AI and gave up", add=True)
            return
        run_info("waited", round(time.time() - w0))
        try:
            sig, new, wrote = _dload(SIGNALS_FILE, {}), [], False
            with _lock:
                es = [dict(e) for e in journal["entries"] if (e.get("text") or "").strip() and e.get("ai_at")]
            new = [e for e in es if sig.get(e["date"], {}).get("stamp") != e["updated"]]
            run_info("nights", len(new))
            for e in new:  # edited since its last read: one fresh read gives the summary and the night's signals together
                safe(lambda e=e: journal_ai(e["date"]))
            if new:
                sig = _dload(SIGNALS_FILE, {})
                with _lock:
                    es = [dict(e) for e in journal["entries"] if (e.get("text") or "").strip() and e.get("ai_at")]
            wrote = safe(lambda: deep_note(sig, es, bool(new) or force)) != "skipped"
            t = now()
            safe(lambda: deep_week(sig, es, t.date() - timedelta(days=(t.weekday() + 1) % 7)))  # the last Sunday; skips if it's done
            if t.day <= 7:
                safe(lambda: deep_month(sig, es))  # skips if the letter is done
            if (t.day == 1 and datetime.fromtimestamp(_dload(CHAPTERS_FILE, {}).get("made", 0)).date() != t.date()) or not os.path.exists(CHAPTERS_FILE):  # once on the 1st, not again at 6:30 and 8:30
                safe(lambda: deep_chapters(es))
        finally:
            _digest_lock.release()
    finally:
        _deep_busy.clear()
    run_job("Deep insights", insights_due)
    return None if new or wrote else "skipped"


_jmorning_lock = threading.Lock()


def journal_behind():
    """What a power cut or restart left undone: a summary, a night not read, today's note, the chapters, the month's letter or Deep insights.
    Nothing before 4:30 AM: until then the night is still his to write, and the 4:30 run does it all."""
    t = now()
    if (t.hour, t.minute) < (4, 30):
        return []
    with _lock:
        es = [dict(e) for e in journal["entries"] if (e.get("text") or "").strip()]
    sig, out = _dload(SIGNALS_FILE, {}), []
    if any(e.get("sum_due") for e in es):
        out.append("summaries")
    if any(e.get("ai_at") and sig.get(e["date"], {}).get("stamp") != e.get("updated") for e in es):
        out.append("nights")
    if es and not any(n.get("date") == t.date().isoformat() and n.get("text") for n in _dload(NOTES_FILE, [])):
        out.append("note")
    if es and not os.path.exists(CHAPTERS_FILE):
        out.append("chapters")
    m = (t.date().replace(day=1) - timedelta(days=1)).strftime("%Y-%m")
    if t.day <= 7 and not os.path.exists(f"{DEEP_DIR}/months/{m}.json") and sum(e["date"].startswith(m) and bool(e.get("ai_at")) for e in es) >= 3:
        out.append("letter")
    if len(es) >= 5 and insights_stamp() > (_dload(INSIGHTS_FILE, {}) or {}).get("stamp", 0):
        out.append("insights")
    return out


def journal_morning_run():
    """The 4:30 run, the 6:30 and 8:30 retries, and the catch-up after a restart: a retry with nothing left to do logs as "skipped"."""
    if not _jmorning_lock.acquire(blocking=False):
        return "skipped"  # one is already running
    try:
        return _journal_morning_run()
    finally:
        _jmorning_lock.release()


def _journal_morning_run():
    with _lock:
        due = any(e.get("sum_due") and (e.get("text") or "").strip() for e in journal["entries"])
    if due:
        run_job("Journal summaries", journal_night)
    d = run_job("Deep read and morning note", deep_night)
    _journal_morning["day"] = now().date().isoformat()
    return "skipped" if not due and d == "skipped" else None


def deep_extra():
    """What the page adds to /journal/deep: the morning note, each night's signals and the longer rhythm."""
    notes = [n for n in _dload(NOTES_FILE, []) if n.get("text")]
    weeks = sorted(glob.glob(f"{DEEP_DIR}/weeks/*.json"))
    return {"signals": {d: {k: v for k, v in s.items() if k not in ("stamp", "at")} for d, s in _dload(SIGNALS_FILE, {}).items()},
            "note": notes[-1] if notes else None,
            "week": _dload(weeks[-1], None) if weeks else None, "months": [_dload(f, None) for f in sorted(glob.glob(f"{DEEP_DIR}/months/*.json"), reverse=True)],
            "chapters": _dload(CHAPTERS_FILE, {}).get("chapters", []), "reading": _deep_busy.is_set()}


def journal_api(path, b):
    if path == "/journal/replace":
        return journal_replace(b), 200
    with _lock:
        d = journal_date(b)
        if not d:
            return {"ok": False, "msg": "Pick a day that isn't in the future."}, 400
        e = journal_entry(d)
        if path == "/journal/save":
            text = str(b.get("text") or "")[:20000]
            if not text.strip():  # everything erased: no entry for that day
                journal["entries"] = [x for x in journal["entries"] if x["date"] != d]
                journal_save(d)
                return {"ok": True, "entry": None}, 200
            if not e:
                e = {"date": d, "created": time.time()}
                journal["entries"].append(e)
                journal["entries"].sort(key=lambda x: x["date"])
            e.update(text=text, words=len(text.split()), updated=time.time())
            if isinstance(b.get("secs"), (int, float)):
                e["secs"] = int(max(e.get("secs", 0), min(b["secs"], 6 * 3600)))
            if b.get("done"):
                e["done"] = time.time()
                if not e.get("summary"):
                    e["sum_due"] = True
            journal_save(d)
            return {"ok": True, "entry": e}, 200
        if path == "/journal/resum":  # {date}: write a fresh summary tonight
            if not e:
                return {"ok": False, "msg": "There's no entry for that day."}, 400
            e["sum_due"] = True
            journal_save(d)
            return {"ok": True, "entry": e}, 200
        if path == "/journal/now":  # {date}: write its fresh summary now; {date, cancel}: stop waiting, back to the 4:30 run
            if b.get("cancel"):
                if d in _jnow["wait"]:
                    _jnow["wait"].remove(d)
                return {"ok": True, "now": jnow_view()}, 200
            if not e or not e.get("sum_due") or not (e.get("text") or "").strip():
                return {"ok": False, "msg": "That day isn't queued.", "now": jnow_view()}, 400
            if d != _jnow["run"] and d not in _jnow["wait"]:
                _jnow["wait"] = sorted(_jnow["wait"] + [d])
            if not _jnow["busy"]:  # the first one starts before we answer, so the page shows it writing straight away
                _jnow.update(busy=True, run=_jnow["wait"].pop(0))
                threading.Thread(target=jnow_worker, daemon=True).start()
            return {"ok": True, "now": jnow_view()}, 200
        if path == "/journal/unqueue":  # {date}: keep the summary it has, no fresh one tonight
            if not e:
                return {"ok": False, "msg": "There's no entry for that day."}, 400
            if d == _jnow["run"]:
                return {"ok": False, "msg": "That summary is being written right now."}, 400
            if d in _jnow["wait"]:
                _jnow["wait"].remove(d)
            e.pop("sum_due", None)
            journal_save(d)
            return {"ok": True, "entry": e}, 200
        if path == "/journal/mood":  # {date, mood, feelings, why}: his own score; {date, reset: true}: back to the AI's
            if not e:
                return {"ok": False, "msg": "There's no entry for that day."}, 400
            if b.get("reset"):
                if e.get("mood_set"):
                    if e.get("mood_ai"):
                        e["mood"] = e["mood_ai"]
                    else:
                        e.pop("mood", None)
                    e["feelings"] = e.get("feelings_ai", [])
                for k in ("mood_set", "mood_why", "mood_ai", "feelings_ai"):
                    e.pop(k, None)
            else:
                try:
                    m = int(b.get("mood"))
                except (TypeError, ValueError):
                    m = 0
                if not 1 <= m <= 10:
                    return {"ok": False, "msg": "Pick a score from 1 to 10."}, 400
                if not e.get("mood_set"):
                    e["mood_ai"], e["feelings_ai"] = e.get("mood"), e.get("feelings", [])
                e["mood"], e["mood_set"] = m, time.time()
                e["feelings"] = [t for t in (b.get("feelings") or []) if t in JOURNAL_FEELINGS][:3]
                why = str(b.get("why") or "").strip()[:300]
                if why:
                    e["mood_why"] = why
                else:
                    e.pop("mood_why", None)
            journal_save(d)
            return {"ok": True, "entry": {k: e.get(k) for k in ("mood", "feelings", "mood_set", "mood_why", "mood_ai", "feelings_ai")}}, 200
        if path == "/journal/delete":
            journal["entries"] = [x for x in journal["entries"] if x["date"] != d]
            journal_save(d)
            return {"ok": True}, 200
    return {"ok": False, "msg": "bad request"}, 400


def suggested_tags():
    """Tags the AI wanted that aren't on the list yet, most frequent first. Only shown when asked."""
    with _lock:
        topics, ignored = journal_topics(), set(journal.get("ignored_tags", []))
        count = {}
        for e in journal["entries"]:
            t = e.get("new_tag")
            if t and t not in topics and t not in ignored:
                count.setdefault(t, []).append(e["date"])
    if not count:
        return send("🏷️ <b>Suggested tags</b>\nNothing new. Your entries fit the tags you have.")
    top = sorted(count.items(), key=lambda x: (-len(x[1]), x[0]))[:8]
    lines = ["🏷️ <b>Suggested tags</b>", "Topics the AI kept seeing that aren't on your list yet:", ""]
    for t, ds in top:
        lines.append(f"• <b>{esc(t)}</b>, {len(ds)} {'entry' if len(ds) == 1 else 'entries'} (latest {fmt_day(max(ds))})")
    rows = [[B(f"➕ Add {t}", f"jtag:add:{t}"), B("Ignore", f"jtag:no:{t}")] for t, _ in top]
    return send("\n".join(lines), rows)


def fmt_day(d):
    return datetime.strptime(d, "%Y-%m-%d").strftime("%-d %b")


def journal_buttons():
    return ([[U("✍️ Start now", f"{DASH}/#journal")]] if DASH else []) + [
            [B("💤 15 min", "jsnz:15"), B("💤 30 min", "jsnz:30"), B("💤 1 hour", "jsnz:60")],
            [B("Skip tonight", "jskip")]]


def check_journal():
    """11 PM: a nudge to journal, once more at 11:30 if it was ignored. Snooze moves it, Skip or writing stops it."""
    t, day = now(), journal_day()
    with _lock:
        js = state.get("journal") or {}
        if t.hour == 23 and js.get("day") != day:
            js = state["journal"] = {"day": day, "next": time.time(), "auto": True, "sent": 0}
            save()
        e = journal_entry(day)
        if js.get("day") != day or js.get("skip") or not js.get("next") or time.time() < js["next"] or (e and e["text"].strip()):
            return
        first = not js.get("sent")
        js["sent"] = js.get("sent", 0) + 1
        js["next"] = time.time() + 1800 if first and js.get("auto") else None
        old, js["msg"] = js.get("msg"), None
        save()
    if old:  # only the newest nudge keeps its buttons
        tg("editMessageReplyMarkup", chat_id=OWNER, message_id=old, reply_markup={"inline_keyboard": []})
    m = send("📓 <b>Time to journal</b>\nTen minutes on how today went. Open it and just talk." if first
             else "📓 <b>Still up?</b>\nYour journal is waiting. Even five minutes counts.", journal_buttons())
    with _lock:
        js["msg"] = (m or {}).get("message_id")
        save()


def journal_week_lines():
    days = [(now().date() - timedelta(i)).isoformat() for i in range(1, 8)]
    es = [e for e in journal["entries"] if e["date"] in days and e.get("text", "").strip()]
    if not es:
        return ["", "<b>Journal</b>", "• No entries this week. Tonight's a good night to start."]
    moods = [e["mood"] for e in es if e.get("mood")]
    tags = {}
    for e in es:
        for t in e.get("tags", []):
            tags[t] = tags.get(t, 0) + 1
    out = ["", "<b>Journal</b>", f"• {len(es)} of 7 nights written"
           + (f" • average mood {sum(moods) / len(moods):.1f}/10" if moods else "")
           + (" • mostly " + ", ".join(t for t, _ in sorted(tags.items(), key=lambda x: -x[1])[:3]) if tags else "")]
    notes = "\n".join(f"{e['date']}: {e.get('summary') or e['text'][:500]}" for e in es)
    r = safe(lambda: llm_json(f"These are {NAME}'s journal notes from the past week. Reply with JSON only: "
                              '{"recap": "two or three short sentences in the second person about how the week went: '
                              'the main themes and anything that kept coming up. Kind and plain, no advice."}\n\n' + notes, 220, kind="Journal"), {})
    if isinstance(r, dict) and r.get("recap"):
        out.append(f"• {esc(str(r['recap']).strip())}")
    return out


def register(app):
    host.need(globals(), "B", "CAPS", "DASH", "OLLAMA", "OWNER", "TZ", "U", "_digest_lock", "_journal_morning", "_lock", "_tag", "ai_loaded", "big_call", "claim", "claimed_run", "count_tokens", "day_events", "gym", "journal_work", "llm_json", "run_info", "run_job", "run_purpose", "save", "send", "state", "tg", "write_json")

    router = app.router

    @router.get("/journal")
    def journal_view(req):
        day = journal_day()
        ctx = safe(lambda: journal_context(day), [])
        with _lock:
            return {"today": day, "date": now().date().isoformat(), "entries": journal_rows({day[:4], str(int(day[:4]) - 1)}),
                    "years": [day[:4], str(int(day[:4]) - 1)], "texts": {day[:7]: journal_texts(day[:7])}, "context": ctx, "now": jnow_view()}

    @router.get("/journal/now")
    def journal_now(req):
        with _lock:
            return jnow_view()

    router.add("GET", "/journal/weekly", lambda req: safe(recap_card, {}))
    router.add("GET", "/journal/deep", lambda req: safe(deep_view, {}))

    @router.get("/journal/deep/letters")
    def journal_letters(req):
        with _lock:
            return {"letters": safe(lambda: json.load(open(LETTERS_FILE)), []) or []}

    @router.get("/journal/month")
    def journal_month(req):
        m = req.query.get("m", "")
        if not re.fullmatch(r"\d{4}-\d{2}", m):
            return {"error": "not found"}, 404
        with _lock:
            return {"month": m, "texts": journal_texts(m)}

    @router.get("/journal/year")
    def journal_year(req):
        y = req.query.get("y", "")
        if not re.fullmatch(r"\d{4}", y):
            return {"error": "not found"}, 404
        with _lock:
            return {"year": y, "entries": journal_rows({y})}

    def journal_post(req):
        b, local = req.json(), req.client in ("127.0.0.1", "::1")  # the three re-run buttons are for the host only
        if req.path == "/journal/reai" and local:
            ds = [e["date"] for e in journal["entries"] if e.get("text", "").strip() and (not b.get("dates") or e["date"] in b["dates"])]
            with _lock:
                for e in journal["entries"]:
                    if e["date"] in ds:
                        e["sum_due"] = True
                        journal_save(e["date"])
            if b.get("now"):
                threading.Thread(target=lambda: journal_work(journal_night), daemon=True).start()
            return {"ok": True, "entries": len(ds)}
        if req.path == "/journal/deep/night" and local:
            threading.Thread(target=lambda: journal_work(lambda: run_job("Deep read and morning note (manual)", lambda: deep_night(force=True))), daemon=True).start()
            return {"ok": True}
        if req.path == "/journal/deep/run" and local:
            threading.Thread(target=lambda: journal_work(insights_run), daemon=True).start()
            return {"ok": True}
        return deep_api(req.path, b) if req.path.startswith("/journal/deep/") else journal_api(req.path, b)

    router.add_prefix("POST", "/journal/", journal_post)
