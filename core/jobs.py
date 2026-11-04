"""Everything that runs on a timer: the scheduler loop, the extras file the landing page reads, and the note after downtime.
Things that live in the app or in modules are reached through core.host, bound once by bind()."""
import json, os, threading, time, traceback
from datetime import datetime, timedelta

from core import host
from core.helpers import cached, now, safe, t12

NEEDS = ("TZ", "send", "NEWS_AT", "BRIEF_AT", "JOURNAL_AT", "JOURNAL_ON", "INSIGHTS_ON", "EVENING_ON", "WEEKLY_ON", "EVENING_AT", "RECAP_START", "RECAP_SHOW", "feature", "state", "once", "claim", "claimed_run", "write_json", "location", "flights", "travel_fx", "nice_when", "day_events", "gmail_cached", "fire_reminders", "check_journal", "check_server", "check_sg", "check_meds", "refresh_location", "warm_briefing", "ai_warm", "refresh_digests", "run_job", "scheduled_briefing", "evening", "journal_work", "journal_morning_run", "insights_due", "recap_due", "weekly", "run_prune", "check_f1", "check_flights")

DATA = os.environ.get("HL_DATA", "/data")
ALIVE_FILE = f"{DATA}/alive"  # the time, every minute: after a restart it says when the bot went down


def bind():
    """Called by the app once everything in NEEDS has been provided."""
    host.need(globals(), *NEEDS)


def downtime_note():
    """On start: one Telegram line if the bot was down more than 3 minutes. Journal work is never named here."""
    last = safe(lambda: float(open(ALIVE_FILE).read().strip()), None)
    if not last or time.time() - last < 180:
        return last
    booted = time.time() - safe(lambda: float(open("/proc/uptime").read().split()[0]), 0)
    back = datetime.fromtimestamp(max(booted, last) if booted > last else time.time(), TZ)
    gone = datetime.fromtimestamp(last, TZ)
    when = lambda d: t12(d) if d.date() == back.date() else f"{d:%-d %b}, {t12(d)}"
    mins = round((back - gone).total_seconds() / 60)
    what = "The server was off" if booted > last else "The bot was down"
    took = f"{mins // 60} h {mins % 60} min" if mins >= 60 else f"{mins} min"
    threading.Thread(target=lambda: (time.sleep(30), safe(lambda: send(
        f"⚡ <b>{what}</b> from {when(gone)} to {t12(back)} ({took}). Anything it missed is running now.", silent=True))), daemon=True).start()
    return last


@cached(60)
def extras():
    loc = location()
    today = now().date()
    fl = flights(1)
    return {
        "generated": int(time.time()),
        "location": loc,
        "fx": (lambda r: {**{f"{c}_INR": v for c, v in r}, "rates": r} if r else None)(safe(lambda: travel_fx(loc), [])),
        "notes": [n["text"] for n in state["notes"]],
        "reminders_today": [{"time": f"{datetime.fromtimestamp(r['due'], TZ):%-I:%M %p}", "text": r["text"]}
                            for r in sorted(state["reminders"], key=lambda r: r["due"]) if datetime.fromtimestamp(r["due"], TZ).date() == today],
        "flights": [{"title": f["title"], "when": nice_when(f["start"]), "leave_by": f"{f['leave_by']:%-I:%M %p}"} for f in fl],
        "agenda": {"today": [{"when": e["when"], "title": e["title"], "loc": e["loc"]} for e in day_events(today)],
                   "tomorrow": [{"when": e["when"], "title": e["title"], "loc": e["loc"]} for e in day_events(today + timedelta(1))],
                   "tomorrow_label": f"{today + timedelta(1):%a %d %b}"},
        "gmail": safe(gmail_cached),
    }


def write_extras():
    try:
        extras.clear()
        tmp = f"{DATA}/extras.json.tmp"
        json.dump(extras(), open(tmp, "w"), indent=1, default=str)
        os.chmod(tmp, 0o644)
        os.replace(tmp, f"{DATA}/extras.json")
    except Exception:
        traceback.print_exc()


def scheduler():
    last = {}
    def every(key, seconds):
        if time.time() - last.get(key, 0) >= seconds:
            last[key] = time.time()
            return True
        return False
    while True:
        try:
            t = now()
            fire_reminders()
            if every("journal", 30): check_journal()
            if every("server", 60): check_server()
            if every("sg", 300): check_sg()
            if every("meds", 20): check_meds()
            if every("location", 600): refresh_location()
            if every("extras", 600): write_extras()
            if every("alive", 60): safe(lambda: write_json(ALIVE_FILE, time.time()))
            if every("warm", 540): warm_briefing()
            if every("aiwarm", 60): threading.Thread(target=lambda: safe(ai_warm), daemon=True).start()  # also loads them at startup
            # news once a day
            # each runs from its time until done; after a power cut only the latest missed news run catches up
            slot = max((h for h, m in NEWS_AT if (t.hour, t.minute) >= (h, m)), default=None)
            if slot is not None and claim(k := f"news:{t:%Y%m%d}{slot:02d}"):
                threading.Thread(target=lambda k=k, both=slot != 6: claimed_run(k, lambda: refresh_digests(wait=True)), daemon=True).start()
            if BRIEF_AT[0] <= t.hour < 12 and claim(k := f"brief:{t:%Y%m%d}"):
                claimed_run(k, lambda late=t.hour * 60 + t.minute >= BRIEF_AT[0] * 60 + BRIEF_AT[1] + 15: run_job("Morning brief", lambda: scheduled_briefing(late), f"{BRIEF_AT[0]:02d}:{BRIEF_AT[1]:02d}"))
            if every("f1", 600): check_f1()
            if every("flights", 300): check_flights()
            if EVENING_ON and (t.hour, t.minute) >= EVENING_AT and claim(k := f"evening:{t:%Y%m%d}"): claimed_run(k, lambda: run_job("Evening check-in", lambda: evening(scheduled=True), f"{EVENING_AT[0]:02d}:{EVENING_AT[1]:02d}"))
            mt, ja = t.hour * 60 + t.minute, JOURNAL_AT[0] * 60 + JOURNAL_AT[1]
            for s in (ja, ja + 120, ja + 240):  # the summary, then two retries that only do something if it did not finish
                s %= 1440
                if JOURNAL_ON and s <= mt < s + 10 and once(f"jnight:{t:%Y%m%d}{s}"): threading.Thread(target=lambda s=s: journal_work(lambda: run_job("Journal morning", journal_morning_run, f"{s // 60:02d}:{s % 60:02d}")), daemon=True).start()
            if INSIGHTS_ON and JOURNAL_ON and mt >= (ja + 30) % 1440 and claim(k := f"insights:{t:%Y%m%d}"): threading.Thread(target=lambda k=k, s=(ja + 30) % 1440: claimed_run(k, lambda: journal_work(lambda: run_job("Deep insights", insights_due, f"{s // 60:02d}:{s % 60:02d}"))), daemon=True).start()
            if feature("therapy_recap", False) and t.weekday() == 2 and RECAP_START <= t.hour < RECAP_SHOW and every("recap", 600): threading.Thread(target=lambda: journal_work(lambda: run_job("Weekly summary", recap_due, "every 10 min")), daemon=True).start()
            if WEEKLY_ON and t.weekday() == 6 and t.hour >= 10 and claim(k := f"weekly:{t:%Y%m%d}"): claimed_run(k, lambda: run_job("Sunday report", weekly, "10:00"))
            if t.hour == 3 and once(f"runprune:{t:%Y%m%d}"): safe(run_prune)
        except Exception:
            traceback.print_exc()
        time.sleep(20)
