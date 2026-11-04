"""One answer to "what is working, what is not, and what do I do about it": for the command line (`python -m core doctor`) and the Settings health page.
It only reads. Nothing here changes a setting or restarts anything."""
from core import registry


def report(caps, mods, enabled, started, notes, config=None, platform=None, machine=None):
    """A dict: ok (nothing is broken; degraded features are not breakage), platform, capabilities, modules and config problems.
    A module is on, degraded (on, but cannot use something optional), hidden (wrong platform), off (switched off or a missing requirement) or failed."""
    platform = platform or registry.this_platform()
    rows = []
    for n, m in sorted(mods.items()):
        if n.startswith("_"):
            continue
        degraded = caps.degraded(m.optional) if n in enabled else []
        if platform not in m.platforms:
            state, why = "hidden", notes.get(n) or f"{m.title} needs {' or '.join(m.platforms)}; this machine is {platform}."
        elif n not in enabled:
            state, why = "off", notes.get(n, "")
        elif n not in started:
            state, why = "failed", f"{m.title} could not start. The server log says why."
        else:
            state, why = ("degraded" if degraded else "on"), ""
        rows.append({"name": n, "title": m.title, "state": state, "why": why, "degraded": degraded})
    problems = list(getattr(config, "problems", None) or [])
    return {"ok": not problems and not any(r["state"] == "failed" for r in rows), "platform": platform,
            "capabilities": caps.all(), "modules": rows, "config": problems, "machine": machine}


MARK = {"on": "ok  ", "degraded": "warn", "hidden": "--  ", "off": "--  ", "failed": "FAIL"}


def render(rep):
    """The report as plain text for a terminal."""
    out = [f"Health check ({rep['platform']})", ""]
    if rep.get("machine"):
        out += [f"Your machine: {rep['machine']['summary']} ({rep['machine']['recommendation']['title']} profile)", ""]
    out.append("Services")
    for c in rep["capabilities"]:
        out.append(f"  {'ok  ' if c['ok'] else '--  ' if c.get('off') else 'warn'}  {c['title']}" + ("" if c["ok"] else f": {c['reason'] or 'not available'}"))
        if not c["ok"] and c["fix"]:
            out.append(f"        Fix: {c['fix']}")
    out += ["", "Modules"]
    for m in rep["modules"]:
        out.append(f"  {MARK[m['state']]}  {m['title']}" + (f": {m['why']}" if m["why"] else ""))
        for d in m["degraded"]:
            out.append(f"        limited without {d['feature']}. Fix: {d['fix']}")
    if rep["config"]:
        out += ["", "config.yaml"] + [f"  FAIL  {p}" for p in rep["config"]]
    out += ["", "Everything that matters is working." if rep["ok"] and all(c["ok"] or c.get("off") for c in rep["capabilities"]) else
            ("Nothing is broken, some features are limited (see warn above)." if rep["ok"] else "Something is broken (see FAIL above).")]
    return "\n".join(out)
