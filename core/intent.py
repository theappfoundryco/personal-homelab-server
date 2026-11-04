"""Intent understanding: every message is embedded and a trained classifier picks what it is asking for. Things that live in the app
(the local model, the data folder) are reached through core.host: DATA and cfg early, the rest bound once by bind()."""
import json, math, os, re, threading

from core import host
from core.helpers import http, safe
from core.store import write_json

host.need(globals(), "cfg")

QUESTION = (r"^(tell me|explain|describe|who|what|when|where|why|how|which|is|are|was|were|did|does|do|can|could|should|will|would|"
            r"compare|give me (a |an )?(summary|overview|rundown|recap)|summari[sz]e|what do you know)\b")
NEWS_WORDS = r"\bnews\b|\bheadlines?\b|\bupdates?\b|\blatest (on|in|about|from|with)\b|happening|going on|what did i miss"


def is_question(t):
    return bool(re.search(QUESTION, t) or t.rstrip().endswith("?"))


# Every message is embedded with embeddinggemma and a trained classifier picks the intent (~30 ms). It was trained on
# ~8,600 labelled messages (see the classifier notes in the docs); 97% right on phrases it never saw.
# Under 50% sure, the local LLM settles it between the top two. What he corrected ("wrong" -> pick what he meant) wins.
# Without the classifier file it falls back to nearest example in intents.py, as before.
EMBED_MODEL = cfg("models.embed", "embeddinggemma")
EMBED_PREFIX = "task: classification | query: "
DATA = os.environ.get("HL_DATA", "/data")
INTENT_CLF_FILE = f"{DATA}/intent_clf.json"
CLF_SURE = 0.5
LEARNED_FILE = f"{DATA}/learned_intents.json"
INTENT_NAMES = {"answer": "🔎 Answer my question", "chat": "💬 Just chat", "briefing": "☀️ Briefing", "news": "🗞 News headlines",
                "sports": "🏆 F1 / cricket dashboard", "weather": "🌦 Weather", "my_day": "📅 My calendar", "evening_plan": "🌙 Plan for tomorrow",
                "weekly_report": "📊 Weekly report", "server": "🖥 Server health", "restart_app": "🔄 Restart an app", "logs": "📜 App logs",
                "free_ai_memory": "🧹 Free AI memory", "reboot_server": "⏻ Restart server", "add_note": "📝 Save a note", "manage_notes": "✏️ Change or delete a note", "manage_reminders": "✏️ Change or cancel a reminder",
                "show_notes": "📝 Show notes", "add_reminder": "⏰ Set a reminder", "show_reminders": "⏰ Show reminders",
                "currency": "💱 Convert currency", "flights": "✈️ My flights", "email": "📧 Email", "add_goal": "🎯 Save a goal"}
_index = {"vecs": [], "labels": [], "texts": []}
_index_lock = threading.Lock()


def embed(texts):
    r = http(f"{OLLAMA}/api/embed", {"model": EMBED_MODEL, "input": [EMBED_PREFIX + t for t in texts], "keep_alive": -1}, timeout=120)
    count_tokens("Other", r)
    out = []
    for v in r["embeddings"]:
        n = sum(x * x for x in v) ** 0.5 or 1
        out.append([x / n for x in v])
    return out


def learned():
    return safe(lambda: json.load(open(LEARNED_FILE)), {})


def build_index():
    import importlib, intents
    importlib.reload(intents)
    pairs = [(k, t) for k, v in {**intents.EXAMPLES, **module_examples()}.items() for t in v] + [(k, t) for t, k in learned().items()]
    cache_file = f"{DATA}/intent_vectors.json"
    cache = safe(lambda: json.load(open(cache_file)), {})
    if cache.get("model") != EMBED_MODEL:
        cache = {"model": EMBED_MODEL, "vecs": {}}
    missing = [t for _, t in pairs if t not in cache["vecs"]]
    for i in range(0, len(missing), 64):
        for t, v in zip(missing[i:i + 64], embed(missing[i:i + 64])):
            cache["vecs"][t] = v
    if missing:
        write_json(cache_file, cache)
    with _index_lock:
        _index.update(labels=[k for k, _ in pairs], texts=[t for _, t in pairs], vecs=[cache["vecs"][t] for _, t in pairs])


def ai_pick(text, a, b):
    """Settle a near-tie between two intents with the local LLM (short prompt, one word out)."""
    j = llm_json(f"Message from {NAME} to their assistant: \"{text}\"\n"
                 f"Which does he want?\nA = {INTENT_NAMES[a]}\nB = {INTENT_NAMES[b]}\n"
                 "A question about the world (sport seasons, people, prices, how things work) means Answer my question. "
                 "Asking to note, save, remember or write something down means Save a note, whatever the topic. "
                 'Reply JSON {"pick": "A" or "B"}', num_predict=12)
    return a if str(j.get("pick", "A")).strip().upper().startswith("A") else b


_clf = {}


def clf_rank(q):
    """Intents by probability from the trained classifier (a calibrated linear SVM: per class a linear score and a sigmoid,
    normalised, averaged over its folds). None if the file isn't there."""
    if "m" not in _clf:
        _clf["m"] = safe(lambda: json.load(open(INTENT_CLF_FILE)), None)
    m = _clf["m"]
    if not m:
        return None
    ps = []
    for f in m["models"][0]["folds"]:
        d = [sum(a * b for a, b in zip(w, q)) + b0 for w, b0 in zip(f["coef"], f["b"])]
        p = [1 / (1 + math.exp(min(500, a * v + c))) for v, a, c in zip(d, f["a"], f["c"])]
        s = sum(p) or 1
        ps.append([x / s for x in p])
    return sorted(zip(m["classes"], (sum(c) / len(ps) for c in zip(*ps))), key=lambda x: -x[1])


def classify(text):
    fixed = {k.lower().strip(): v for k, v in learned().items()}
    if (k := fixed.get(text.lower().strip())) in INTENT_NAMES:
        return k, "learned"
    q = embed([text])[0]
    if (r := clf_rank(q)):
        (i1, s1), (i2, _) = r[:2]
        unsure, how = s1 < CLF_SURE, f"clf {s1:.2f}"
    else:
        if not _index["vecs"]:
            build_index()
        best = {}
        with _index_lock:
            for v, l in zip(_index["vecs"], _index["labels"]):
                s = sum(a * b for a, b in zip(q, v))
                if s > best.get(l, -1):
                    best[l] = s
        (i1, s1), (i2, s2) = sorted(best.items(), key=lambda x: -x[1])[:2]
        unsure, how = s1 - s2 < 0.04, f"{s1:.2f}/{s1 - s2:.2f}"
    t = text.lower()
    # A question about the world is an answer, even if it mentions a news-ish topic ("tell me about Verstappen's season").
    if i1 in ("news", "sports") and is_question(t) and not re.search(NEWS_WORDS, t):
        return "answer", "rule"
    if unsure:
        return safe(lambda: ai_pick(text, i1, i2), i1), "ai"
    return i1, how


def learn(text, intent):
    with _lock:
        d = learned()
        d[text] = intent
        write_json(LEARNED_FILE, d, indent=1)
    threading.Thread(target=build_index, daemon=True).start()

NEEDS = ("OLLAMA", "NAME", "count_tokens", "llm_json", "module_examples", "_lock")


def bind():
    """Called by the app once everything in NEEDS has been provided."""
    host.need(globals(), *NEEDS)
