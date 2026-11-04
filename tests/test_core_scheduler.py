import unittest
from datetime import datetime
from zoneinfo import ZoneInfo

import harness  # noqa: F401
from core import scheduler as S

LON = ZoneInfo("Europe/London")


def at(h, m=0, day=3, tz=LON, sec=0):
    return datetime(2026, 11, day, h, m, sec, tzinfo=tz)  # 3 Nov 2026 is a Tuesday


class SchedulerTests(unittest.TestCase):
    def setUp(self):
        self.ran, self.logs = [], []
        self.s = S.Scheduler("Europe/London", log=self.logs.append)

    def job(self, name, **kw):
        return self.s.add(S.Job(name, lambda: self.ran.append(name), **kw))

    def test_runs_once_at_its_time(self):
        self.job("brief", at=[(7, 0)])
        self.assertEqual(self.s.tick(at(6, 59), wait=True), [])
        self.assertEqual(self.s.tick(at(7, 0), wait=True), ["brief"])
        self.assertEqual(self.s.tick(at(7, 1), wait=True), [])
        self.assertEqual(self.s.tick(at(7, 0, day=4), wait=True), ["brief"])

    def test_catch_up_after_being_off(self):
        self.job("brief", at=[(7, 0)])
        self.assertEqual(self.s.tick(at(9, 30), wait=True), ["brief"])
        self.job("exact", at=[(7, 0)], catch_up=False)
        self.assertEqual(self.s.tick(at(9, 30), wait=True), [])

    def test_weekdays(self):
        self.job("weekly", at=[(8, 0)], weekdays=[2])  # Wednesday
        self.assertEqual(self.s.tick(at(8, 0), wait=True), [])
        self.assertEqual(self.s.tick(at(8, 0, day=4), wait=True), ["weekly"])

    def test_uses_the_users_timezone(self):
        self.job("brief", at=[(7, 0)])
        utc_seven = datetime(2026, 11, 3, 7, 0, tzinfo=ZoneInfo("UTC"))  # 7 AM in London in November, same as UTC
        self.assertEqual(self.s.tick(utc_seven.astimezone(LON), wait=True), ["brief"])
        s2 = S.Scheduler("Asia/Tokyo")
        s2.add(S.Job("b", lambda: None, at=[(7, 0)], catch_up=False))
        self.assertEqual(s2.tick(utc_seven, wait=True), [])  # 4 PM in Tokyo

    def test_every_n_seconds(self):
        self.job("warm", every=60)
        self.assertEqual(self.s.tick(at(7, 0), wait=True), ["warm"])
        self.assertEqual(self.s.tick(at(7, 0, sec=30), wait=True), [])
        self.assertEqual(self.s.tick(at(7, 1, sec=1), wait=True), ["warm"])

    def test_failing_job_is_contained(self):
        self.s.add(S.Job("bad", lambda: 1 / 0, at=[(7, 0)]))
        self.job("good", at=[(7, 0)])
        self.s.tick(at(7, 0), wait=True)
        self.assertEqual(self.ran, ["good"])
        self.assertIn("job bad failed", self.logs[0])

    def test_descriptions_are_12_hour(self):
        self.assertEqual(S.show_time(0, 5), "12:05 AM")
        self.assertEqual(S.show_time(12, 0), "12:00 PM")
        self.assertEqual(S.show_time(21, 30), "9:30 PM")
        self.job("brief", at=[(7, 0), (19, 30)])
        self.job("weekly", at=[(8, 0)], weekdays=[2, 6])
        self.assertEqual(self.s.describe(), ["brief: every day at 7:00 AM and 7:30 PM", "weekly: on Wednesday, Sunday at 8:00 AM"])

    def test_needs_at_or_every(self):
        with self.assertRaises(ValueError):
            S.Job("x", lambda: None)


if __name__ == "__main__":
    unittest.main()
