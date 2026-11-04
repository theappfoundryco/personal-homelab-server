"""Medicines (0.2.0): when each kind of schedule is due, the form's checks, the move from the old slots and courses, the API,
and Telegram reminders that only go out while the bot is connected (clock frozen at 3 Nov 2026, 10 AM UTC; network blocked)."""
import copy, importlib.util, json, os, tempfile, unittest
from datetime import date, timedelta

import harness
from harness import load_bot

_spec = importlib.util.spec_from_file_location("health_meds", os.path.join(harness.ROOT, "modules", "health", "meds.py"))
M = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(M)  # on its own: the package needs the running assistant

TUE = date(2026, 11, 3)


class Schedules(unittest.TestCase):
    def test_each_kind_falls_on_the_right_days_and_stops(self):
        daily = {"every": "day", "start": "2026-11-01", "times": ["08:00"]}
        self.assertEqual([M.dose_no(daily, date(2026, 11, d)) for d in (1, 3)], [1, 3])
        self.assertEqual(M.dose_no(daily, date(2026, 10, 31)), 0)  # not before it starts
        weekly = {"every": "week", "weekday": 0, "start": "2026-11-03", "times": ["09:00"], "stop_after": 2}  # Mondays, from a Tuesday
        self.assertEqual([M.dose_no(weekly, date(2026, 11, d)) for d in (3, 9, 16, 23)], [0, 1, 2, 0])
        two = {"every": "2weeks", "start": "2026-11-09", "times": ["10:00"]}
        self.assertEqual([x for x in range(9, 40) if M.dose_no(two, date(2026, 11, 9) + timedelta(days=x - 9))], [9, 23, 37])
        monthly = {"every": "month", "monthday": 5, "start": "2026-11-10", "times": ["09:00"]}  # started after the 5th: first one in December
        self.assertEqual((M.dose_no(monthly, date(2026, 11, 5)), M.dose_no(monthly, date(2026, 12, 5)), M.dose_no(monthly, date(2027, 1, 5))), (0, 1, 2))
        self.assertEqual(M.next_due(monthly, TUE), date(2026, 12, 5))
        self.assertIsNone(M.next_due(weekly, date(2026, 11, 17)))  # finished

    def test_the_meds_day_runs_4_am_to_4_am(self):
        self.assertLess(M.early("23:00"), M.early("01:00"))
        self.assertEqual(M.at(TUE, "01:00").date(), date(2026, 11, 4))
        self.assertEqual(M.at(TUE, "08:00").date(), TUE)

    def test_the_form_says_what_to_fix(self):
        ok = {"name": "Vitamin D", "every": "day", "times": ["20:00", "08:00", "08:00", "bad"]}
        m, why = M.clean(ok, TUE)
        self.assertEqual((m["times"], m["start"], why), (["08:00", "20:00"], "2026-11-03", None))
        for bad, msg in [({**ok, "name": " "}, "Give it a name."), ({**ok, "every": "hourly"}, "Choose how often."), ({**ok, "times": []}, "Add a time."),
                         ({**ok, "every": "week"}, "Choose the day of the week."), ({**ok, "every": "month", "monthday": 31}, "Choose a date from 1 to 28 (every month has those)."),
                         ({**ok, "stop_after": -1}, "Stop after must be a number from 1 to 999.")]:
            self.assertEqual(M.clean(bad, TUE), (None, msg))
        self.assertEqual(M.clean({**ok, "every": "week", "weekday": 2, "times": ["09:00", "18:00"]}, TUE)[0]["times"], ["09:00"])  # one time unless every day

    def test_the_old_slots_and_courses_become_medicines_with_their_ticks(self):
        old = {"slots": [{"id": "morning", "label": "Morning", "when": "8:00 AM", "items": ["Vitamin D", "Iron"]}, {"id": "night", "label": "Night", "items": ["Magnesium"]}],
               "courses": [{"id": "c1", "name": "B12", "weekday": 0, "start": "2026-10-19", "weeks": 6}], "health": [],
               "log": {"2026-10-20": {"morning": True, "night": False}, "2026-10-26": {"c1": True}}}
        self.assertTrue(M.convert_old(old, TUE))
        self.assertEqual([(m["id"], m["name"], m["every"], m["times"], m["remind"]) for m in old["meds"]],
                         [("morning", "Vitamin D, Iron", "day", ["08:00"], True), ("night", "Magnesium", "day", ["21:00"], True), ("c1", "B12", "week", ["09:00"], True)])
        self.assertEqual(old["meds"][2]["stop_after"], 6)
        self.assertEqual(old["log"], {"2026-10-20": {"morning@0800": True}, "2026-10-26": {"c1@0900": True}})
        self.assertNotIn("slots", old)
        self.assertFalse(M.convert_old(old, TUE))  # safe to run twice

    def test_the_migration_rewrites_the_saved_file(self):
        import importlib
        d = tempfile.mkdtemp()
        json.dump({"slots": [{"id": "lunch", "label": "Lunch", "items": ["Iron"]}], "courses": [], "health": [], "log": {}}, open(f"{d}/sg.json", "w"))
        importlib.import_module("core.migrations.0002_medicines").run(d)
        self.assertEqual(json.load(open(f"{d}/sg.json"))["meds"][0]["times"], ["14:00"])
        importlib.import_module("core.migrations.0002_medicines").run(os.path.join(d, "missing"))  # no file: nothing to do, no crash


class Api(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.bot = load_bot()
        cls.base = harness.start_api(cls.bot)[1]

    def setUp(self):
        import modules.health as m
        self.m, keep, state = m, copy.deepcopy(m.sg), copy.deepcopy(m.state)
        self.addCleanup(lambda: (m.sg.clear(), m.sg.update(keep), m.state.clear(), m.state.update(state)))
        self.sent = []
        self.patch(sg_save=lambda: None, save=lambda: None, send=lambda text, buttons=None, **kw: self.sent.append((text, buttons)))

    def patch(self, **attrs):
        for k, v in attrs.items():
            self.addCleanup(setattr, self.m, k, getattr(self.m, k))
            setattr(self.m, k, v)

    def post(self, path, body):
        return harness.call(self.base, "POST", path, body)

    def test_add_change_and_delete_a_medicine_and_an_appointment(self):
        code, out = self.post("/sg/med", {"name": "Zinc", "dose": "1 tablet", "every": "month", "monthday": 3, "times": ["09:00"]})
        self.assertEqual(code, 200)
        z = next(x for x in out["meds"] if x["name"] == "Zinc")
        self.assertEqual(z["next"], "2026-11-03")
        self.assertIn(f"{z['id']}@0900", [d["key"] for d in out["doses"]])  # due today, so it is in today's list
        out = self.post("/sg/med", {**z, "monthday": 20})[1]
        self.assertEqual(next(x for x in out["meds"] if x["id"] == z["id"])["next"], "2026-11-20")
        self.assertNotIn(z["id"], [x["id"] for x in self.post("/sg/med/delete", {"id": z["id"]})[1]["meds"]])
        self.assertEqual(self.post("/sg/med", {"name": "", "every": "day", "times": ["09:00"]}), (400, {"ok": False, "msg": "Give it a name."}))
        self.assertEqual(self.post("/sg/med", {"id": "gone", "name": "X", "every": "day", "times": ["09:00"]})[0], 404)
        a = self.post("/sg/appt", {"name": "Eye test", "due": "2026-12-01"})[1]["health"][-1]
        self.assertEqual((a["name"], a["due"]), ("Eye test", "2026-12-01"))
        self.assertNotIn(a["id"], [x["id"] for x in self.post("/sg/appt/delete", {"id": a["id"]})[1]["health"]])
        self.assertEqual(self.post("/sg/appt", {"name": "No date"})[0], 400)

    def test_reminders_need_telegram_in_the_form_the_api_and_the_reminder_loop(self):
        self.patch(telegram_on=lambda: False)
        self.assertFalse(harness.call(self.base, "GET", "/sg")[1]["telegram"])  # the form hides the switch
        code, out = self.post("/sg/med", {"name": "Zinc", "every": "day", "times": ["09:00"], "remind": True})
        self.assertEqual((code, out["msg"]), (400, "Connect Telegram first (Settings, Telegram), then turn reminders on."))
        self.m.sg["meds"] = [{"id": "z1", "name": "Zinc", "dose": "", "every": "day", "times": ["09:00"], "start": "2026-11-01", "remind": True}]
        self.m.check_meds()
        self.assertEqual(self.sent, [])  # saved earlier with reminders on, then Telegram went away: nothing is sent, nothing breaks

    def test_a_reminder_offers_done_5_and_15_minutes_and_stops_once_ticked(self):
        self.patch(telegram_on=lambda: True)
        t = self.m.now() - timedelta(hours=1)
        hm = f"{t:%H:%M}"
        self.m.sg["meds"] = [{"id": "z2", "name": "Zinc", "dose": "1 tablet", "every": "day", "times": [hm], "start": "2026-11-01", "remind": True},
                             {"id": "z3", "name": "Quiet", "dose": "", "every": "day", "times": [hm], "start": "2026-11-01", "remind": False}]
        self.m.check_meds()
        self.assertEqual(len(self.sent), 1)  # only the one with reminders on
        text, buttons = self.sent[0]
        self.assertIn("Zinc", text)
        self.assertEqual([b["text"] for b in buttons[0]], ["✅ Done", "💤 5 min", "💤 15 min"])
        self.m.check_meds()
        self.assertEqual(len(self.sent), 1)  # once
        k, d = f"z2@{hm.replace(':', '')}", self.m.meds_day().isoformat()
        self.assertIn("again at", self.m.med_snooze(k, d, 15))
        self.m.state["med_snooze"][f"{k}:{d}"] = 0  # the snooze has run out
        self.m.check_meds()
        self.assertEqual(len(self.sent), 2)
        self.assertIn("Reminding you again", self.sent[1][0])
        self.assertIn("ticked", self.m.med_tick(k, d))
        self.m.state.setdefault("med_snooze", {})[f"{k}:{d}"] = 0
        self.m.check_meds()
        self.assertEqual(len(self.sent), 2)  # ticked: no more reminders
        self.assertIn("ticked", self.m.med_tick("z2", d))  # an old button with no time still works

    def test_typing_that_you_took_one_ticks_it(self):
        t = self.m.now() - timedelta(minutes=30)
        self.m.sg["meds"] = [{"id": "z4", "name": "Magnesium", "dose": "", "every": "day", "times": [f"{t:%H:%M}"], "start": "2026-11-01", "remind": False}]
        self.assertIn("Magnesium", self.m.typed_meds("took my magnesium"))
        self.assertTrue(self.m.sg["log"][self.m.meds_day().isoformat()][f"z4@{t:%H%M}"])
        self.assertIsNone(self.m.typed_meds("did i take my magnesium?"))


if __name__ == "__main__":
    unittest.main()
