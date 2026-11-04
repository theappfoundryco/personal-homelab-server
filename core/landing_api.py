"""The dashboard's small API: what the app itself answers (config, capabilities, extras, run log, ask). Each module registers its own routes.
Anything unknown gets the same plain 404 or 400 as before. Things that live elsewhere come through core.host."""
import threading
from urllib.parse import urlparse

from core import host, http_api
from core.helpers import safe

NEEDS = ("CAPS", "doctor", "hardware_view", "CLOCKS", "HOME", "SYSTEM", "TZ", "cfg", "context", "events_for", "extras", "feature", "ics_text", "llm_stream", "modules_info", "run_view", "SETTINGS")


def routes(router):
    host.need(globals(), *NEEDS)

    @router.get("/capabilities")
    def capabilities_view(req):
        """What works right now, and the fix for what does not (the dashboard's Settings and doctor views read this)."""
        return {"capabilities": CAPS.all()}

    @router.get("/config")
    def config_view(req):  # what the dashboard needs from config.yaml: nothing secret
        out = {"name": cfg("owner.name", ""), "timezone": str(TZ), "home_city": HOME["city"], "home_lat": HOME["lat"], "home_lon": HOME["lon"],
                "clocks": [{"label": l, "tz": z} for _, l, z in CLOCKS],
                "features": {"therapy_recap": feature("therapy_recap", False)},
                "support": {"therapist": cfg("support.therapist", ""), "helpline_name": cfg("support.helpline_name", ""),
                            "helpline_tel": cfg("support.helpline_tel", "")}}
        layout = {k: v for k, v in (SETTINGS.merged().get("dashboard") or {}).items() if v}  # read live, so a change shows on the next load; only when someone changed it, so a fresh install answers as before
        return {**out, "layout": layout} if layout else out

    @router.get("/doctor")
    def doctor_view(req):
        return doctor()

    @router.get("/hardware")
    def hardware_route(req):
        return hardware_view()

    @router.get("/modules")
    def modules_view(req):
        """The modules that are on, with what each adds to the dashboard (its tab, home cards and the files of its views)."""
        out = []
        for m in modules_info():
            d = m.dashboard or {}
            tab = d.get("tab")
            tab = {"id": tab} if isinstance(tab, str) else tab
            out.append({"name": m.name, "title": m.title, "tab": tab, "home_cards": d.get("home_cards") or [], "web": d.get("web") or [], "degraded": CAPS.degraded(m.optional)})
        return {"modules": out}

    @router.get("/extras")
    def extras_view(req):
        if "fresh=1" in req._h.path:  # the page's refresh button: skip the calendar caches and read the feed again
            ics_text.clear(); events_for.clear(); extras.clear()
        return safe(extras, {})

    @router.get("/runs")
    def runs_view(req):
        return safe(run_view, {"jobs": [], "ai": []})

    @router.post("/ask")
    def ask(req):
        b = req.json()
        if not b.get("q", "").strip():
            return {"error": "bad request"}, 400
        h = req._h
        h.send_response(200)
        h.send_header("Content-Type", "text/plain; charset=utf-8")
        h.send_header("Cache-Control", "no-store")
        h.send_header("X-Accel-Buffering", "no")
        h.end_headers()
        msgs = [{"role": "system", "content": SYSTEM + "\n\n" + safe(context, "")}, {"role": "user", "content": b["q"][:2000]}]
        try:
            for c in llm_stream(msgs, num_predict=400):
                h.wfile.write(c.encode()); h.wfile.flush()
        except Exception as e:
            h.wfile.write(f"\n(Sorry, the AI isn't available: {e})".encode())
        return http_api.HANDLED


class Api(http_api.Handler):
    """Routes answer first; this is only what is left over."""

    def do_GET(self):
        self.dispatch("GET") or self.reply({"error": "not found"}, 404)

    def do_POST(self):
        self.dispatch("POST") or self.reply({"error": "bad request"}, 400)
