"""Money, one month at a time: income each month, bills each month with the day they are charged, what you spent, and what that
leaves for today. The maths is in budget.py. Names and amounts leave this module masked unless the request may see them: with a
settings PIN set, only a request that carries it does; without one, the page asks to show them (and masks them again on its own)."""
import json
import os
import re

from core import host
from core.helpers import now, safe

host.need(globals(), "DATA")

from modules.money.budget import amount, mask_name, month_key, plan  # noqa: E402

FILE = f"{DATA}/money.json"
SEED = {"currency": None, "income": [], "bills": [], "spent": {}}  # spent: {"2026-11": [{"id", "amount", "note", "day"}]}
CURRENCY = re.compile(r"^[A-Z]{3}$")


def load():
    try:
        return {**json.loads(json.dumps(SEED)), **json.load(open(FILE))}
    except Exception:
        return json.loads(json.dumps(SEED))


money = load()


def save():
    with _lock:
        tmp = FILE + ".tmp"
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)  # only you can read it on this machine
        with os.fdopen(fd, "w") as f:
            json.dump(money, f, indent=1)
        os.replace(tmp, FILE)


def new_id(items):
    taken = {x["id"] for x in items}
    while (i := os.urandom(3).hex()) in taken:
        pass
    return i


def view(show):
    """The Money page. show=False masks every name, note and amount: names keep their first letter, amounts become None."""
    t = now().date()
    with _lock:
        spent = money["spent"].get(month_key(t), [])
        p = plan(money["income"], money["bills"], spent, t)
        cur = money["currency"]
        income, bills = [dict(x) for x in money["income"]], [dict(x) for x in money["bills"]]
        spends = sorted((dict(x) for x in spent), key=lambda x: (x["day"], x["id"]), reverse=True)
    out = {"ok": True, "currency": cur, "setup": bool(cur), "month": month_key(t), "today": t.isoformat(), "shown": show,
           "income": income, "bills": bills, "spent": spends, **p}
    if show:
        return out
    hide = lambda rows: [{**r, "name": mask_name(r.get("name")), "note": mask_name(r["note"]) if r.get("note") else "", "amount": None} for r in rows]
    for k in ("income", "bills", "spent", "upcoming", "paid"):
        out[k] = hide(out[k])
    for k in ("total_income", "total_bills", "free", "total_spent", "spent_today", "today_budget", "left_today", "left_month", "charged"):
        out[k] = None
    out["over"] = p["today_budget"] < 0  # whether to say "over budget" is not a number, so it stays
    return out


def may_show(req):
    """With a settings PIN set, showing amounts needs it (sent as X-Settings-Pin); without one, asking is enough."""
    from core.settings import guard_request
    return req.query.get("show") == "1" and not guard_request(SETTINGS, req)


def api(path, b, req):
    from core.settings import guard_request
    if bad := guard_request(SETTINGS, req):  # changing money needs the PIN too, when one is set
        return bad
    b = b or {}
    t = now().date()
    with _lock:
        if path == "/money/currency":
            c = str(b.get("currency") or "").upper()
            if not CURRENCY.match(c):
                return {"ok": False, "msg": "Choose a currency."}, 400
            money["currency"] = c
        elif path in ("/money/income", "/money/bill"):
            rows = money["income" if path == "/money/income" else "bills"]
            name, a = str(b.get("name") or "").strip()[:40], amount(b.get("amount"))
            if not name:
                return {"ok": False, "msg": "Give it a name."}, 400
            if not a:
                return {"ok": False, "msg": "Type an amount, like 1200 or 1,200.50."}, 400
            row = {"name": name, "amount": a}
            if path == "/money/bill":
                if b.get("day") not in range(1, 32):
                    return {"ok": False, "msg": "Choose the day of the month it is charged."}, 400
                row["day"] = b["day"]
            old = next((x for x in rows if x["id"] == b.get("id")), None)
            if b.get("id") and not old:
                return {"ok": False, "msg": "That one is gone. Refresh and try again."}, 404
            if old:
                old.update(row)
            else:
                rows.append({"id": new_id(rows), **row})
        elif path in ("/money/income/delete", "/money/bill/delete"):
            k = "income" if "income" in path else "bills"
            money[k] = [x for x in money[k] if x["id"] != b.get("id")]
        elif path == "/money/spent":  # {amount, note?, day?}: today unless another day of this month is given
            a, day = amount(b.get("amount")), b.get("day") or t.day
            if not a:
                return {"ok": False, "msg": "Type how much, like 12 or 12.50."}, 400
            if day not in range(1, t.day + 1):
                return {"ok": False, "msg": "Choose a day of this month, up to today."}, 400
            rows = money["spent"].setdefault(month_key(t), [])
            rows.append({"id": new_id(rows), "amount": a, "note": str(b.get("note") or "").strip()[:40], "day": day})
        elif path == "/money/spent/delete":
            m = month_key(t)
            money["spent"][m] = [x for x in money["spent"].get(m, []) if x["id"] != b.get("id")]
        else:
            return {"error": "not found"}, 404
        money["spent"] = {k: v for k, v in money["spent"].items() if k >= f"{t.year - 1:04d}"}  # a year of spending is plenty
        save()
    return view(may_show(req)), 200


def register(app):
    host.need(globals(), "SETTINGS", "_lock")
    app.router.add("GET", "/money", lambda req: view(may_show(req)))
    app.router.add_prefix("POST", "/money/", lambda req: api(req.path, req.json(), req))
