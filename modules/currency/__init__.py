"""Currency conversion (ECB rates) and travel exchange rates."""
import re
from datetime import datetime, timedelta
from urllib.parse import urlencode
from zoneinfo import ZoneInfo

from core import host
from core.helpers import cached, esc, http, now, safe


# ================================================================ currency
CUR = {"sgd": "SGD", "singapore dollar": "SGD", "inr": "INR", "rupee": "INR", "rs": "INR", "₹": "INR", "usd": "USD",
       "dollar": "USD", "$": "USD", "eur": "EUR", "euro": "EUR", "gbp": "GBP", "pound": "GBP", "aed": "AED",
       "dirham": "AED", "jpy": "JPY", "yen": "JPY", "aud": "AUD", "myr": "MYR", "ringgit": "MYR", "thb": "THB", "baht": "THB"}


@cached(1800)
def fx_rate(a, b):
    if a == b:
        return 1.0
    return http(f"https://api.frankfurter.app/latest?from={a}&to={b}", timeout=15)["rates"][b]


COUNTRY_CUR = {"Singapore": "SGD", "United States": "USD", "United Kingdom": "GBP", "Australia": "AUD", "Canada": "CAD",
               "Italy": "EUR", "Germany": "EUR", "France": "EUR", "Netherlands": "EUR", "Spain": "EUR", "Ireland": "EUR",
               "Austria": "EUR", "Belgium": "EUR", "Portugal": "EUR", "Greece": "EUR", "Finland": "EUR", "Denmark": "DKK",
               "Switzerland": "CHF", "Sweden": "SEK", "Norway": "NOK", "Japan": "JPY", "United Arab Emirates": "AED",
               "Malaysia": "MYR", "Thailand": "THB", "New Zealand": "NZD", "Georgia": "GEL"}


def in_india(loc=None):
    return (loc or location()).get("country", "").strip().lower() in ("india", "in", "")


def travel_fx(loc=None):
    """Exchange rates for the briefing and home page, only when away from India: the local currency (when the ECB
    publishes it), SGD and USD, each in rupees. In India it's nothing; ask the assistant ("100 sgd to inr") instead."""
    loc = loc or location()
    if in_india(loc):
        return []
    out = []
    for c in dict.fromkeys(x for x in (COUNTRY_CUR.get(loc.get("country", "")), "SGD", "USD") if x):
        r = safe(lambda c=c: fx_rate(c, "INR"))
        if r:
            out.append((c, round(r, 2)))
    return out


def fx(text):
    t = text.lower()
    found = []
    for m in re.finditer(r"singapore dollars?|[a-z]+|[$₹]", t):
        w = m.group(0).rstrip("s") if m.group(0) not in ("rs",) else "rs"
        if w in CUR or m.group(0) in CUR:
            found.append(CUR.get(w) or CUR[m.group(0)])
    amt = float((re.search(r"(\d+(?:[.,]\d+)?)\s*(k)?", t.replace(",", "")) or [None, None])[1] or 1)
    if re.search(r"\d+(?:\.\d+)?\s*k\b", t):
        amt *= 1000
    a, b = (found + ["SGD", "INR"])[:2] if len(found) != 1 else (found[0], "INR" if found[0] != "INR" else "SGD")
    try:
        r = fx_rate(a, b)
    except Exception as e:
        return send(f"Exchange rates aren't available right now ({esc(e)}).")
    send(f"💱 <b>{amt:,.2f} {a} = {amt * r:,.2f} {b}</b>\n<i>1 {a} = {r:,.4f} {b} • ECB rate, updated daily</i>")


def register(app):
    host.need(globals(), "location", "send")
