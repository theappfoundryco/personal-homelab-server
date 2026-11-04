"""Flights found in your calendar, with when to leave for the airport."""
import re
from datetime import timedelta

from core import host
from core.helpers import cached, esc, http, now, safe

# ================================================================ flights (from the calendar)
FLIGHT = re.compile(r"\bflight\b|✈|\bdeparts?\b|\b(?:[A-Z]{2}|[A-Z]\d|\d[A-Z])\s?\d{2,4}\b")


def flights(days=2):
    out, seen = [], set()
    if not has_calendar():
        return out
    for i in range(days + 1):
        for e in day_events(now().date() + timedelta(i)):
            if e["start"] and FLIGHT.search(e["title"]) and e["start"] not in seen:
                seen.add(e["start"])
                code = (re.search(r"\b((?:[A-Z]{2}|[A-Z]\d|\d[A-Z])\s?\d{2,4})\b", e["title"]) or [None, ""])[1]
                leave = e["start"] - timedelta(hours=3, minutes=15)  # international: be at the airport ~2.5h early
                out.append({**e, "code": code, "leave_by": leave, "checkin": e["start"] - timedelta(hours=24)})
    return out


def flight_text(f):
    return (f"✈️ <b>{esc(f['title'])}</b>\n"
            f"Departs {nice_when(f['start'])}{' from ' + esc(f['loc']) if f['loc'] else ''}\n"
            f"🚕 Leave home by <b>{f['leave_by']:%-I:%M %p}</b> (3h15 before, for an international flight)")


def register(app):
    host.need(globals(), "day_events", "has_calendar", "nice_when")
