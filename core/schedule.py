"""The Schedule page and the Night log's plan: every job that runs on a timer, whether it is on, and when.
Each one can be turned off. Times are in your time zone. The backup and the git copy are run by the host helper."""
from core import config
from core.settings import guard_request

DAYS = ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday")


def _t12(hm):
    h, m = hm
    return f"{h % 12 or 12}:{m:02d} {'AM' if h < 12 else 'PM'}"


def plan(eff, helper_ok=True, ai_ok=True):
    """[{id, title, what, on, at, at24, every, needs, fields}] from the effective settings. at is "4:30 AM" style; every says how often."""
    g = lambda path, d=None: _dig(eff, path, d)
    mods = g("modules", {}) or {}
    mod_on = lambda n: mods.get(n, True) is not False
    ja = config.clock_time(g("night.journal_at") or "4:30 AM", (4, 30))
    ins = divmod((ja[0] * 60 + ja[1] + 30) % 1440, 60)
    news = config.clock_time((g("schedule.news_at") or ["6:30 AM"])[0], (6, 30))
    rows = [
        dict(id="briefing", title="Morning brief", what="Weather, your day and the news, on Telegram and Home", on=mod_on("briefing"),
             at=config.clock_time(g("schedule.briefing") or "7:00 AM", (7, 0)), switch="modules.briefing", time="schedule.briefing"),
        dict(id="news", title="News", what="Written before the brief, from your topics", on=mod_on("news") and mod_on("briefing"), at=news, switch="modules.news", time="schedule.news_at"),
        dict(id="evening", title="Evening check-in", what="Tomorrow's plan and what is still open today", on=g("schedule.evening_on", True) is not False,
             at=config.clock_time(g("schedule.evening_plan") or "9:00 PM", (21, 0)), switch="schedule.evening_on", time="schedule.evening_plan"),
        dict(id="journal", title="Journal summary", what="Your mood and a short summary of last night's entry. Tries again 2 and 4 hours later if it could not finish",
             on=mod_on("journal") and g("night.journal", True) is not False, at=ja, switch="night.journal", time="night.journal_at", needs="ai"),
        dict(id="insights", title="Deep insights", what="What lifts you, from your recent nights. Runs half an hour after the summary",
             on=mod_on("journal") and g("night.journal", True) is not False and g("night.insights", True) is not False, at=ins, switch="night.insights", needs="ai"),
        dict(id="weekly", title="Sunday report", what="Your week in numbers, Sundays", on=g("schedule.weekly_on", True) is not False, at=(10, 0), day=6, switch="schedule.weekly_on"),
        dict(id="recap", title="Weekly journal summary", what="A week of journal entries in one page, Wednesdays", on=bool(g("features.therapy_recap", False)),
             at=None, day=2, switch="features.therapy_recap", needs="ai"),
        dict(id="backup", title="Backup", what="Your data and settings in one file, the oldest removed after the number you keep",
             on=bool(g("night.backup", False)), at=config.clock_time(g("night.backup_at") or "3:30 AM", (3, 30)), switch="night.backup", time="night.backup_at", needs="helper",
             extra={"backup_to": g("night.backup_to") or "", "backup_keep": g("night.backup_keep") or 7}),
        dict(id="github", title="Copy settings to git", what="Your settings (never the journal, passwords or PIN) to your own private repository, with this machine's SSH key",
             on=bool(g("night.github", False)), at=config.clock_time(g("night.github_at") or "3:45 AM", (3, 45)), switch="night.github", time="night.github_at", needs="helper",
             extra={"github_repo": g("night.github_repo") or ""}),
    ]
    for r in rows:
        r["at24"] = f"{r['at'][0]:02d}:{r['at'][1]:02d}" if r["at"] else ""
        r["every"] = f"{DAYS[r['day']]}s" + (f" at {_t12(r['at'])}" if r["at"] else "") if r.get("day") is not None else (f"Every day at {_t12(r['at'])}" if r["at"] else "")
        r["at"] = _t12(r["at"]) if r["at"] else ""
        r["blocked"] = ("The host helper is not running, so this cannot run. Install it with: bin/homelab agent install" if r.get("needs") == "helper" and not helper_ok
                        else "No AI engine is set up, so this has nothing to write with. Add one in Settings, Apps." if r.get("needs") == "ai" and not ai_ok else "")
    return rows


def _dig(d, path, default=None):
    for p in path.split("."):
        if not isinstance(d, dict) or p not in d:
            return default
        d = d[p]
    return d


def routes(router, settings, helper_ok, ai_ok):
    @router.get("/schedule")
    def get_schedule(req):
        return {"jobs": plan(settings.merged(), helper_ok(), ai_ok())}

    @router.post("/schedule")
    def set_schedule(req):
        """{"set": {path: value}} for the paths the Schedule page shows. All or none."""
        if bad := guard_request(settings, req):
            return bad
        ch = (req.json() or {}).get("set")
        allowed = {p for r in plan(settings.merged()) for p in (r.get("switch"), r.get("time")) if p} | {"night.backup_to", "night.backup_keep", "night.github_repo"}
        if not isinstance(ch, dict) or not ch or any(k not in allowed for k in ch):
            return {"ok": False, "error": "Nothing to change, or a setting this page does not hold."}, 400
        if "schedule.news_at" in ch and not isinstance(ch["schedule.news_at"], list):
            ch["schedule.news_at"] = [ch["schedule.news_at"]]
        ok, problems = settings.set(ch)
        return ({"ok": True, "restart": True}, 200) if ok else ({"ok": False, "error": " ".join(problems)}, 400)
