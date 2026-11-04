"""Where you are: a shared pin, the server's internet location, or a 'Name in City' calendar event."""
import re, time
from urllib.parse import urlencode

from core import host
from core.helpers import cached, esc, http, now, safe

host.need(globals(), "cfg")

# ================================================================ location (follows "{name} in X" calendar events)
@cached(86400)
def geocode(city):
    r = http("https://geocoding-api.open-meteo.com/v1/search?" + urlencode({"name": city, "count": 1}), timeout=15)
    g = (r.get("results") or [None])[0]
    if not g:
        return None
    return {"city": g["name"], "country": g.get("country", ""), "lat": g["latitude"], "lon": g["longitude"], "tz": g.get("timezone", "Asia/Singapore")}


HOME = {"city": "London", "country": "United Kingdom", "lat": 51.51, "lon": -0.13, "tz": "Europe/London", **(cfg("home", {}) or {})}


@cached(1800)
def ip_location():
    """Where the server's internet connection is (the server lives with him). ~100 ms, cached 30 min."""
    try:
        r = http("http://ip-api.com/json/?fields=status,city,country,lat,lon,timezone", timeout=5)
        if r.get("status") == "success":
            return {"city": r["city"], "country": r["country"], "lat": r["lat"], "lon": r["lon"], "tz": r["timezone"], "source": "internet"}
    except Exception:
        pass
    r = http("https://ipwho.is/", timeout=5)
    return {"city": r["city"], "country": r["country"], "lat": r["latitude"], "lon": r["longitude"], "tz": r["timezone"]["id"], "source": "internet"}


def location(d=None):
    """Today: a pin he shared (last 24 h), else where the server's internet is. Future days: his calendar's "{name} in X"."""
    today = now().date()
    d = d or today
    pin = state.get("here")
    if d == today:
        if pin and time.time() - pin["ts"] < 86400:
            return pin["loc"]
        if (here := safe(ip_location)):
            return here
    for e in day_events(d):
        m = re.match(rf"^(?:{NAME}\s+)?(?:is\s+)?in\s+([A-Za-z .'-]+?)\s*(?:\(.*)?$", e["title"], re.I)
        if e["all_day"] and m:
            g = safe(lambda: geocode(m[1].strip()))
            if g:
                return {**g, "source": "calendar"}
    return safe(ip_location) or state.get("last_loc") or HOME


def refresh_location():
    """Tracks where he is (for weather). The clock stays on the configured timezone."""
    loc = safe(location)
    if not loc:
        return
    if loc != state.get("last_loc"):
        with _lock:
            state["last_loc"] = loc; save()


@cached(86400)
def reverse_geocode(lat, lon):
    r = http("https://nominatim.openstreetmap.org/reverse?" + urlencode({"lat": lat, "lon": lon, "format": "json", "zoom": 10}),
             timeout=8, headers={"User-Agent": "homelab-bot"})
    a = r.get("address", {})
    return a.get("city") or a.get("town") or a.get("county") or a.get("state") or "your location", a.get("country", "")


def shared_location(m):
    """He sent a location pin: use it for the next 24 hours."""
    lat, lon = m["location"]["latitude"], m["location"]["longitude"]
    city, country = safe(lambda: reverse_geocode(round(lat, 2), round(lon, 2)), ("your location", ""))
    w = safe(lambda: http(f"https://api.open-meteo.com/v1/forecast?latitude={lat}&longitude={lon}&timezone=auto&forecast_days=1", timeout=8), {})
    loc = {"city": city, "country": country, "lat": lat, "lon": lon, "tz": w.get("timezone") or TZ.key, "source": "shared"}
    with _lock:
        state["here"] = {"loc": loc, "ts": time.time()}; save()
    refresh_location()
    extras.clear()
    send(f"📍 Got it, you're in <b>{esc(city)}</b>. I'll use it for weather and your briefing today.",
         [[B("☀️ Briefing", "full"), B("🌦 Weather", "wx")]])


def register(app):
    host.need(globals(), "B", "NAME", "TZ", "_lock", "day_events", "extras", "save", "send", "state")
