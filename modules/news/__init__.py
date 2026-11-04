"""News: feeds, topic headlines, short digests written by the AI, and search for a news topic."""
import email
import email.utils
import html
import json
import re
import threading
import time
import xml.etree.ElementTree as ET
from datetime import datetime
from urllib.parse import urlencode, urlparse

from core import host
from core.helpers import cached, esc, http, now, safe
from core.store import write_json

host.need(globals(), "BRIEF_NEWS", "DATA", "SEARX", "UA", "cfg")

# ================================================================ topic news (fresh headlines on demand)
FEEDS = {
    "tech": [("The Verge", "https://www.theverge.com/rss/index.xml"), ("Ars Technica", "https://feeds.arstechnica.com/arstechnica/index")],
    "science": [("ScienceDaily", "https://www.sciencedaily.com/rss/top/science.xml"), ("Nature", "https://www.nature.com/nature.rss")],
    "world": [("BBC", "https://feeds.bbci.co.uk/news/world/rss.xml"), ("Al Jazeera", "https://www.aljazeera.com/xml/rss/all.xml")],
    "india": [("The Hindu", "https://www.thehindu.com/news/national/feeder/default.rss"), ("Indian Express", "https://indianexpress.com/section/india/feed/"),
              ("Hindustan Times", "https://www.hindustantimes.com/feeds/rss/india-news/rssfeed.xml")],
    "sports": [("BBC Sport", "https://feeds.bbci.co.uk/sport/rss.xml"), ("Cricinfo", "https://www.espncricinfo.com/rss/content/story/feeds/0.xml")],
    "cricket": [("Cricinfo", "https://www.espncricinfo.com/rss/content/story/feeds/0.xml"), ("BBC Cricket", "https://feeds.bbci.co.uk/sport/cricket/rss.xml")],
    "f1": [("BBC F1", "https://feeds.bbci.co.uk/sport/formula1/rss.xml"), ("Formula 1", "https://www.formula1.com/en/latest/all.xml")],
    "business": [("BBC Business", "https://feeds.bbci.co.uk/news/business/rss.xml"), ("Mint", "https://www.livemint.com/rss/markets")],
    # new apps and tools taking off (the Wispr Flow kind): launches, plus the app and AI desks of tech sites
    # M&As: tech and finance deals only
    "mna": [("FT", "https://www.ft.com/mergers-acquisitions?format=rss"),
            ("Google News", "https://news.google.com/rss/search?hl=en-GB&gl=GB&ceid=GB:en&q=(merger+OR+acquisition+OR+acquire+OR+takeover+OR+buyout)+(tech+OR+software+OR+AI+OR+startup+OR+chip+OR+bank+OR+fintech+OR+%22private+equity%22+OR+insurer+OR+%22asset+manager%22)+when:2d"),
            ("TechCrunch M&A", "https://techcrunch.com/tag/mergers-and-acquisitions/feed/")],
    "launches": [("TechCrunch AI", "https://techcrunch.com/category/artificial-intelligence/feed/"), ("TechCrunch Apps", "https://techcrunch.com/category/apps/feed/"),
                 ("The Verge Apps", "https://www.theverge.com/rss/apps/index.xml"), ("The Verge AI", "https://www.theverge.com/rss/ai-artificial-intelligence/index.xml")],
}
TOPIC_NAMES = {"tech": "💻 Tech", "science": "🔬 Science", "world": "🌍 World", "india": "🇮🇳 India", "sports": "🏆 Sport",
               "cricket": "🏏 Cricket", "f1": "🏎 F1", "business": "📈 Business & markets", "launches": "🚀 New apps & tech", "mna": "🤝 M&As"}
TOPIC_WORDS = [  # most specific first
    ("launches", r"new apps?|new tools?|\blaunch(es|ed)?\b|product hunt|new (ai )?products?|apps? (to try|taking off)|trending apps?"),
    ("mna", r"\bm ?& ?as?\b|\bm and a\b|mergers?|acquisitions?|takeovers?|buyouts?"),
    ("f1", r"\bf1\b|formula ?(1|one)|grand prix|\bgp\b|verstappen|hamilton|leclerc|norris|piastri|antonelli|russell|ferrari|mclaren|red ?bull|mercedes"),
    ("cricket", r"cricket|\bipl\b|bcci|\bodi\b|\bt20\b|test match|kohli|rohit|bumrah"),
    ("business", r"business|market|stocks?|sensex|nifty|economy|finance|crypto|bitcoin"),
    ("tech", r"\btech|technology|\bai\b|artificial intelligence|gadget|apple|google|iphone|android|startup"),
    ("science", r"science|space|nasa|isro|research|discover|climate|health"),
    ("india", r"\bindia|indian|national|delhi|bengaluru|bangalore|mumbai|modi"),
    ("world", r"\bworld|international|global|politics|war|geopolitic"),
    ("sports", r"sports?|football|soccer|tennis|nba|olympic|premier league"),
]
# Words that just name the topic. Anything else left in the request (a driver, a party, a company) is a specific subject to search.
TOPIC_GENERIC = {"f1": r"\bf1\b|formula ?(1|one)|grand prix|\bgp\b|racing|race", "cricket": r"cricket|\bipl\b|\bodi\b|\bt20\b|test match|scores?|match",
                 "business": r"business|markets?|stocks?|share market|economy|finance", "tech": r"\btech\b|technology|gadgets?",
                 "science": r"science|space|research|discover(y|ies)", "india": r"\bindia\b|indian|national",
                 "world": r"\bworld\b|international|global|politics|geopolitics", "sports": r"sports?",
                 "launches": r"new apps?|new tools?|\blaunch(es|ed)?\b|product hunt|new (ai )?products?|trending apps?",
                 "mna": r"\bm ?& ?as?\b|\bm and a\b|mergers?|acquisitions?|takeovers?|buyouts?|deals?"}
last_headlines = {}
# Your own feeds (news.feeds): each one joins a topic, or makes a new section named by its topic
for _f in cfg("news.feeds", None) or []:
    if _f.get("url") and _f.get("topic"):
        _t = re.sub(r"[^a-z0-9]+", "-", _f["topic"].lower()).strip("-") or "mine"
        FEEDS.setdefault(_t, []).append((_f.get("name") or urlparse(_f["url"]).netloc, _f["url"]))
        TOPIC_NAMES.setdefault(_t, "📰 " + _f["topic"].strip())


def detect_topic(t):
    return next((k for k, pat in TOPIC_WORDS if re.search(pat, t)), None)


def short_desc(d, title=""):
    """First sentence or two of a feed summary, if it adds anything to the headline."""
    d = re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", d or ""))).strip()
    d = re.sub(r"\s*(Continue reading|Read more|The post .* appeared first on|Discussion\s*\|\s*Link|Comments?\s*\|).*$", "", d, flags=re.I)
    if len(d) < 25 or d.lower()[:40] in title.lower():
        return ""
    out = ""
    for sent in re.split(r"(?<=[.!?])\s+", d):
        if len(out) + len(sent) > 360:
            break
        out = f"{out} {sent}".strip()
    return out or d[:340].rsplit(" ", 1)[0] + "…"


@cached(600)
def feed_items(url):
    root = ET.fromstring(http(url, raw=True, timeout=12, headers={"User-Agent": UA}).encode())
    out = []
    for it in list(root.iter("item")) + list(root.iter("{http://www.w3.org/2005/Atom}entry")):
        title = (it.findtext("title") or it.findtext("{http://www.w3.org/2005/Atom}title") or "").strip()
        link = it.findtext("link") or ""
        if not link:
            l = it.find("{http://www.w3.org/2005/Atom}link")
            link = l.get("href", "") if l is not None else ""
        when = it.findtext("pubDate") or it.findtext("{http://www.w3.org/2005/Atom}updated") or ""
        desc = (it.findtext("description") or it.findtext("{http://www.w3.org/2005/Atom}summary")
                or it.findtext("{http://www.w3.org/2005/Atom}content") or "")
        ts = safe(lambda: email.utils.parsedate_to_datetime(when).timestamp()) or safe(lambda: datetime.fromisoformat(when.replace("Z", "+00:00")).timestamp())
        if title:
            out.append({"title": html.unescape(re.sub(r"<[^>]+>", "", title)), "link": link.strip(), "ts": ts, "desc": short_desc(desc, title)})
    return out


def ago(ts):
    if not ts:
        return ""
    m = int((time.time() - ts) / 60)
    return f"{m} min ago" if m < 60 else f"{m // 60}h ago" if m < 48 * 60 else f"{m // 1440} days ago"


STATE_PAGE = re.compile(r"/news/national/[a-z-]+/|/news/cities/")  # The Hindu's state and city pages: local, not national
FLUFF = re.compile(r"\bpodcast\b|send us your questions|^(watch|listen|quiz)\b|\bQ&A\b", re.I)
# stock-ticker and quote pages that Google News mixes in ("GSK stock trades at EUR 22.65", "... Estimates – OTC:XYZ")
JUNK = re.compile(r" - (TradingView|ad-hoc-news\.de|MarketBeat|Stock Titan|Investing\.com|Pluang)$|\bstock (trades|costs|price)\b|\bEstimates [–-] [A-Z]+:|\bAcquisition Corp", re.I)


def headlines_for(topic, n=7):  # newest first, mixed sources
    results = {}
    def grab(src, url):
        results[src] = [dict(x, src=src, title=re.sub(r"^STAT\+: ", "", x["title"])) for x in safe(lambda: feed_items(url), [])
                        if (not x["ts"] or time.time() - x["ts"] < 3 * 86400) and not FLUFF.search(x["title"]) and not JUNK.search(x["title"])
                        and not (topic == "india" and STATE_PAGE.search(x["link"]))]
    threads = [threading.Thread(target=grab, args=f) for f in FEEDS[topic]]
    [t.start() for t in threads]; [t.join(15) for t in threads]
    lists = [results.get(src, []) for src, _ in FEEDS[topic]]
    out, seen = [], set()
    for i in range(max(map(len, lists), default=0)):  # interleave sources, newest first within each
        for l in lists:
            if i < len(l):
                key = re.sub(r"\W+", "", l[i]["title"].lower())[:40]
                if key not in seen:
                    seen.add(key); out.append(l[i])
    out.sort(key=lambda x: -(x["ts"] or 0))  # newest first
    return out[:n]


@cached(6 * 3600)
def article_lead(url):
    """The first few paragraphs of a story, so the digest has real facts to work with (feeds give one line)."""
    page = http(url, raw=True, timeout=10, headers={"User-Agent": UA})
    page = re.sub(r"(?is)<(script|style|figure|aside|nav|footer)\b.*?</\1>", " ", page)
    out = ""
    for p in re.findall(r"(?is)<p\b[^>]*>(.*?)</p>", page):
        t = re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", p))).strip()
        if len(t) < 70 or re.search(r"cookie|subscribe|sign up|newsletter|all rights reserved|©", t, re.I):
            continue
        out = f"{out} {t}".strip()
        if len(out) > 900:
            break
    return out[:1000]


DIGEST_FILE = f"{DATA}/digests.json"
digests = {}
_digest_lock = threading.Lock()


DIGEST_PICK = {
    "mna": "Pick the {n} most significant mergers, acquisitions, takeovers and buyouts in TECH (software, AI, chips, internet, startups) and FINANCE (banks, "
           "fintech, payments, insurers, asset managers, exchanges, private equity) ONLY; ignore every other industry and stories that are not deals. "
           "Big deals and well-known companies first; skip SPAC filings and stock-price pages. For each: who is buying whom, the price if given, and where the deal stands (agreed, rumoured, approved, blocked).",
}


_STOP = set("a an the and or of in on for to with by at from as is are was were be has have had its it this that after over into new says said will".split())


def _words(t):
    return {w for w in re.findall(r"[a-z0-9$%]+", t.lower()) if w not in _STOP and len(w) > 2}


def same_story(title_a, text_a, title_b, text_b):
    """Two bullets about one event (often two outlets with the same news): their headlines or their summaries overlap heavily."""
    sim = lambda x, y: len(x & y) / max(1, min(len(x), len(y)))
    return sim(_words(title_a), _words(title_b)) >= 0.6 or sim(_words(text_a), _words(text_b)) >= 0.4


def digest_clean(text, title):
    """Guard rails on one AI bullet: no pasted headline, no "- Source" tails, no outlet credits, no [n] marks, no dashes."""
    t = re.sub(r"\s*\[\d+\]\s*", " ", text)
    head = re.sub(r"\s+-\s+[^-]{2,60}$", "", title).strip().rstrip(".")
    if len(head) > 25:
        t = t.replace(head + ".", "").replace(head, "")
    t = re.sub(r"\s+-\s+\w[\w .&'/]{1,40}\.{0,2}$", ".", t.strip())  # "... - 24/7 Wall St.."
    t = re.sub(r",?\s+(according to|reports?|reported by|as reported by|described [^.]{0,40}? by)\s+(the\s+)?(Seeking Alpha|Endpoints News|STAT|Reuters|Bloomberg|"
               r"BBC|Al Jazeera|The Verge|TechCrunch|FT|Financial Times|Yahoo Finance|CNBC|Fierce\w*|BioPharma Dive|Healthcare Dive|KFF Health News)\b", "", t)
    t = t.replace("—", ",").replace("–", "-")
    t = re.sub(r"\s{2,}", " ", re.sub(r"\.{2,}", ".", t)).strip()
    return t


NEWS_MODEL = "qwen3:30b-a3b"  # the old local news model: kept on disk if present, no longer loaded
NEWS_AI, NEWS_PRICE = cfg("models.claude_news", "claude-haiku-5-5"), (0.10, 0.50)  # writes the news; $ per million tokens in / out
_news_ai = None


def news_ai():
    """(provider, model) that writes the news, or (None, "") when there is no AI to use. news.ai: auto (default), claude, openai, ollama or none."""
    from core import ai_keys
    want = cfg("news.ai", None) or "auto"
    if want == "none":
        return None, ""
    for p in (("claude", "openai", "ollama") if want == "auto" else (want,)):
        if p in ai_keys.PROVIDERS and ai_keys.get(DATA, p):
            return p, cfg("news.model", None) or (NEWS_AI if p == "claude" else "")
        if p == "ollama" and CAPS.ok("ollama"):
            return p, cfg("news.model", None) or ""
    return None, ""


def news_json(prompt, max_tokens, think=False):
    """One reply as JSON from the news AI you chose (Claude, OpenAI or the local engine).
    Claude: one Haiku reply as JSON, counted on the SG page's AI usage with its cost. One retry when the JSON comes back broken.
    think: high effort, for picking (it follows the section rules only when it thinks). Otherwise thinking is off explicitly:
    Haiku 5.5 thinks by default and would spend the whole budget on it."""
    how = ({"thinking": {"type": "adaptive"}, "output_config": {"effort": "high"}, "max_tokens": max_tokens + 16000} if think else
           {"thinking": {"type": "disabled"}, "max_tokens": max_tokens})
    provider, model = news_ai()
    if provider == "ollama":
        return llm_json(prompt + "\nReply with the JSON only.", num_predict=max_tokens, timeout=300, kind="Brief", model=model or None)
    if provider == "openai":
        return openai_json(prompt, max_tokens, model)
    if provider != "claude":
        raise RuntimeError("no news AI is set up")
    global _news_ai
    if _news_ai is None:
        import anthropic
        from core import ai_keys
        _news_ai = anthropic.Anthropic(api_key=ai_keys.get(DATA, "claude"))
    for k in range(2):
        r = _news_ai.messages.create(model=model or NEWS_AI, messages=[{"role": "user", "content": prompt + "\nReply with the JSON only."}], **how)
        count_tokens("Brief", {"model": NEWS_AI, "prompt_eval_count": r.usage.input_tokens, "eval_count": r.usage.output_tokens},
                     (r.usage.input_tokens * NEWS_PRICE[0] + r.usage.output_tokens * NEWS_PRICE[1]) / 1e6)
        t = "".join(b.text for b in r.content if b.type == "text")
        try:
            return json.loads(t[t.index("{"):t.rindex("}") + 1])
        except ValueError:
            if k:
                raise
def openai_json(prompt, max_tokens, model):
    """One OpenAI reply as JSON, counted on the AI usage page (no price: OpenAI prices vary by model, so only tokens are counted)."""
    from core import ai_keys
    key = ai_keys.get(DATA, "openai")
    if not model:
        ok, ids = ai_keys.models("openai", key)
        model = ai_keys.suggest("openai", ids) if ok else ""
    r = http("https://api.openai.com/v1/chat/completions", {"model": model, "messages": [{"role": "user", "content": prompt + "\nReply with the JSON only."}],
             "response_format": {"type": "json_object"}, "max_completion_tokens": max_tokens + 2000}, timeout=120, headers={"Authorization": f"Bearer {key}"})
    u = r.get("usage") or {}
    count_tokens("Brief", {"model": model, "prompt_eval_count": u.get("prompt_tokens", 0), "eval_count": u.get("completion_tokens", 0)}, 0.0)
    t = r["choices"][0]["message"]["content"] or "{}"
    return json.loads(t[t.index("{"):t.rindex("}") + 1])


STORY_FILE = f"{DATA}/story-cache.json"
stories = {}  # link -> {"text", "at"}: each story is summarised once, later runs reuse it


def news_skip(topic):
    """Extra picking rules per section: what the test runs got wrong (quizzes in F1, domain sales counted as deals)."""
    base = ("Rank by importance, most important first. Never pick two stories about the same event, even from different outlets. "
            "Skip anything that is not real news: quizzes, games, listicles, opinion, music or celebrity stories, adverts, things for sale. "
            "Pick fewer when not enough stories fit these rules; never fill the list with weak ones.")
    if topic == "mna":
        base += (" Only the industries named above. Only real deals that name BOTH the buyer and the company or business being bought; skip a story "
                 "that doesn't say what is bought. Big deals first: $100 million or more, or well-known companies. Skip small local deals (a small "
                 "bank, a single shop or site) unless there is nothing better. "
                 "Not funding rounds, partnerships, licensing, domain names or assets listed for sale, stock tips or earnings.")
    if topic == "launches":
        base += (" Only things people can use or try now or soon: new apps, AI tools, products and features. Not lawsuits, policy, earnings, "
                 "workplace or culture stories, or stories about one person.")
    if topic == "f1":
        base += " Only Formula 1 racing: drivers, teams, races, results, the championship, contracts and rules."
    return base


def make_digest(topic, n=5):
    run_purpose(f"news {topic}")
    """The news model picks the top stories, then summarises only the ones it has not summarised before."""
    items = headlines_for(topic, 10)
    if not items:
        return
    if news_ai()[0] is None:  # no AI: the newest headlines, as they are, so the brief still has news and never waits for a summary that won't come
        digests[topic] = {"at": time.time(), "keys": [i["link"] for i in items], "items": [{"link": i["link"], "title": i["title"]} for i in items],
                          "bullets": [(i["title"] if i["title"][-1:] in ".!?" else i["title"] + ".", k) for k, i in enumerate(items[:n], 1)], "plain": True}
        safe(lambda: write_json(DIGEST_FILE, digests))
        return
    leads = {}
    th = [threading.Thread(target=lambda i=i: leads.__setitem__(i["link"], safe(lambda: article_lead(i["link"]), ""))) for i in items if i.get("link")]
    [t.start() for t in th]; [t.join(15) for t in th]
    listing = "\n".join(f"[{k}] {i['title']}. {leads.get(i['link']) or i.get('desc', '')}" for k, i in enumerate(items, 1))
    want = min(n + 2, len(items))  # spares, so the guard rails below can drop a bad bullet and still fill the section
    pick = DIGEST_PICK[topic].format(n=want) if topic in DIGEST_PICK else (f"Pick the {want} most interesting stories about NEW apps, AI tools, products or features people can actually use or try (the kind of thing Wispr Flow was; "
            "prefer launches and fast-growing apps over funding, lawsuits, policy or earnings). For each: what it is, what it does for you, and why people are talking about it."
            if topic == "launches" else
            "Pick the {n} most important stories (national or global significance beats local events). For each: what happened, then the key facts from the story "
            "(who, numbers, where, what happens next).").format(n=want)
    j = news_json(f"News stories:\n{listing}\n\n{pick}\n{news_skip(topic)}\nFirst give each story you pick a short label naming the underlying event (who, what, where). Two stories are the SAME event when they cover the same happening, even from different outlets or angles (an aid convoy entering a town and the evacuation of that town under the same truce are one event): keep only the better one.\nReply JSON {{\"picks\": [{{\"event\": \"short label\", \"n\": story number}}, ...]}} with the best first.",
                  max_tokens=500, think=True)
    picks = []
    for x in j.get("picks") or []:
        src = safe(lambda: int(x.get("n") if isinstance(x, dict) else x), 0)
        if 1 <= src <= len(items) and src not in picks and not any(same_story(items[src - 1]["title"], "", items[p - 1]["title"], "") for p in picks):
            picks.append(src)
    picks = picks[:want]
    new = [p for p in picks if items[p - 1]["link"] not in stories]
    run_info("stories", f"{len(picks)} picked, {len(new)} new")
    if new:
        part = "\n".join(f"[{p}] {items[p - 1]['title']}. {leads.get(items[p - 1]['link']) or items[p - 1].get('desc', '')}" for p in new)
        j = news_json(f"News stories:\n{part}\n\nAbout this section: {pick}\nFor each story above give 'what': one sentence (15 to 25 words) saying what happened, and 'detail': one more sentence (15 to 30 words) with further facts from the story (numbers, who, when, what happens next) that are NOT already in 'what' (leave 'detail' empty when the story has no further facts). Only facts given in the story. Never talk about the story or the source itself (no 'the story does not give', 'reported as', 'the excerpt'): if a fact isn't there, leave it out. "
                     "no commentary like 'this highlights' or 'underscores'. Never name the news site. Never repeat the headline. No intro. "
                     'Reply JSON {"bullets": [{"src": story number, "what": "...", "detail": "..."}]}', max_tokens=220 * len(new) + 300)
        for b in j.get("bullets") or []:
            src = safe(lambda: int(b.get("src")), 0)
            if src not in new:
                continue
            parts = [str(b.get(k) or "").strip() for k in ("what", "detail", "text")]
            text = digest_clean(" ".join(x if x[-1:] in ".!?" else x + "." for x in parts if x), items[src - 1]["title"])
            if len(text) >= 40:
                stories[items[src - 1]["link"]] = {"text": text, "at": time.time()}
        for k in [k for k, v in stories.items() if time.time() - v["at"] > 3 * 86400]:
            stories.pop(k)
        safe(lambda: write_json(STORY_FILE, stories))
    bullets = []
    for src in picks:
        text = (stories.get(items[src - 1]["link"]) or {}).get("text")
        if not text or any(same_story(items[src - 1]["title"], text, items[s2 - 1]["title"], t2) for t2, s2 in bullets):
            continue  # not summarised, or a second bullet about a story already in
        bullets.append((text, src))
    if bullets:
        digests[topic] = {"at": time.time(), "keys": [i["link"] for i in items], "items": [{"link": i["link"], "title": i["title"]} for i in items],
                          "bullets": bullets[:n]}
        safe(lambda: write_json(DIGEST_FILE, digests))


_news_lock = threading.Lock()  # one news run at a time


def refresh_digests(topics=tuple(k for k, _, _ in BRIEF_NEWS), wait=False):
    """Haiku writes the news, so nothing waits for the journal or the CPU to cool."""
    if not 5 <= now().hour < 24:
        return
    return run_job("News: " + ", ".join(topics), lambda: news_run(topics, wait))


def news_run(topics, wait):
    if not _news_lock.acquire(timeout=600 if wait else -1, blocking=wait):
        return "skipped"
    try:
        for t in topics:
            safe(lambda: make_digest(t))
    finally:
        _news_lock.release()


def news_rows(topic, items, n=3, max_age=25 * 3600):  # 25 h: one run a day, plus an hour of slack
    """[(html, plain)] for a news section: what happened, then a small [1] link to the story."""
    link = lambda k, url: f' <a href="{esc(url)}">[{k}]</a>' if url else ""
    d = digests.get(topic)
    if d and time.time() - d["at"] < max_age and d["bullets"]:  # a section may have fewer than n: fewer beats weak picks
        return [(f"• {esc(text)}" + link(k, d["items"][src - 1]["link"]), f"• {text}") for k, (text, src) in enumerate(d["bullets"][:n], 1)]
    rows = []
    for k, i in enumerate(items[:n], 1):
        title = i["title"].rstrip(".") + ("" if i["title"].rstrip(".")[-1:] in "?!" else ".")
        rest = f" {i['desc']}" if i.get("desc") else ""
        rows.append((f"• <b>{esc(title)}</b>{esc(rest)}" + link(k, i["link"]), f"• {title}{rest}"))
    return rows


def live_digest(per=2, title=None, buttons=True):
    """Fresh headlines from every section, right now: world, India, tech, science, markets, sport and an F1 corner."""
    typing()
    secs = ["world", "india", "launches", "tech", "science", "business", "sports", "f1"]
    got = {}
    threads = [threading.Thread(target=lambda k=k: got.__setitem__(k, headlines_for(k, per))) for k in secs]
    f1_info = {}
    threads.append(threading.Thread(target=lambda: f1_info.__setitem__("lines", safe(f1_lines, []))))
    [t.start() for t in threads]; [t.join(20) for t in threads]
    lines = [title or f"🗞 <b>Latest headlines</b> • {now():%-I:%M %p}"]
    for k in secs:
        items = got.get(k) or []
        last_headlines[k] = items
        if k == "f1" and f1_info.get("lines"):
            lines += ["", "<b>🏎 F1 corner</b>"] + f1_info["lines"][1:]  # next race, last podium, standings
            if items:
                lines += [h for h, _ in news_rows(k, items, per)]
        elif items:
            lines += ["", f"<b>{TOPIC_NAMES[k]}</b>"] + [h for h, _ in news_rows(k, items, per)]
    send("\n".join(lines), [[B("🏎 F1", "topic:f1"), B("🏏 Cricket", "topic:cricket"), B("💻 Tech", "topic:tech")],
                            [B("🇮🇳 India", "topic:india"), B("🌍 World", "topic:world"), B("📈 Markets", "topic:business")],
                            [B("🧠 Summarise the news", "sum:all")]] if buttons else None)


def topic_news(topic):
    typing()
    items = headlines_for(topic)
    last_headlines[topic] = items
    lines = []
    if topic == "f1":
        lines += safe(f1_lines, ["🏎 <b>Formula 1</b>"]) + [""]
    elif topic == "cricket":
        lines += cricket_lines() + [""]
    lines.append(f"<b>{TOPIC_NAMES[topic]} headlines</b>" if topic not in ("f1", "cricket") else "<b>Latest news</b>")
    lines += [h for h, _ in news_rows(topic, items, 6)] or ["Couldn't load headlines right now."]
    send("\n".join(lines), [[B("🧠 Summarise for me", f"sum:{topic}"), B("🔄 Refresh", f"topic:{topic}")]])


def summarise_topic(topic):
    if topic == "all":
        items = [i for k in ("world", "india", "tech", "science", "business", "sports", "f1") for i in last_headlines.get(k, [])]
    else:
        items = last_headlines.get(topic) or headlines_for(topic)
    if not items:
        return send("No headlines to summarise right now.")
    msgs = [{"role": "system", "content": SYSTEM},
            {"role": "user", "content": "Headlines:\n" + "\n".join(f"- {i['title']} ({i['src']})" for i in items)
             + "\n\nIn 3 or 4 short sentences, tell me what's going on. Only use these headlines."}]
    stream_to_chat(llm_stream(msgs, num_predict=260, temperature=0.3, kind="Brief"), prefix=f"🧠 <b>{TOPIC_NAMES.get(topic, '🗞 The news')} in short</b>\n")


STOP = {"the", "and", "for", "with", "news", "latest", "about", "from", "what", "who", "how", "why", "are", "was", "his", "her", "its"}


FOREIGN = set("da do em de het een van zo laat begint la le les il lo gli della nella più con per que el los las del por para da das dos uma não der die und mit für ist auf".split())


def relevant(q, results):
    """Keep results that actually mention the subject (its words, or its acronym: 'cockroach janta party' ~ 'CJP'), newest first."""
    words = [w for w in re.findall(r"[a-z0-9]+", q.lower()) if len(w) > 2 and w not in STOP]
    big = [w for w in q.split() if len(w) > 2 and w.lower() not in STOP]
    acronym = "".join(w[0] for w in big).lower() if len(big) >= 2 else ""
    need = max(1, (len(words) + 1) // 2)
    keep = []
    for x in results:
        hay = f"{x.get('title', '')} {x.get('content', '')}".lower()
        if sum(1 for w in re.findall(r"[^\x00-\x7f]", x.get("title", ""))) > len(x.get("title", "")) * 0.3:
            continue  # mostly non-Latin script
        title_words = re.findall(r"[a-zà-ÿ]+", x.get("title", "").lower())
        title = x.get("title", "")
        if (len(title_words) < 4 or sum(w in FOREIGN for w in title_words) >= 2 or re.search(r"[ãõçñ¿¡]", title)
                or len(re.findall(r"[áéíóúàèìòùâêôü]", title)) >= 2 or re.match(r"^(br|es|fr|de|it|pt|nl|jp|ru|tr|mx|ar)\.", urlparse(x.get("url", "")).netloc)):
            continue  # not an article headline, or not English
        score = sum(1 for w in words if re.search(rf"\b{re.escape(w)}", hay)) + (need if acronym and re.search(rf"\b{acronym}\b", hay) else 0)
        if score >= need:
            keep.append((score, x.get("publishedDate") or "", x))
    keep.sort(key=lambda k: (k[1], k[0]), reverse=True)
    return [k[2] for k in keep]


def news_search(q):
    """Any other topic: recent news via the private search engine."""
    typing()
    try:
        r = http(f"{SEARX}/search?" + urlencode({"q": q, "format": "json", "categories": "news", "time_range": "day", "language": "en"}), timeout=20)
        if len(relevant(q, r.get("results", []))) < 4:
            r = http(f"{SEARX}/search?" + urlencode({"q": q, "format": "json", "categories": "news", "time_range": "week", "language": "en"}), timeout=20)
    except Exception as e:
        return send(f"News search isn't working right now ({esc(e)}).")
    items, seen = [], set()
    for x in relevant(q, r.get("results", [])):
        k = re.sub(r"\W+", "", x.get("title", "").lower())[:40]
        if x.get("url") and k and k not in seen:
            seen.add(k); items.append(x)
    if not items:
        return send(f"I couldn't find recent news about <i>{esc(q)}</i>.")
    lines = [f"🗞 <b>Latest on {esc(q)}</b>"] + [
        f"• <a href=\"{esc(x['url'])}\">{esc(x['title'])}</a> <i>• {esc(urlparse(x['url']).netloc.removeprefix('www.'))}"
        + (f" • {ago(safe(lambda: datetime.fromisoformat(x['publishedDate']).timestamp()))}" if x.get("publishedDate") else "") + "</i>"
        for x in items[:7]]
    send("\n".join(lines), [[B("🧠 Summarise for me", f"nsum:{q[:50]}")]])


def _routes(router):
    @router.get("/news")
    def news(req):
        topics = [k for k, _, _ in BRIEF_NEWS if k in FEEDS] + [k for k in ("world", "tech", "business", "science") if k not in [b[0] for b in BRIEF_NEWS]]
        got = {}
        th = [threading.Thread(target=lambda k=k: got.__setitem__(k, safe(lambda: headlines_for(k, 4), []))) for k in topics]
        [x.start() for x in th]; [x.join(15) for x in th]
        return {"at": time.time(), "sections": [
            {"key": k, "name": TOPIC_NAMES[k], "rows": [h for h, _ in news_rows(k, got[k], 3)]} for k in topics if got.get(k)]}


def _setup_routes(router):
    from core import ai_keys
    from core.settings import guard_request

    @router.get("/news/setup")
    def news_setup(req):
        """Everything the News page in Settings shows. Keys are never sent back, only whether one is set."""
        eff = SETTINGS.merged()
        n, sched = eff.get("news") or {}, eff.get("schedule") or {}
        provider, model = news_ai()
        topics = [{"key": k, "name": re.sub(r"^\W+\s*", "", TOPIC_NAMES.get(k, k)), "sources": [x for x, _ in FEEDS[k]]} for k in FEEDS]
        return {"topics": topics, "chosen": n.get("topics") or [k for k, _, _ in BRIEF_NEWS], "feeds": n.get("feeds") or [],
                "ai": n.get("ai") or "auto", "model": n.get("model") or "", "using": {"provider": provider, "model": model},
                "keys": {p: bool(ai_keys.get(DATA, p)) for p in ai_keys.PROVIDERS}, "local": CAPS.ok("ollama"),
                "briefing": sched.get("briefing") or "7:00 AM", "news_at": (sched.get("news_at") or ["6:30 AM"])}

    @router.post("/news/key")
    def news_key(req):
        """Check a key with its provider, then keep it. An empty key removes it."""
        if bad := guard_request(SETTINGS, req):
            return bad
        b = req.json() or {}
        provider, key = b.get("provider"), str(b.get("key") or "").strip()
        if provider not in ai_keys.PROVIDERS:
            return {"ok": False, "error": "Choose Claude or OpenAI."}, 400
        if not key:
            ai_keys.save(DATA, provider, "")
            return {"ok": True, "models": []}
        ok, out = ai_keys.models(provider, key)
        if not ok:
            return {"ok": False, "error": out}, 400
        ai_keys.save(DATA, provider, key)
        global _news_ai
        _news_ai = None
        return {"ok": True, "models": out, "suggested": ai_keys.suggest(provider, out)}

    @router.get("/news/models")
    def news_models(req):
        provider = req.query.get("provider", "")
        if provider == "ollama":
            try:
                return {"ok": True, "models": sorted(m["name"] for m in http(f"{OLLAMA}/api/tags", timeout=5).get("models", []))}
            except Exception:
                return {"ok": False, "error": "The local AI engine is not answering."}
        key = ai_keys.get(DATA, provider)
        if not key:
            return {"ok": False, "error": "Add a key first."}
        ok, out = ai_keys.models(provider, key)
        return {"ok": True, "models": out, "suggested": ai_keys.suggest(provider, out)} if ok else {"ok": False, "error": out}

    @router.post("/news/feed/check")
    def news_feed_check(req):
        """Read a feed once, so a wrong address is caught before it is saved."""
        url = str((req.json() or {}).get("url") or "").strip()
        if not url.lower().startswith(("http://", "https://")):
            return {"ok": False, "error": "A feed address starts with http:// or https://."}, 400
        try:
            items = feed_items(url)
        except Exception:
            return {"ok": False, "error": "That address did not give a news feed. Look for an RSS or Atom link on the site."}, 400
        if not items:
            return {"ok": False, "error": "The feed has no stories right now."}, 400
        return {"ok": True, "sample": [i["title"] for i in items[:3]], "name": urlparse(url).netloc.removeprefix("www.")}

    @router.post("/news/setup")
    def news_setup_save(req):
        if bad := guard_request(SETTINGS, req):
            return bad
        b, ch = req.json() or {}, {}
        if "topics" in b:
            ch["news.topics"] = [str(t) for t in b["topics"]][:12]
        if "feeds" in b:
            ch["news.feeds"] = [{"name": str(f.get("name", ""))[:40], "url": str(f.get("url", "")), "topic": str(f.get("topic", "") or "My feeds")[:30]}
                                for f in b["feeds"] if isinstance(f, dict) and f.get("url")][:20]
        if "ai" in b:
            if b["ai"] not in ("auto", "claude", "openai", "ollama", "none"):
                return {"ok": False, "error": "Unknown AI choice."}, 400
            ch["news.ai"] = b["ai"]
        if "model" in b:
            ch["news.model"] = str(b["model"])[:80]
        if "briefing" in b:
            ch["schedule.briefing"] = b["briefing"]
        if "news_at" in b:
            ch["schedule.news_at"] = b["news_at"] if isinstance(b["news_at"], list) else [b["news_at"]]
        ok, problems = SETTINGS.set(ch)
        return ({"ok": True, "restart": True}, 200) if ok else ({"ok": False, "error": " ".join(problems)}, 400)


def register(app):
    host.need(globals(), "B", "CAPS", "CLAUDE_KEY", "OLLAMA", "SETTINGS", "SYSTEM", "llm_json", "count_tokens", "cricket_lines", "f1_lines", "llm_stream",
              "run_info", "run_job", "run_purpose", "send", "stream_to_chat", "typing")
    _routes(app.router)
    _setup_routes(app.router)
