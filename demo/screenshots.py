"""Records the README screenshots from the fake demo data (no network, a frozen clock).
  pip install playwright pyyaml && playwright install chromium
  python3 demo/screenshots.py            writes docs/screenshots/*.png
Review the pictures before you commit them: they must show demo data only."""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "tests", "e2e"))
sys.path.insert(0, os.path.join(ROOT, "tests"))
import server  # noqa: E402
from playwright.sync_api import sync_playwright  # noqa: E402

import json  # noqa: E402

OUT = os.environ.get("SHOTS_OUT") or os.path.join(ROOT, "docs", "screenshots")
VIEWS = [("home", "home"), ("journal", "journal"), ("gym", "gym"), ("sg", "health")]
SIZES = {"phone": ({"width": 390, "height": 844}, 2)}
HEALTHY = ["ollama", "internet", "calendar", "gmail", "docker", "telegram", "whisper"]


def forecast():
    """A made-up, mild ten days for the weather card (the real one comes from the internet, which the demo does not use)."""
    days = [f"2026-11-{d:02d}" for d in range(3, 13)]
    hours = [f"{d}T{h:02d}:00" for d in days for h in range(24)]
    return {
        "current": {"temperature_2m": 19.4, "apparent_temperature": 18.6, "relative_humidity_2m": 58, "dew_point_2m": 11.0, "weather_code": 2, "is_day": 1,
                    "wind_speed_10m": 9.0, "wind_direction_10m": 240, "wind_gusts_10m": 17.0, "pressure_msl": 1016, "visibility": 24000, "uv_index": 3.2, "precipitation": 0.0},
        "hourly": {"time": hours, "temperature_2m": [15 + (h % 24) / 3 for h in range(len(hours))], "weather_code": [2] * len(hours),
                   "precipitation_probability": [10] * len(hours), "is_day": [1 if 7 <= h % 24 < 18 else 0 for h in range(len(hours))]},
        "daily": {"time": days, "weather_code": [2, 3, 61, 2, 1, 0, 2, 3, 2, 1], "temperature_2m_max": [21, 20, 17, 19, 22, 23, 21, 20, 19, 22],
                  "temperature_2m_min": [13, 12, 11, 11, 13, 14, 13, 12, 12, 13], "precipitation_probability_max": [10, 20, 70, 15, 5, 0, 10, 25, 20, 5],
                  "precipitation_sum": [0, 0.2, 4.1, 0, 0, 0, 0, 0.3, 0, 0], "sunrise": [f"{d}T06:41" for d in days], "sunset": [f"{d}T17:52" for d in days],
                  "uv_index_max": [3.2, 3.0, 2.0, 3.1, 3.4, 3.5, 3.2, 3.0, 3.1, 3.4]}}


def main():
    os.makedirs(OUT, exist_ok=True)
    srv, url = server.start()
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        for size, (viewport, scale) in SIZES.items():
            ctx = browser.new_context(viewport=viewport, device_scale_factor=scale, reduced_motion="reduce", timezone_id="UTC", locale="en-US", color_scheme="dark")
            pg = ctx.new_page()
            pg.clock.set_fixed_time("2026-11-03T10:00:00Z")  # the same moment the demo API thinks it is
            pg.route("**/*", lambda r: r.continue_() if r.request.url.startswith(url) else r.abort())  # fonts, maps and the internet stay out
            pg.route("https://api.open-meteo.com/**", lambda r: r.fulfill(status=200, content_type="application/json", body=json.dumps(forecast())))
            pg.route("https://air-quality-api.open-meteo.com/**", lambda r: r.fulfill(status=200, content_type="application/json", body=json.dumps({"current": {"us_aqi": 32, "pm2_5": 7.0}})))
            pg.route("**/api/bot/capabilities", lambda r: r.fulfill(status=200, content_type="application/json", body=json.dumps({"capabilities": [{"name": n, "title": n.title(), "ok": True} for n in HEALTHY]})))
            pg.route("**/api/bot/server/status", lambda r: r.fulfill(status=200, content_type="application/json", body=json.dumps(
                {"monitoring": True, "apps": [{"id": a, "name": a, "state": "running"} for a in ("landing", "telegram-bot", "ollama", "open-webui", "grafana")]})))
            pg.goto(url + "/")
            pg.wait_for_load_state("networkidle")
            for tab, name in VIEWS:
                pg.click(f'.tab[data-tab="{tab}"]')
                pg.wait_for_load_state("networkidle")
                pg.wait_for_timeout(400)
                pg.evaluate("window.scrollTo(0, 0)")
                pg.set_viewport_size({"width": viewport["width"], "height": pg.evaluate("document.documentElement.scrollHeight")})  # the whole page, so no card is cut off behind the bottom menu
                pg.wait_for_timeout(300)
                pg.screenshot(path=os.path.join(OUT, f"{name}-{size}.png"))
                pg.set_viewport_size(viewport)
                print("wrote", f"{name}-{size}.png")
            ctx.close()
        browser.close()
    srv.shutdown()


if __name__ == "__main__":
    main()
