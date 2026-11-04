"""Weather now and tomorrow, for home or any city you name."""
import re
from datetime import datetime, timedelta
from urllib.parse import urlencode
from zoneinfo import ZoneInfo

from core import host
from core.helpers import cached, esc, http, now, safe


# ================================================================ weather
WX = {0: "☀️ Clear", 1: "🌤 Mostly clear", 2: "⛅ Partly cloudy", 3: "☁️ Overcast", 45: "🌫 Fog", 48: "🌫 Fog",
      51: "🌦 Light drizzle", 53: "🌦 Drizzle", 55: "🌧 Heavy drizzle", 61: "🌦 Light rain", 63: "🌧 Rain", 65: "🌧 Heavy rain",
      71: "🌨 Light snow", 73: "🌨 Snow", 75: "🌨 Heavy snow", 80: "🌦 Light showers", 81: "🌧 Showers", 82: "⛈ Heavy showers",
      95: "⛈ Thunderstorm", 96: "⛈ Thunderstorm", 99: "⛈ Thunderstorm"}


@cached(600)
def weather_data(lat, lon):
    q = urlencode({"latitude": lat, "longitude": lon, "timezone": "auto", "forecast_days": 3,
                   "current": "temperature_2m,apparent_temperature,weather_code,relative_humidity_2m",
                   "daily": "weather_code,temperature_2m_max,temperature_2m_min,precipitation_probability_max,uv_index_max",
                   "hourly": "precipitation_probability"})
    return http(f"https://api.open-meteo.com/v1/forecast?{q}", timeout=15)


def wx_text(code):
    return WX.get(code, "🌡 Mixed").split(" ", 1)


def weather_lines(loc=None):
    loc = loc or location()
    w = weather_data(loc["lat"], loc["lon"])
    c, d, h = w["current"], w["daily"], w["hourly"]
    local_hour = datetime.now(ZoneInfo(w.get("timezone", "UTC"))).hour
    rain = [f"{(i % 24) % 12 or 12} {'AM' if i % 24 < 12 else 'PM'}" for i in range(local_hour + 1, min(local_hour + 13, len(h["precipitation_probability"])))
            if (h["precipitation_probability"][i] or 0) >= 60]
    icon, text = wx_text(c["weather_code"])
    t_icon, t_text = wx_text(d["weather_code"][1])
    out = [f"{icon} <b>{c['temperature_2m']:.0f}°C</b> and {text.lower()} • feels {c['apparent_temperature']:.0f}°",
           f"Today {d['temperature_2m_min'][0]:.0f}° to {d['temperature_2m_max'][0]:.0f}° • {d['precipitation_probability_max'][0]}% chance of rain • UV {d['uv_index_max'][0]:.0f}",
           f"Tomorrow {t_icon} {t_text.lower()}, {d['temperature_2m_min'][1]:.0f}° to {d['temperature_2m_max'][1]:.0f}° • {d['precipitation_probability_max'][1]}% rain"]
    out.append(("☔ Take an umbrella. Rain likely around " + ", ".join(rain[:3]) + ".") if rain else "🙂 No heavy rain expected in the next 12 hours.")
    return out


def weather(text=""):
    m = re.search(r"\b(?:in|at|for)\s+([A-Za-z][A-Za-z .'-]{2,40}?)(?:\s+(?:today|tomorrow|now|this week|right now))?\s*\??$", text, re.I)
    city = m[1].strip() if m else ""
    loc = safe(lambda: geocode(city)) if city and city.lower() not in ("the morning", "the evening", "the afternoon") else None
    loc = loc or location()
    try:
        send(f"🌦 <b>Weather in {esc(loc['city'])}</b>\n" + "\n".join(weather_lines(loc)))
    except Exception as e:
        send(f"Weather isn't available right now ({esc(e)}).")


def tomorrow_weather():
    d = now().date() + timedelta(1)
    loc = location(d)
    w = weather_data(loc["lat"], loc["lon"])["daily"]
    icon, text = wx_text(w["weather_code"][1])
    return loc, f"{icon} {text.lower()}, {w['temperature_2m_min'][1]:.0f}° to {w['temperature_2m_max'][1]:.0f}°, {w['precipitation_probability_max'][1]}% rain"


def register(app):
    host.need(globals(), "geocode", "location", "send")
