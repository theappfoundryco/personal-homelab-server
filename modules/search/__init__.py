"""Web search with sources, link and YouTube summaries, photo reading and voice notes."""
import base64
import re
import uuid
from html.parser import HTMLParser
from urllib.parse import urlencode, urlparse

from core import host
from core.helpers import cached, esc, http, now, safe

# ================================================================ search, links, photos, voice
def f1_context(t):
    """Official F1 data for the current season: standings with wins, and race-by-race results for any driver mentioned."""
    out = [strip_tags(l) for l in safe(f1_lines, [])]
    st = safe(lambda: jolpica("driverStandings?limit=30")["StandingsTable"]["StandingsLists"][0]["DriverStandings"], [])
    if st:
        out.append("Driver standings: " + "; ".join(
            f"{d['position']}. {d['Driver']['givenName']} {d['Driver']['familyName']} ({d['Constructors'][0]['name'] if d.get('Constructors') else ''}) "
            f"{d['points']} pts, {d['wins']} wins" for d in st[:12]))
    cs = safe(lambda: jolpica("constructorStandings")["StandingsTable"]["StandingsLists"][0]["ConstructorStandings"], [])
    if cs:
        out.append("Team standings: " + "; ".join(f"{c['position']}. {c['Constructor']['name']} {c['points']} pts" for c in cs[:6]))
    for d in st:
        dr = d["Driver"]
        if re.search(rf"\b({re.escape(dr['familyName'].lower())}|{re.escape(dr.get('code', '@@').lower())})\b", t):
            races = safe(lambda: jolpica(f"drivers/{dr['driverId']}/results?limit=40")["RaceTable"]["Races"], [])
            if races:
                out.append(f"{dr['givenName']} {dr['familyName']} {races[0]['season']} results by round: " + "; ".join(
                    f"R{r['round']} {r['raceName'].replace(' Grand Prix', '')}: P{r['Results'][0]['position']}"
                    + ("" if r["Results"][0]["status"] in ("Finished",) or r["Results"][0]["status"].startswith("+") else f" ({r['Results'][0]['status']})")
                    for r in races))
    return "\n".join(out)


def live_context(t):
    t = t.lower()
    parts = []
    if re.search(dict(TOPIC_WORDS)["f1"], t):
        parts.append(f1_context(t))
    if re.search(dict(TOPIC_WORDS)["cricket"], t):
        parts.append(strip_tags("\n".join(cricket_lines())))
    if re.search(r"\b(weather|rain|temperature)\b", t):
        parts.append(strip_tags("\n".join(safe(weather_lines, []))))
    return "\n".join(p for p in parts if p)


def search(q):
    typing()
    query = re.sub(r"(?i)^(tell me (about|more about)|explain|describe|give me (a |an )?(summary|overview|rundown) of|what do you know about)\s+", "", q).strip(" ?")
    live = safe(lambda: live_context(q), "")
    try:
        r = http(f"{SEARX}/search?" + urlencode({"q": query, "format": "json", "safesearch": 1, "language": "en"}), timeout=20)
        results = [x for x in r.get("results", []) if x.get("url")][:6]
    except Exception as e:
        results = []
        if not live:
            return send(f"Search isn't working right now ({esc(e)}).")
    if not results and not live:
        return send("I couldn't find anything for that. Try different words?")
    sources = "\n".join(f"[{i}] {x.get('title', '')}: {x.get('content', '')[:500]}" for i, x in enumerate(results, 1))
    broad = re.search(r"(?i)^(tell me|explain|describe|give me|what do you know|compare|how (has|did|is) .* (season|year|going))|season|overview|summary|history", q)
    msgs = [{"role": "system", "content": SYSTEM + f" Today is {now():%d %B %Y}."},
            {"role": "user", "content": f"Question: {q}\n\n"
                                        + (f"Live official data (most reliable, prefer it over search results):\n{live}\n\n" if live else "")
                                        + (f"Search results:\n{sources}\n\n" if sources else "")
                                        + ("Give a helpful overview in 5 to 8 short bullets with the key numbers, then one line takeaway. "
                                           if broad else "Answer in 2 to 5 sentences. ")
                                        + "Use only the data above. Cite search results like [1]. If the data doesn't answer it, say so."}]
    links = "\n\n" + "\n".join(f"[{i}] <a href=\"{esc(x['url'])}\">{esc(urlparse(x['url']).netloc.removeprefix('www.'))}</a>"
                               for i, x in enumerate(results[:4], 1))
    stream_to_chat(llm_stream(msgs, num_predict=600 if broad else 350, temperature=0.3), prefix="🔎 ", footer=links if results else "")


class TextGrab(HTMLParser):
    def __init__(self):
        super().__init__()
        self.parts, self.skip, self.title, self.in_title, self.meta = [], 0, "", False, ""

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag in ("script", "style", "nav", "footer", "header", "aside", "form", "noscript"):
            self.skip += 1
        if tag == "title":
            self.in_title = True
        if tag == "meta" and a.get("name", a.get("property", "")) in ("description", "og:description"):
            self.meta = self.meta or a.get("content", "")
        if tag in ("p", "li", "h1", "h2", "h3", "br"):
            self.parts.append("\n")

    def handle_endtag(self, tag):
        if tag in ("script", "style", "nav", "footer", "header", "aside", "form", "noscript"):
            self.skip = max(0, self.skip - 1)
        if tag == "title":
            self.in_title = False

    def handle_data(self, data):
        if self.in_title:
            self.title += data
        elif not self.skip:
            self.parts.append(data)


def youtube_text(url):
    vid = (re.search(r"(?:v=|youtu\.be/|shorts/|live/)([\w-]{11})", url) or [None, None])[1]
    if not vid:
        return None, None
    from youtube_transcript_api import YouTubeTranscriptApi
    try:
        t = YouTubeTranscriptApi().fetch(vid, languages=["en", "en-IN", "en-US", "hi"])
        text = " ".join(s.text for s in t)
    except AttributeError:
        text = " ".join(s["text"] for s in YouTubeTranscriptApi.get_transcript(vid, languages=["en", "hi"]))
    title = safe(lambda: http(f"https://www.youtube.com/oembed?url=https://youtu.be/{vid}&format=json", timeout=10)["title"], "YouTube video")
    return title, text


def summarise_link(url, question=None):
    typing()
    title, text = None, None
    try:
        if re.search(r"youtube\.com|youtu\.be", url):
            title, text = youtube_text(url)
        if not text:
            page = http(url, raw=True, timeout=25, headers={"User-Agent": UA, "Accept-Language": "en"})
            g = TextGrab(); g.feed(page)
            title = title or g.title.strip()
            text = re.sub(r"\n\s*\n+", "\n", "".join(g.parts)).strip()
            text = "\n".join(l for l in text.split("\n") if len(l.split()) > 6) or g.meta
    except Exception as e:
        return send(f"I couldn't open that link ({esc(e)}). It may need a login or block bots.")
    if not text:
        return send("That page didn't have readable text I could summarise.")
    ask = question or "Summarise this in 4 to 6 short bullets, then one line on why it matters."
    msgs = [{"role": "system", "content": SYSTEM},
            {"role": "user", "content": f"Title: {title}\n\nContent:\n{text[:5000]}\n\n{ask}"}]  # longer pages are slow on CPU
    stream_to_chat(llm_stream(msgs, num_predict=400, temperature=0.3), prefix=f"🔗 <b>{esc(title or 'Summary')}</b>\n\n")


def tg_file(file_id):
    f = tg("getFile", file_id=file_id)
    return http(f"{FILE_API}/{f['file_path']}", binary=True, timeout=60)


def photo(msg):
    if cannot("look at pictures"):
        return
    typing("upload_photo")
    best = max(msg["photo"], key=lambda p: p.get("file_size", 0) if p.get("width", 0) <= 1600 else 0)
    try:
        img = base64.b64encode(tg_file(best["file_id"])).decode()
    except Exception:
        return send("🖼 I couldn't download that picture. Try sending it again in a moment.")
    q = msg.get("caption") or ("Describe what's in this picture in a few sentences. If it's a receipt, bill, ticket or document, "
                               "list the key details (amounts, dates, names, times).")
    note = send("👀 Looking at your photo… (pictures take about 20 to 40 seconds)")
    msgs = [{"role": "system", "content": SYSTEM}, {"role": "user", "content": q}]
    out = ""
    for c in llm_stream(msgs, images=[img], num_predict=400, temperature=0.3):
        out += c
    edit(note, "🖼 " + md_to_html(out.strip() or "I couldn't make out the picture."))


def multipart(field, filename, data, ctype):
    boundary = uuid.uuid4().hex
    body = (f"--{boundary}\r\nContent-Disposition: form-data; name=\"{field}\"; filename=\"{filename}\"\r\n"
            f"Content-Type: {ctype}\r\n\r\n").encode() + data + f"\r\n--{boundary}--\r\n".encode()
    return body, f"multipart/form-data; boundary={boundary}"


def voice(msg):
    if cannot("understand voice notes", ("whisper",)):
        return
    typing("record_voice")
    v = msg.get("voice") or msg.get("audio")
    try:
        data = tg_file(v["file_id"])
    except Exception:
        return send("🎤 I couldn't download that voice note. Try sending it again in a moment.")
    body, ctype = multipart("audio_file", "voice.ogg", data, v.get("mime_type", "audio/ogg"))
    try:
        r = http(f"{WHISPER}/asr?output=json&task=transcribe&encode=true", body, timeout=300, headers={"Content-Type": ctype})
    except Exception as e:
        return send(f"🎤 I couldn't transcribe that ({esc(e)}). The voice app may still be starting.")
    text = (r.get("text") or "").strip()
    if not text:
        return send("🎤 I couldn't hear anything in that voice note.")
    send(f"🎤 <i>“{esc(text)}”</i>", silent=True)
    route(text)


def register(app):
    host.need(globals(), "FILE_API", "cannot", "SEARX", "SYSTEM", "TOPIC_WORDS", "UA", "WHISPER", "cricket_lines", "edit", "f1_lines", "jolpica", "llm_stream", "md_to_html", "route", "send", "strip_tags", "stream_to_chat", "tg", "typing", "weather_lines")
