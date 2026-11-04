"""World clock for the cities in config.yaml."""
import re
from datetime import datetime, timedelta
from urllib.parse import urlencode
from zoneinfo import ZoneInfo

from core import host
from core.helpers import cached, esc, http, now, safe

host.need(globals(), "cfg")

# ================================================================ world clock
# Empty until you add cities (from Home, or world_clock in config.yaml). Changed in place, so everything holding it sees new cities at once.
CLOCKS = [(c.get("flag", "🕰"), c["label"], c["tz"]) for c in (cfg("world_clock", None) or []) if c.get("label") and c.get("tz")]


def offset_text(minutes):
    if minutes == 0:
        return "same time"
    h, m = divmod(abs(minutes), 60)
    return f"{'+' if minutes > 0 else '-'}{h}h" + (f"{m:02d}" if m else "")


def world_clock():
    here = now()
    ind = datetime.now(TZ)
    lines = [f"🕰 <b>World clock</b>", f"<i>You: {here:%-I:%M %p}, {here:%a %d %b} • {esc(location()['city'])}</i>", f"<i>Differences are from {esc(HOME['city'])} time.</i>", ""]
    if not CLOCKS:
        lines.append("No cities yet. Add them on the dashboard's Home, under World clock.")
    for flag, city, zone in CLOCKS:
        t = datetime.now(ZoneInfo(zone))
        diff = int((t.utcoffset() - ind.utcoffset()).total_seconds() // 60)  # compared with home
        day = "" if t.date() == ind.date() else " • 🟢 +1 day" if t.date() > ind.date() else " • 🔴 −1 day"
        night = " 🌙" if t.hour < 6 or t.hour >= 22 else ""
        lines.append(f"{flag} <b>{t:%-I:%M %p}</b>  {city}  <i>{offset_text(diff)}{day}</i>{night}")
    send("\n".join(lines), [[B("🔄 Refresh", "clock")]])


def register(app):
    host.need(globals(), "B", "HOME", "SETTINGS", "TZ", "location", "send")

    @app.router.post("/clocks")
    def clocks_set(req):
        """The whole list of cities, in order: [{label, tz}]. Saved as a setting and live at once (no restart)."""
        from core.settings import guard_request
        if bad := guard_request(SETTINGS, req):
            return bad
        items = (req.json() or {}).get("clocks")
        if not isinstance(items, list) or len(items) > 12:
            return {"ok": False, "error": "Send up to 12 cities."}, 400
        clean = [{"label": str(c.get("label", "")).strip()[:30], "tz": str(c.get("tz", "")).strip()} for c in items if isinstance(c, dict)]
        ok, problems = SETTINGS.set({"world_clock": clean})
        if not ok:
            return {"ok": False, "error": " ".join(problems)}, 400
        CLOCKS[:] = [("🕰", c["label"], c["tz"]) for c in clean if c["label"] and c["tz"]]
        return {"ok": True, "clocks": [{"label": l, "tz": z} for _, l, z in CLOCKS]}
