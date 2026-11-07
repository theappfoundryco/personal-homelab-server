"""The monthly budget maths. Plain functions over plain data, so tests need no clock and no files.
These are the budget calculations the project treats as frozen: change one only with the maintainer's yes (CONTRIBUTING.md).

All amounts are whole minor units (cents, paise), so nothing is lost to rounding. For the month of `today`:
  free           = income each month - every bill this month, charged yet or not
  today_budget   = (free - spent before today) / days left in the month, today included
  left_today     = today_budget - spent today
  left_month     = free - everything spent this month
Bills are monthly only for now. A bill on the 29th, 30th or 31st is charged on the month's last day in a shorter month."""
import calendar
import re
from datetime import date


def days_in(d):
    return calendar.monthrange(d.year, d.month)[1]


def charge_day(bill, d):
    """The day of d's month that this bill is charged."""
    return min(int(bill["day"]), days_in(d))


def month_key(d):
    return f"{d.year:04d}-{d.month:02d}"


def plan(income, bills, spent, today):
    """Everything the Money page shows for today's month. spent is this month's list: [{"amount", "day"}]."""
    total_in = sum(int(x["amount"]) for x in income)
    total_bills = sum(int(b["amount"]) for b in bills)
    free = total_in - total_bills
    n, t = days_in(today), today.day
    before = sum(int(s["amount"]) for s in spent if int(s["day"]) < t)
    on_day = sum(int(s["amount"]) for s in spent if int(s["day"]) == t)
    days_left = n - t + 1
    budget = (free - before) // days_left if free - before >= 0 else -((before - free) // days_left)  # whole units, rounded towards zero
    charged = [b for b in bills if charge_day(b, today) <= t]
    return {"total_income": total_in, "total_bills": total_bills, "free": free, "total_spent": sum(int(s["amount"]) for s in spent),
            "spent_today": on_day, "days": n, "days_left": days_left, "today_budget": budget, "left_today": budget - on_day,
            "left_month": free - sum(int(s["amount"]) for s in spent), "charged": sum(int(b["amount"]) for b in charged),
            "upcoming": sorted(({**b, "on": charge_day(b, today)} for b in bills if charge_day(b, today) > t), key=lambda b: b["on"]),
            "paid": sorted(({**b, "on": charge_day(b, today)} for b in charged), key=lambda b: b["on"])}


def amount(v):
    """A typed amount ("1,250.50", 1250.5, "₹ 99") as whole minor units, or None."""
    if isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        return round(v * 100) if 0 <= v < 1e10 else None
    if re.search(r"[A-Za-z-]", str(v or "")):  # words, exponents or a minus sign: not an amount someone typed
        return None
    s = "".join(ch for ch in str(v or "") if ch.isdigit() or ch in ".,")
    if not s:
        return None
    if "," in s and "." in s:  # 1,250.50 or 1.250,50: the last mark is the decimal one
        s = s.replace(",", "") if s.rfind(".") > s.rfind(",") else s.replace(".", "").replace(",", ".")
    elif "," in s:
        s = s.replace(",", ".") if len(s.rsplit(",", 1)[1]) in (1, 2) else s.replace(",", "")
    try:
        f = float(s)
    except ValueError:
        return None
    return round(f * 100) if 0 <= f < 1e10 else None


def mask_name(name):
    """The first letter and three stars, whatever the length, so a masked list gives nothing away."""
    name = str(name or "").strip()
    return (name[:1] + "***") if name else "***"
