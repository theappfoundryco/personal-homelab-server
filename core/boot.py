#!/usr/bin/env python3
"""Homelab assistant: Telegram bot + small API for the landing page.

- Long-polls Telegram (no public URL). Only the owner's chat id is answered.
- Common requests are handled instantly by a keyword router; anything else goes to the local LLM
  (Ollama) and streams into the chat as it is written.
- A scheduler sends reminders, the morning briefing (with a short server recap), the evening plan,
  Sunday report and F1/flight alerts (no cricket alerts). No live up/down alerts: problems are recapped in the briefing.
- Watchtower posts its nightly report to /watchtower, which becomes one tidy "apps updated" message.
- Server actions (restart an app, reboot) are requested by dropping a file in /data/requests;
  the host's homelab-bot-actions service carries them out. The bot has no Docker or host access.
"""
import base64, calendar, glob, hashlib, html, imaplib, email, email.header, email.utils, json, math, os, re, shutil, sys, threading, time, traceback, uuid
import xml.etree.ElementTree as ET
from collections import Counter
from datetime import date, datetime, timedelta, timezone
from html.parser import HTMLParser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.error import HTTPError
from urllib.parse import quote, urlencode, urlparse, parse_qs
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

from core import capabilities as _capabilities, config as _config, helpers as _helpers, http_api as _http_api, llm as _llm, store as _store
from core.telegram import client as _telegram
from core import app as _app, host as _host, registry as _registry, scheduler as _scheduler

CONFIG = _config.load()
from core import migrations as _migrations
try:
    _migrations.run_all(os.environ.get("HL_DATA", "/data"))  # a manual git pull still gets its data changes
except Exception as e:
    print(f"Data migration stopped: {e}", flush=True)
from core import settings as _settings, setup as _setup
SETTINGS = _settings.Settings(os.environ.get("HL_DATA", "/data"), CONFIG)
SETTINGS.apply(CONFIG)  # what was set in the dashboard sits on top of config.yaml
cfg, feature, clock_time = CONFIG.get, CONFIG.feature, _config.clock_time
_host.provide(cfg=cfg)


TOKEN, OWNER = _setup.telegram_login(os.environ.get("HL_DATA", "/data"))  # optional: with no token the dashboard runs and chat is off. The environment wins over what the wizard saved
MODEL = os.environ.get("BOT_MODEL") or cfg("models.chat", "qwen3.5:4b")
NAME = str(cfg("owner.name", "friend"))
SECRETS = "/secrets"
ICS_FILE, GMAIL_FILE = f"{SECRETS}/ical.secret.txt", f"{SECRETS}/gmail.secret.txt"
GMAIL_USER = os.environ.get("GMAIL_USER", "")
DAILY = "/srv/stats/daily.json"
DATA = os.environ.get("HL_DATA", "/data")
TZ = ZoneInfo(cfg("timezone", "UTC"))  # the one clock everything runs on, wherever you are
API = f"https://api.telegram.org/bot{TOKEN}"
FILE_API = f"https://api.telegram.org/file/bot{TOKEN}"
OLLAMA, PROM, N8N = _llm.base_url(cfg), "http://prometheus:9090", "http://n8n:5678"
SEARX, WHISPER, DOCKER = "http://searxng:8080", "http://whisper:9000", "http://docker-proxy:2375"
DASH = str(cfg("dashboard_url", "")).rstrip("/")  # full URL: Telegram rejects bare hostnames in buttons
UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_0) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126 Safari/537.36"

# Friendly names for the apps (containers) in the stack.
APPS = {"n8n": "Automations (n8n)", "ollama": "AI engine (Ollama)", "open-webui": "AI chat (Open WebUI)",
        "grafana": "Charts (Grafana)", "uptime-kuma": "Website monitor",
        "landing": "Home page", "homepage": "Full dashboard", "searxng": "Private search", "adguard": "Ad blocker (AdGuard)",
        "prometheus": "Metrics (Prometheus)", "cadvisor": "Container metrics", "node-exporter": "Server metrics",
        "dozzle": "Logs viewer", "watchtower": "Auto-updater", "whisper": "Voice to text", "docker-proxy": "Docker reader",
        "telegram-bot": "This bot"}
ALWAYS_ON = [a for a in APPS if a != "telegram-bot"]
app_name = lambda c: APPS.get(c, c)


# ================================================================ helpers
http = _helpers.http


TG = _telegram.Telegram(TOKEN, OWNER)


def tg(method, **params):
    return TG.call(method, **params)


esc, strip_tags, now = _helpers.esc, _helpers.strip_tags, _helpers.now


def send(text, buttons=None, keyboard=None, silent=False):
    return TG.send(text, buttons, keyboard, silent)


def edit(msg, text, buttons=None):
    return TG.edit(msg, text, buttons)


def typing(action="typing"):
    TG.typing(action)


cached = _helpers.cached
safe = _helpers.safe
_helpers.configure(TZ, on_error=lambda e: run_info("errors", f"{type(e).__name__}: {e}"[:200], add=True))  # inside a logged job, a swallowed error still shows in the run log


from core.runlog import RUN_LOG, _run, _runl, run_info, run_job, run_prune, run_purpose, run_since, run_view, run_write


B = lambda text, data: {"text": text, "callback_data": data}
U = lambda text, url: {"text": text, "url": url}

KEYBOARD = {"keyboard": [[{"text": "☀️ Briefing"}, {"text": "📅 My day"}],
                         [{"text": "📝 Notes"}, {"text": "⏰ Reminders"}],
                         [{"text": "🗞 News"}, {"text": "🏆 Sports"}],
                         [{"text": "🌦 Weather"}, {"text": "🖥 Server"}]],
            "resize_keyboard": True, "is_persistent": True, "input_field_placeholder": "Type anything, or send a voice note"}


# ================================================================ state (moved to core/state.py)
from core.state import BOOT_AT, STATE_FILE, _lock, claim, claimed_run, finish, load_state, once, save, state

write_json = _store.write_json


# ================================================================ calendar (moved to modules/calendar/)
from modules.calendar import day_events, event_line, events_for, has_calendar, ics_text


# ================================================================ location (moved to modules/location/)
from modules.location import HOME, geocode, location, refresh_location, shared_location


# ================================================================ weather, currency, world clock (moved to modules/)
from modules.weather import tomorrow_weather, weather, weather_data, weather_lines


from modules.currency import fx, travel_fx


# ================================================================ briefing (moved to modules/briefing/)
_host.provide(NAME=NAME)
from modules.briefing import BRIEF_NEWS, LAST_BRIEF, build_briefing, full_briefing, morning_briefing, scheduled_briefing, stored, warm_briefing


# ================================================================ server (moved to modules/server/)
from modules.server import TEMP, app_buttons, containers, daily, find_app, free_ai_memory, host_action, logs, one, restart_app, server, unload_ai


# ================================================================ planner (moved to modules/planner/)
_host.provide(DATA=DATA)
from modules.planner import DATE_WORDS, GOAL_ADD, achieve_goal, add_goal, add_note, add_reminder, capture_save, del_reminder, delete_goal, done_note, edit_goal, fire_reminders, goal_text, goals_view, manage_notes, manage_reminders, note_text, notes_view, past_drop, past_load, past_restore, past_view, pick, plan_reminders, quick_plan, reminders_view, save_reminders, snooze, undo_note, update_note


# ================================================================ ai (moved to modules/ai/)
from modules.ai import _ai, _tag, ai_keep, ai_load, ai_loaded, ai_status, ai_usage_view, ai_warm, big_call, count_tokens, llm_json, nice_when


# ================================================================ flights (moved to modules/flights/)
from modules.flights import FLIGHT, flight_text, flights


# ================================================================ day (moved to modules/day/)
from modules.day import evening, my_day, weekly


# ================================================================ world clock (moved to modules/clock/)
from modules.clock import CLOCKS, world_clock


# ================================================================ sports (moved to modules/sports/)
from modules.sports import f1_lines, cricket_lines, cricket_items, f1_when, jolpica, sports, INDIA


# ================================================================ journal priority and schedule times
_journal_idle = threading.Event()  # cleared while journal AI work runs (summaries, deep read, insights, weekly recap)
_journal_idle.set()
_journal_morning = {"day": None}  # the date whose morning journal run has finished


def journal_work(fn):
    """Runs journal AI work with priority: news digests queue until it's done."""
    _journal_idle.clear()
    try:
        safe(fn)
    finally:
        if not (_deep_busy.is_set() or _insights_busy.is_set() or _recap_busy.is_set()):
            _journal_idle.set()


NEWS_AT = [clock_time(t, (6, 30)) for t in (cfg("schedule.news_at", None) or ["6:30 AM"])]  # in your timezone, once a day, before the briefing
BRIEF_AT = clock_time(cfg("schedule.briefing", "7:00 AM"), (7, 0))
# Night jobs you chose in Settings: the journal summary (and two retries, 2 and 4 hours later), and Deep insights half an hour after it
JOURNAL_ON, INSIGHTS_ON = cfg("night.journal", True) is not False, cfg("night.insights", True) is not False
JOURNAL_AT = clock_time(cfg("night.journal_at", None) or "4:30 AM", (4, 30))
EVENING_AT = clock_time(cfg("schedule.evening_plan", "9:00 PM"), (21, 0))
EVENING_ON, WEEKLY_ON = cfg("schedule.evening_on", True) is not False, cfg("schedule.weekly_on", True) is not False  # each can be turned off on the Schedule page


# ================================================================ news (moved to modules/news/)
_host.provide(BRIEF_NEWS=BRIEF_NEWS, DATA=DATA, SEARX=SEARX, UA=UA)
from modules.news import DIGEST_FILE, FEEDS, NEWS_MODEL, STORY_FILE, TOPIC_GENERIC, TOPIC_NAMES, TOPIC_WORDS, _digest_lock, detect_topic, digests, feed_items, headlines_for, last_headlines, live_digest, news_rows, news_search, refresh_digests, stories, summarise_topic, topic_news


# ================================================================ gmail (moved to modules/gmail/)
from modules.gmail import gmail, gmail_cached


# ================================================================ chat (moved to core/chat.py)
from core import chat as _chat
from core.chat import REFUSAL, TAGS, chat, context, llm_stream, md_to_html, stream_to_chat


# ================================================================ search (moved to modules/search/)
from modules.search import photo, search, summarise_link, voice


# ================================================================ alerts (moved to modules/alerts/)
from modules.alerts import check_f1, check_flights, check_server, incident, updates_message


# ================================================================ timers (moved to core/jobs.py)
from core import jobs as _jobs
from core.jobs import ALIVE_FILE, downtime_note, extras, scheduler, write_extras
t12, t12_range = _helpers.t12, _helpers.t12_range


# ================================================================ gym (moved to modules/gym/)
_host.provide(DATA=DATA)
from modules.gym import gym, gym_today


# ================================================================ journal (moved to modules/journal/)
_host.provide(DATA=DATA, HOME=HOME, NAME=NAME, feature=feature)
from modules.journal import CLAUDE_KEY, JOURNAL_MODEL, LETTERS_FILE, RECAP_SHOW, RECAP_START, _deep_busy, _insights_busy, _recap_busy, check_journal, deep_api, deep_night, deep_view, insights_due, insights_run, jnow_view, journal, journal_api, journal_behind, journal_context, journal_day, journal_morning_run, journal_night, journal_rows, journal_save, journal_texts, journal_week_lines, recap_card, recap_due, suggested_tags


# ================================================================ health (moved to modules/health/)
from modules.health import BARE_DONE, bare_done, check_meds, check_sg, med_tick, nudged, sg, sg_api, sg_save, sg_view, typed_meds


# ================================================================ small API for the landing page
ROUTER = _http_api.Router(log=print)
CAPS = _capabilities.Capabilities()
def _ollama_check():
    ok, why = _llm.Ollama(OLLAMA).available()
    return ok, re.sub(r"\s*\([^)]*\)", "", why.replace(_llm.FIX, "")).strip()  # the fix is shown on its own line; no raw error codes


CAPS.register("ollama", "AI (Ollama)", _ollama_check, "Start Ollama, or turn the AI features off in config.yaml.",
              off=lambda: "No AI engine is set up yet. Add one in Settings, Apps, or point to another machine's Ollama." if OLLAMA == _llm.DEFAULT_URL and "ollama" not in _apps.chosen(DATA) else "")
CAPS.register("internet", "Internet", _capabilities.internet_check, "Check the network. News, weather and search need it.", ttl=60)
CAPS.register("calendar", "Calendar", lambda: (os.path.exists(ICS_FILE), "No calendar link yet."), "Add your calendar link in the setup wizard to see your day.",
              off=lambda: "No calendar added. Add one in the setup wizard to see your day.")
CAPS.register("telegram", "Telegram", lambda: (bool(TOKEN and OWNER), "No Telegram bot is set up, so there is no chat."), "Add the bot token and your chat id in the setup wizard.", ttl=300,
              off=lambda: "" if TOKEN else "Telegram is not connected. Connect it in the setup wizard to chat with the assistant.")
CAPS.register("whisper", "Voice to text (Whisper)", lambda: _capabilities.reachable(WHISPER), "Start the Whisper container, or leave voice notes off.", ttl=60,
              off=lambda: "" if "whisper" in _apps.chosen(DATA) else "Voice to text is not installed. Add it in Settings, Apps.")
CAPS.register("docker_reader", "Docker reader", lambda: _capabilities.reachable(f"{DOCKER}/_ping"), "Start the docker-proxy container to see and restart apps.", ttl=60)
from core import agent as _agent
from core import apps as _apps
CAPS.register("host_agent", "Host helper", lambda: (_agent.alive(DATA), "The host helper (restart and update) is not running."), "Install it with: homelab agent install", ttl=60,
              off=lambda: "" if os.path.exists(os.path.join(DATA, _agent.BEAT)) else "The host helper is not installed, so Restart, Update and Add ask you to run a command instead. Install it with: bin/homelab agent install")
CAPS.register("gmail", "Gmail", lambda: (os.path.exists(GMAIL_FILE), "No Gmail account yet."), "Add a Gmail app password in the setup wizard to see unread mail.",
              off=lambda: "Gmail is not connected. Add an app password in the setup wizard to see unread mail.")


# ================================================================ landing API (moved to core/landing_api.py and the modules)
from core import landing_api as _landing


class Api(_landing.Api):
    router = ROUTER


# ================================================================ intent understanding (moved to core/intent.py)
from core import intent as _intent
from core.intent import _clf, _index, CLF_SURE, EMBED_MODEL, EMBED_PREFIX, INTENT_CLF_FILE, INTENT_NAMES, LEARNED_FILE, NEWS_WORDS, QUESTION, ai_pick, build_index, classify, clf_rank, embed, is_question, learn, learned


# ================================================================ telegram handlers (moved to core/telegram/handlers.py)
from core.telegram import handlers as _handlers
from core.telegram.handlers import EXACT, FILLER, FRESH, URL, WRONG, dispatch, fresh_data, handle, news_request, on_callback, route, sports_request


# ================================================================ modules
MODULES_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(_config.__file__))), "modules")
_host.provide(**{n: globals()[n] for n in _chat.NEEDS})
_chat.bind()
SYSTEM = _chat.SYSTEM
_host.provide(OLLAMA=OLLAMA, module_examples=lambda: module_examples(), llm_json=llm_json, count_tokens=count_tokens, _lock=_lock, NAME=NAME)
_intent.bind()
_host.provide(**{n: globals()[n] for n in _jobs.NEEDS})
_jobs.bind()
_host.provide(doctor=lambda: doctor(), hardware_view=lambda: hardware_view(), SETTINGS=SETTINGS, modules_info=lambda: [MODULES[n] for n in ENABLED], CAPS=CAPS, CLOCKS=CLOCKS, HOME=HOME, extras=extras, ics_text=ics_text, events_for=events_for, weather_data=weather_data, cricket_items=cricket_items, feed_items=feed_items, run_view=run_view, SYSTEM=SYSTEM, context=context, llm_stream=llm_stream, TZ=TZ, feature=feature, cfg=cfg)
_landing.routes(ROUTER)
_host.provide(**{n: globals()[n] for n in _handlers.NEEDS})
_handlers.bind()
HELP = _handlers.HELP
_host.provide(llm_json=llm_json, nudged=nudged, edit=edit, U=U, nice_when=nice_when, has_calendar=has_calendar, CLAUDE_KEY=CLAUDE_KEY, SYSTEM=SYSTEM, count_tokens=count_tokens, cricket_lines=cricket_lines, f1_lines=f1_lines, llm_stream=llm_stream,
              run_info=run_info, run_job=run_job, run_purpose=run_purpose, stream_to_chat=stream_to_chat, typing=typing, send=send, B=B, location=location, geocode=geocode, HOME=HOME, TZ=TZ, FLIGHT=FLIGHT, ICS_FILE=ICS_FILE, t12_range=t12_range,
              NAME=NAME, _lock=_lock, day_events=day_events, extras=extras, save=save, state=state,
              CAPS=CAPS, cannot=_chat.cannot, DASH=DASH, OLLAMA=OLLAMA, OWNER=OWNER, _digest_lock=_digest_lock, _journal_morning=_journal_morning, _tag=_tag, ai_loaded=ai_loaded, big_call=big_call,
              claim=claim, claimed_run=claimed_run, gym=gym, journal_week_lines=journal_week_lines, tomorrow_weather=tomorrow_weather, events_for=events_for, journal_day=journal_day, FEEDS=FEEDS, event_line=event_line, feed_items=feed_items, flight_text=flight_text, headlines_for=headlines_for, last_headlines=last_headlines, live_digest=live_digest,
              news_rows=news_rows, t12=t12, travel_fx=travel_fx, weather_data=weather_data, INDIA=INDIA, TEMP=TEMP, containers=containers, cricket_items=cricket_items, daily=daily, f1_when=f1_when, flights=flights, once=once, one=one,
              FILE_API=FILE_API, SEARX=SEARX, TOPIC_WORDS=TOPIC_WORDS, UA=UA, WHISPER=WHISPER, jolpica=jolpica, md_to_html=md_to_html, route=route, strip_tags=strip_tags,
              weather_lines=weather_lines, GMAIL_FILE=GMAIL_FILE, GMAIL_USER=GMAIL_USER, ALWAYS_ON=ALWAYS_ON, APPS=APPS, DAILY=DAILY, DOCKER=DOCKER, PROM=PROM, _ai=_ai, ai_status=ai_status, app_name=app_name, EMBED_MODEL=EMBED_MODEL, JOURNAL_MODEL=JOURNAL_MODEL, MODEL=MODEL, NEWS_MODEL=NEWS_MODEL, _run=_run, run_write=run_write, journal_work=journal_work, tg=tg, write_json=write_json)
APP = _app.App(CONFIG, ROUTER, _scheduler.Scheduler(str(TZ)), CAPS, _store.Store(DATA), _llm.Ollama(OLLAMA), TG)
MODULES = _registry.discover(MODULES_DIR)
ENABLED, MODULE_NOTES = _registry.plan(MODULES, cfg("modules", None))
STARTED = [_n for _n in ENABLED if _registry.start(MODULES[_n], APP)]
from core import doctor as _doctor
from core import hardware as _hardware
_hw = {}


def hardware_view():
    """The machine as probed once at first use (it does not change while running), with the profile and suggestions for it."""
    if not _hw:
        _hw.update(_hardware.view(DATA if os.path.isdir(DATA) else None, data_dir=DATA))
    return dict(_hw)


doctor = lambda: _doctor.report(CAPS, MODULES, ENABLED, STARTED, MODULE_NOTES, CONFIG, machine=hardware_view())
def _module_rows():
    return [{"name": m.name, "title": m.title, "description": m.description, "default": m.default, "requires": list(m.requires),
             "why_off": MODULE_NOTES.get(m.name, ""), "unavailable": _registry.this_platform() not in m.platforms} for m in MODULES.values() if m.name != "_template"]


_settings.routes(ROUTER, SETTINGS, _module_rows)
from core import schedule as _schedule
_schedule.routes(ROUTER, SETTINGS, lambda: CAPS.ok("host_agent"), lambda: CAPS.ok("ollama"))
SETUP = _setup.Setup(DATA)
_setup.routes(ROUTER, SETUP, SETTINGS, hardware_view, _module_rows, lambda: TG.enabled, lambda: [c["name"] for c in CAPS.all() if not c["ok"]], lambda: OLLAMA,
               add_app=lambda a: __import__("modules.server", fromlist=["host_action"]).host_action("add", a),
               host_do=lambda act, name: __import__("modules.server", fromlist=["host_action"]).host_action(act, name))


def module_examples():
    """Intent examples from every module that is on."""
    import importlib
    out = {}
    for n in ENABLED:
        try:
            out.update(importlib.import_module(f"modules.{n}.intents").EXAMPLES)
        except ImportError:
            pass
    return out


def main():
    os.makedirs(DATA, exist_ok=True)
    tg("setMyCommands", commands=[
        {"command": "help", "description": "What I can do"},
        {"command": "brief", "description": "Briefing + news, fresh right now"},
        {"command": "morning", "description": "This morning's 7 AM briefing and news"},
        {"command": "news", "description": "Latest headlines"},
        {"command": "cal", "description": "My day"},
        {"command": "tomorrow", "description": "Tomorrow: plans, weather, alarm"},
        {"command": "clock", "description": "World clock"},
        {"command": "notes", "description": "My notes"},
        {"command": "reminders", "description": "My reminders"},
        {"command": "weather", "description": "Weather"},
        {"command": "stats", "description": "Server health"},
        {"command": "suggestedtags", "description": "Journal tags the AI suggests adding"},
        {"command": "reset", "description": "Forget our chat"},
    ])
    threading.Thread(target=lambda: safe(build_index), daemon=True).start()  # warm the intent index
    refresh_location()
    warm_briefing()
    digests.update(safe(lambda: json.load(open(DIGEST_FILE)), {}))
    stories.update(safe(lambda: json.load(open(STORY_FILE)), {}))
    behind = safe(journal_behind, [])
    if behind:
        _journal_idle.clear()  # held before the scheduler's first news run can start
        threading.Thread(target=lambda: journal_work(lambda: run_job("Journal catch-up after restart", lambda: (run_info("behind", behind), journal_morning_run())[1])), daemon=True).start()
    down = safe(downtime_note, None)
    safe(lambda: run_write({"t": "boot", "at": round(time.time(), 1), "down_from": down and round(down, 1)}))  # the Night log marks jobs a restart cut short
    threading.Thread(target=scheduler, daemon=True).start()
    if not state.get("goals_v1"):  # 2026-10-27: his countries list is a life goal, not a note
        with _lock:
            for n in [n for n in state["notes"] if n["text"].lower().startswith("order of countries")]:
                state["notes"].remove(n)
                state.setdefault("goals", []).append({"id": n["id"], "text": n["text"], "added": n.get("added", time.time())})
            state["goals_v1"] = True
            save()
    threading.Thread(target=ThreadingHTTPServer(("0.0.0.0", 8080), Api).serve_forever, daemon=True).start()
    print("bot running, model", MODEL)
    offset = None
    if not TG.enabled:
        print("telegram is off (no TG_TOKEN or TG_CHAT): serving the dashboard only")
        threading.Event().wait()
    while True:
        try:
            ups = http(f"{API}/getUpdates?timeout=50" + (f"&offset={offset}" if offset else ""), timeout=70)["result"]
        except Exception as e:
            print("poll error:", e)
            time.sleep(5)
            continue
        for u in ups:
            offset = u["update_id"] + 1
            threading.Thread(target=handle, args=(u,), daemon=True).start()


if __name__ == "__main__":
    main()
