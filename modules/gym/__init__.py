"""Gym log: your training days, exercises, sets and body weight."""
import json
import os
import re
import time
import uuid
from datetime import datetime, timedelta

from core import host

host.need(globals(), "DATA")

GYM_FILE = f"{DATA}/gym.json"


def _gym_load():
    try:
        return {"days": [], "exercises": [], "sessions": [], "weight": [], **json.load(open(GYM_FILE))}
    except Exception:
        return {"days": [], "exercises": [], "sessions": [], "weight": []}


gym = _gym_load()


def gym_save():
    with _lock:
        tmp = GYM_FILE + ".tmp"
        json.dump(gym, open(tmp, "w"), indent=1)
        os.replace(tmp, GYM_FILE)


def gym_key(name):
    """Loose form of a name so "DB bench presses" and "dumbbell bench press" count as one."""
    n = re.sub(r"[^a-z0-9 ]+", " ", name.lower())
    words = {"db": "dumbbell", "dbs": "dumbbell", "bb": "barbell", "kb": "kettlebell", "inc": "incline", "dec": "decline",
             "ext": "extension", "extensions": "extension", "ohp": "overhead press", "rdl": "romanian deadlift", "rdls": "romanian deadlift"}
    out = []
    for w in n.split():
        w = words.get(w, w)
        if len(w) > 3 and w.endswith("s") and not w.endswith("ss"):
            w = w[:-1]
        if w not in ("the", "a", "on", "with"):
            out.append(w)
    return " ".join(out)


def gym_clean(name, n=60):
    return re.sub(r"\s+", " ", str(name or "")).strip()[:n]


def gym_today():
    return datetime.now(TZ).strftime("%Y-%m-%d")


def gym_date(b):
    """The date a write is for: today unless the page sends a past "date" (a missed workout). None if it's bad."""
    d = b.get("date")
    if not d:
        return gym_today()
    try:
        day = datetime.strptime(str(d), "%Y-%m-%d").date()
    except ValueError:
        return None
    today = datetime.now(TZ).date()
    return day.isoformat() if today - timedelta(days=730) <= day <= today else None


def gym_api(path, b):
    """All gym writes. Returns (reply, status)."""
    with _lock:
        if path == "/gym/weight":  # {date, kg} saves (one per day, a second one replaces it); {date, delete: true} removes
            try:
                d = datetime.strptime(str(b.get("date") or ""), "%Y-%m-%d").date().isoformat()
            except ValueError:
                return {"ok": False, "msg": "Pick a date."}, 400
            if d > gym_today():
                return {"ok": False, "msg": "That date hasn't happened yet."}, 400
            ws = gym.setdefault("weight", [])
            if b.get("delete"):
                gym["weight"] = [w for w in ws if w["date"] != d]
            else:
                try:
                    kg = round(float(str(b.get("kg")).replace(",", ".")), 2)
                except (TypeError, ValueError):
                    kg = 0
                if not 30 <= kg <= 250:
                    return {"ok": False, "msg": "Enter your weight in kg, like 85.4."}, 400
                gym["weight"] = sorted([w for w in ws if w["date"] != d] + [{"date": d, "kg": kg, "at": time.time()}], key=lambda w: w["date"])
            gym_save()
            return {"ok": True, "weight": gym["weight"]}, 200
        if path == "/gym/day":
            name = gym_clean(b.get("name"), 30)
            if not name:
                return {"ok": False, "msg": "Give the day a name."}, 400
            d = next((d for d in gym["days"] if gym_key(d["name"]) == gym_key(name)), None)
            if d:
                d.pop("hidden", None)
            else:
                d = {"id": uuid.uuid4().hex[:8], "name": name, "created": time.time()}
                gym["days"].append(d)
            gym_save()
            return {"ok": True, "day": d}, 200
        if path == "/gym/day/edit":
            d = next((d for d in gym["days"] if d["id"] == b.get("id")), None)
            if not d:
                return {"ok": False, "msg": "Unknown day."}, 404
            if b.get("move") in (-1, 1):  # order decides which day comes up next
                vis = [x for x in gym["days"] if not x.get("hidden")]
                i = vis.index(d) if d in vis else -1
                j = i + b["move"]
                if i >= 0 and 0 <= j < len(vis):
                    a_, b_ = gym["days"].index(vis[i]), gym["days"].index(vis[j])
                    gym["days"][a_], gym["days"][b_] = gym["days"][b_], gym["days"][a_]
            elif b.get("remove"):
                d["hidden"] = True  # history stays, adding the same name again brings it back
            elif gym_clean(b.get("name"), 30):
                d["name"] = gym_clean(b["name"], 30)
            gym_save()
            return {"ok": True}, 200
        if path == "/gym/exercise":
            day, name = b.get("day"), gym_clean(b.get("name"))
            if not name or not any(d["id"] == day for d in gym["days"]):
                return {"ok": False, "msg": "Pick a day and a name."}, 400
            e = next((e for e in gym["exercises"] if e["day"] == day and gym_key(e["name"]) == gym_key(name)), None)
            if e:
                e.pop("hidden", None)
            else:
                e = {"id": uuid.uuid4().hex[:8], "day": day, "name": name, "created": time.time()}
                if b.get("timed") or re.search(r"\bplanks?\b|\bholds?\b|wall sit|dead hang", name.lower()):
                    e["timed"] = True  # logged in seconds, not weight and reps
                gym["exercises"].append(e)
            gym_save()
            return {"ok": True, "exercise": e}, 200
        if path == "/gym/exercise/edit":
            e = next((e for e in gym["exercises"] if e["id"] == b.get("id")), None)
            if not e:
                return {"ok": False, "msg": "Unknown exercise."}, 404
            if b.get("remove"):
                e["hidden"] = True
            elif "note" in b:
                e["note"] = gym_clean(b.get("note"), 120)
                if not e["note"]:
                    e.pop("note")
            elif gym_clean(b.get("name")):
                e["name"] = gym_clean(b["name"])
            gym_save()
            return {"ok": True}, 200
        if path == "/gym/set":
            e = next((e for e in gym["exercises"] if e["id"] == b.get("ex")), None)
            try:
                kg, reps, secs = round(float(b.get("kg") or 0), 2), int(b.get("reps") or 0), int(b.get("secs") or 0)
            except (TypeError, ValueError):
                kg, reps, secs = -1, 0, 0
            if e and e.get("timed"):
                if not (0 < secs <= 3600):
                    return {"ok": False, "msg": "Enter how long you held it."}, 400
                kg, reps = 0, 0
            elif not e or not (0 <= kg <= 1000) or not (0 < reps <= 500):
                return {"ok": False, "msg": "Enter the weight and how many reps."}, 400
            date = gym_date(b)
            if not date:
                return {"ok": False, "msg": "Pick a day that isn't in the future."}, 400
            ses = next((x for x in gym["sessions"] if x["day"] == e["day"] and x["date"] == date), None)
            if not ses:
                ses = {"id": uuid.uuid4().hex[:8], "day": e["day"], "date": date, "started": time.time(), "sets": []}
                if date != gym_today():
                    ses["finished"] = time.time()  # a workout added afterwards is already over
                gym["sessions"].append(ses)
            # the first set of an exercise is the warm-up unless the page says it isn't (warm-up skipped)
            first = not any(x["ex"] == e["id"] for x in ses["sets"])
            warm = False if e.get("timed") else bool(b["warm"]) if "warm" in b and first else first
            st = {"id": uuid.uuid4().hex[:8], "ex": e["id"], "kg": kg, "reps": reps, "warm": warm, "at": time.time()}
            if e.get("timed"):
                st["secs"] = secs
            ses["sets"].append(st)
            if date == gym_today():
                ses.pop("finished", None)  # logging more reopens today's finished workout
            gym_save()
            return {"ok": True, "set": st, "session": ses["id"]}, 200
        if path == "/gym/finish":  # {day, undo}: mark today's workout for that day finished, or reopen it
            ses = next((x for x in gym["sessions"] if x["day"] == b.get("day") and x["date"] == (gym_date(b) or "")), None)
            if not ses:
                return {"ok": False, "msg": "Nothing logged today."}, 404
            if b.get("undo"):
                ses.pop("finished", None)
            else:
                ses["finished"] = time.time()
            gym_save()
            return {"ok": True}, 200
        if path == "/gym/set/delete":
            for ses in gym["sessions"]:
                if any(x["id"] == b.get("id") for x in ses["sets"]):
                    ses["sets"] = [x for x in ses["sets"] if x["id"] != b.get("id")]
            gym["sessions"] = [x for x in gym["sessions"] if x["sets"]]
            gym_save()
            return {"ok": True}, 200
    return {"ok": False, "msg": "bad request"}, 400

def register(app):
    host.need(globals(), "TZ", "_lock")

    @app.router.get("/gym")
    def gym_view(req):
        with _lock:
            return {**gym, "today": gym_today()}

    app.router.add_prefix("POST", "/gym/", lambda req: gym_api(req.path, req.json()))
