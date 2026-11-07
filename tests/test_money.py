"""Money (0.3.0), monthly only. The budget maths is frozen once released: these tests are its contract (clock frozen at 3 Nov 2026)."""
import importlib.util, json, os, unittest
from datetime import date

import harness

_spec = importlib.util.spec_from_file_location("money_budget", os.path.join(harness.ROOT, "modules", "money", "budget.py"))
B = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(B)
NOV3 = date(2026, 11, 3)


class Maths(unittest.TestCase):
    def test_todays_budget_counts_every_bill_this_month_and_spreads_what_is_left(self):
        income, bills = [{"amount": 480000}, {"amount": 40000}], [{"amount": 180000, "day": 1}, {"amount": 4500, "day": 8}, {"amount": 1099, "day": 14}, {"amount": 4000, "day": 31}]
        p = B.plan(income, bills, [], NOV3)
        self.assertEqual((p["total_income"], p["total_bills"], p["free"]), (520000, 189599, 330401))
        self.assertEqual((p["days"], p["days_left"]), (30, 28))  # 3 Nov, today included
        self.assertEqual(p["today_budget"], 11800)  # 3,304.01 / 28 = 118.00
        self.assertEqual([b["on"] for b in p["upcoming"]], [8, 14, 30])  # the 31st falls on the 30th in November
        self.assertEqual(p["charged"], 180000)

    def test_spending_lowers_today_and_spreads_over_the_days_after(self):
        bills, income = [{"amount": 100000, "day": 1}], [{"amount": 400000}]
        p = B.plan(income, bills, [{"amount": 2350, "day": 3}], NOV3)
        self.assertEqual((p["today_budget"], p["spent_today"], p["left_today"]), (10714, 2350, 8364))  # 3,000 / 28; spent today comes off today only
        p2 = B.plan(income, bills, [{"amount": 2350, "day": 3}], date(2026, 11, 4))
        self.assertEqual(p2["today_budget"], (300000 - 2350) // 27)  # tomorrow: yesterday's spending is shared by the days left
        self.assertEqual(p2["left_month"], 297650)

    def test_more_bills_than_income_is_over_budget(self):
        p = B.plan([{"amount": 100000}], [{"amount": 160000, "day": 5}], [], NOV3)
        self.assertLess(p["today_budget"], 0)
        self.assertEqual(p["today_budget"], -(60000 // 28))

    def test_the_last_day_gets_everything_left(self):
        p = B.plan([{"amount": 300000}], [], [{"amount": 290000, "day": 1}], date(2026, 11, 30))
        self.assertEqual((p["days_left"], p["today_budget"]), (1, 10000))

    def test_amounts_are_read_the_way_people_type_them(self):
        for typed, cents in (("1,250.50", 125050), ("1.250,50", 125050), ("1,00,000", 10000000), ("99", 9900), ("12,5", 1250), ("₹ 2,500", 250000), (12.5, 1250)):
            self.assertEqual(B.amount(typed), cents, typed)
        for bad in ("abc", "", True, -5, "1e99"):
            self.assertIsNone(B.amount(bad), bad)

    def test_a_masked_name_is_one_letter_and_three_stars_whatever_its_length(self):
        self.assertEqual([B.mask_name(n) for n in ("Rent", "Netflix Premium Family", "X", "")], ["R***", "N***", "X***", "***"])


class Api(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.bot = harness.load_bot()
        cls.base = harness.start_api(cls.bot)[1]

    def setUp(self):
        import modules.money as m
        self.m = m
        keep = json.loads(json.dumps(m.money))
        self.addCleanup(lambda: (m.money.clear(), m.money.update(keep)))
        m.money.clear(); m.money.update(json.loads(json.dumps(m.SEED)))

    def call(self, method, path, body=None, pin=None):
        if pin is None:
            return harness.call(self.base, method, path, body)
        from urllib.request import Request, urlopen
        req = Request(self.base + path, data=None if body is None else json.dumps(body).encode(), method=method, headers={"Content-Type": "application/json", "X-Settings-Pin": pin})
        with urlopen(req, timeout=30) as r:
            return r.status, json.loads(r.read() or b"{}")

    def test_amounts_and_names_leave_masked_unless_asked_for(self):
        self.assertFalse(self.call("GET", "/money")[1]["setup"])
        self.assertEqual(self.call("POST", "/money/currency", {"currency": "eur"})[1]["currency"], "EUR")
        self.call("POST", "/money/income", {"name": "Salary", "amount": "4,000"})
        out = self.call("POST", "/money/bill", {"name": "Rent", "amount": "1200", "day": 5})[1]
        self.assertEqual((out["income"][0]["name"], out["income"][0]["amount"], out["today_budget"]), ("S***", None, None))  # masked by default
        self.assertNotIn("Salary", json.dumps(out))
        self.assertNotIn("400000", json.dumps(out))
        shown = self.call("GET", "/money?show=1")[1]
        self.assertEqual((shown["income"][0]["name"], shown["total_income"], shown["today_budget"]), ("Salary", 400000, 280000 // 28))

    def test_with_a_pin_showing_and_changing_need_it(self):
        s = self.bot.SETTINGS
        s.set_pin("2468")
        self.addCleanup(s.set_pin, None)
        self.assertEqual(self.call("POST", "/money/currency", {"currency": "USD"})[0], 403)
        self.assertEqual(self.call("POST", "/money/currency", {"currency": "USD"}, pin="2468")[0], 200)
        self.assertIsNone(self.call("GET", "/money?show=1")[1]["today_budget"])  # no PIN sent: still masked
        self.assertFalse(self.call("GET", "/money?show=1")[1]["shown"])

    def test_bad_input_says_what_to_fix(self):
        self.assertEqual(self.call("POST", "/money/currency", {"currency": "dollars"})[1]["msg"], "Choose a currency.")
        self.assertEqual(self.call("POST", "/money/income", {"name": "", "amount": "5"})[1]["msg"], "Give it a name.")
        self.assertEqual(self.call("POST", "/money/bill", {"name": "Rent", "amount": "12", "day": 40})[1]["msg"], "Choose the day of the month it is charged.")
        self.assertEqual(self.call("POST", "/money/spent", {"amount": "zero"})[0], 400)
        self.assertEqual(self.call("POST", "/money/spent", {"amount": "5", "day": 20})[0], 400)  # a day after today
        out = self.call("POST", "/money/spent", {"amount": "5", "note": "Coffee"})[1]
        self.assertEqual(len(out["spent"]), 1)
        self.assertEqual(len(self.call("POST", "/money/spent/delete", {"id": out["spent"][0]["id"]})[1]["spent"]), 0)


if __name__ == "__main__":
    unittest.main()
