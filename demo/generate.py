#!/usr/bin/env python3
"""Writes obviously fake demo data in the shape the bot stores it. Same seed, same output.

    python3 demo/generate.py OUT_DIR [--today 2026-11-03] [--seed 42]

Every name, entry and number here is invented. Used by the tests, the screenshots and the README demo.
"""
import argparse
import json
import os
import random
from datetime import date, datetime, time as dtime, timedelta, timezone

MOODS_TEXT = [
    "Slow start, but the walk after lunch helped. Nothing dramatic today.",
    "Got through the whole to-do list for once. Felt proud of that.",
    "Tired all day. Went to bed early and tried not to scroll.",
    "Good call with Sam about the trip. Looking forward to it.",
    "Rainy and quiet. Cooked something new and it actually worked.",
    "Rough meeting, then a long run to clear my head. Calmer now.",
    "Lazy Sunday. Read for two hours and napped.",
    "Gym felt strong today. Added a little weight on the press.",
]
TAGS = ["work", "gym", "health", "sleep", "food", "friends", "music", "shows", "travel"]
FEELINGS = ["calm", "happy", "grateful", "proud", "hopeful", "anxious", "relieved"]
PEOPLE = ["Sam", "Jo", "Riley", "Casey"]
NOTES = ["Buy oat milk", "Renew library card", "Book dentist", "Try the new ramen place", "Fix the bike light",
         "Ideas for the weekend project", "Reply to Jo about dinner"]
GOALS = ["Run a 10k", "Read 20 books this year", "Sleep before midnight", "Learn 50 words of Spanish"]
DAYS = {"Push": ["Bench press", "Overhead press", "Tricep pushdown"],
        "Pull": ["Barbell row", "Lat pulldown", "Bicep curl"],
        "Legs": ["Squat", "Romanian deadlift", "Plank"]}
START_KG = {"Bench press": 50, "Overhead press": 30, "Tricep pushdown": 20, "Barbell row": 45, "Lat pulldown": 40,
            "Bicep curl": 12, "Squat": 60, "Romanian deadlift": 55, "Plank": 0}


def dump(path, data, **kw):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        json.dump(data, f, indent=1, ensure_ascii=False, sort_keys=True, **kw)


def ts(d, hour=12, minute=0):
    return datetime.combine(d, dtime(hour, minute), tzinfo=timezone.utc).timestamp()


def build(out, today, seed=42):
    r = random.Random(seed)
    days = [today - timedelta(days=i) for i in range(59, -1, -1)]
    uid = lambda: f"{r.getrandbits(32):08x}"

    # journal: settings, a year index, and the words per month
    entries = []
    for d in days:
        if r.random() < 0.3:
            continue
        text = r.choice(MOODS_TEXT)
        entries.append({"date": d.isoformat(), "created": ts(d, 22), "updated": ts(d, 22), "words": len(text.split()),
                        "mood": r.randint(4, 9), "feelings": r.sample(FEELINGS, 2), "tags": r.sample(TAGS, 2),
                        "people": r.sample(PEOPLE, r.randint(0, 2)), "summary": text.split(".")[0] + ".", "text": text})
    dump(f"{out}/journal/settings.json", {})
    for y in sorted({e["date"][:4] for e in entries}):
        dump(f"{out}/journal/{y}/index.json", [{k: v for k, v in e.items() if k != "text"} for e in entries if e["date"][:4] == y])
    for m in sorted({e["date"][:7] for e in entries}):
        dump(f"{out}/journal/{m[:4]}/{m}.json", {e["date"]: e["text"] for e in entries if e["date"][:7] == m})

    # gym: three days, a session roughly every other day with a little progress
    gym = {"days": [], "exercises": [], "sessions": [], "weight": []}
    ex_id = {}
    for name, exs in DAYS.items():
        did = uid()
        gym["days"].append({"id": did, "name": name, "created": ts(days[0])})
        for e in exs:
            ex = {"id": uid(), "day": did, "name": e, "created": ts(days[0])}
            if e == "Plank":
                ex["timed"] = True
            gym["exercises"].append(ex)
            ex_id[e] = (ex["id"], did)
    names = list(DAYS)
    for i, d in enumerate(days[::2]):
        name = names[i % 3]
        did = gym["days"][i % 3]["id"]
        sets = []
        for e in DAYS[name]:
            eid = ex_id[e][0]
            kg = START_KG[e] + (i // 3) * 1.25
            for n in range(4):
                st = {"id": uid(), "ex": eid, "kg": 0 if e == "Plank" else kg, "reps": 0 if e == "Plank" else 10 - n,
                      "warm": n == 0 and e != "Plank", "at": ts(d, 18, n * 3)}
                if e == "Plank":
                    st["secs"] = 40 + 5 * n
                sets.append(st)
        gym["sessions"].append({"id": uid(), "day": did, "date": d.isoformat(), "started": ts(d, 18), "finished": ts(d, 19), "sets": sets})
    for i, d in enumerate(days[::7]):
        gym["weight"].append({"date": d.isoformat(), "kg": round(78.0 - i * 0.3, 1), "at": ts(d, 7)})
    dump(f"{out}/gym.json", gym)

    # notes, goals, reminders
    state = {"notes": [{"id": uid(), "text": t, "added": ts(today - timedelta(days=i))} for i, t in enumerate(NOTES)],
             "goals": [{"id": uid(), "text": g, "added": ts(days[0]), "done": i == 3} for i, g in enumerate(GOALS)],
             "reminders": [{"id": uid(), "text": "Water the plants", "due": ts(today + timedelta(days=1), 9), "repeat": None}],
             "sent": {}, "history": []}
    dump(f"{out}/state.json", state)

    # AI usage over the last two weeks
    usage = {}
    for d in days[-14:]:
        usage[d.isoformat()] = {"chat": {"in": r.randint(2000, 9000), "out": r.randint(500, 3000), "calls": r.randint(3, 15)},
                                "journal": {"in": r.randint(1000, 4000), "out": r.randint(200, 900), "calls": r.randint(1, 4)}}
    dump(f"{out}/ai-usage.json", usage)

    # health: invented medication slots, a weekly course and one appointment
    slots = [{"id": "morning", "label": "Morning", "when": "8:00 AM", "items": ["Vitamin D", "Multivitamin"]},
             {"id": "night", "label": "Night", "when": "10:00 PM", "items": ["Magnesium"]}]
    log = {d.isoformat(): {"morning": r.random() < 0.8, "night": r.random() < 0.6} for d in days[-14:]}
    dump(f"{out}/sg.json", {"slots": slots, "log": log,
                            "courses": [{"id": "course1", "name": "Demo weekly dose", "weekday": 0, "start": (today - timedelta(days=14)).isoformat(), "weeks": 6}],
                            "health": [{"id": "appt1", "name": "Demo check-up", "due": (today + timedelta(days=20)).isoformat(), "why": "yearly"}]})
    dump(f"{out}/planner-past.json", {})
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("out")
    ap.add_argument("--today", default="2026-11-03")
    ap.add_argument("--seed", type=int, default=42)
    a = ap.parse_args()
    build(a.out, date.fromisoformat(a.today), a.seed)
    print(f"demo data written to {a.out}")


if __name__ == "__main__":
    main()
