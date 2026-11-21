"""The Schedule page: every timed job can be turned off, times are yours, and only those paths can be changed here."""
import unittest

import harness
from harness import load_bot


class Schedule(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.bot = load_bot()

    def setUp(self):
        self.addCleanup(self.bot.SETTINGS.reset)
        self.base = harness.start_api(self.bot)[1]

    def jobs(self):
        return {j["id"]: j for j in harness.call(self.base, "GET", "/schedule")[1]["jobs"]}

    def test_every_job_is_listed_with_a_switch_and_backups_start_off(self):
        j = self.jobs()
        self.assertEqual(set(j), {"briefing", "news", "evening", "journal", "insights", "weekly", "recap", "backup", "offsite", "github"})
        self.assertTrue(all(x["switch"] for x in j.values()))
        self.assertFalse(j["backup"]["on"])
        self.assertFalse(j["github"]["on"])
        self.assertEqual(j["weekly"]["every"], "Sundays at 10:00 AM")
        self.assertFalse(j["offsite"]["on"])
        self.assertEqual(j["offsite"]["every"], "Every day at 4:00 AM")

    def test_the_off_site_copy_says_how_to_set_it_up_until_it_is(self):
        import os
        from core import offsite
        self.assertIn("offsite setup", self.jobs()["offsite"]["blocked"])
        offsite.write(self.bot.DATA, where="b2:alex-bucket:homelab", set_up=1)
        self.addCleanup(os.remove, os.path.join(self.bot.DATA, offsite.STATE))
        self.assertNotIn("offsite setup", self.jobs()["offsite"]["blocked"])
        self.assertEqual(harness.call(self.base, "POST", "/schedule", {"set": {"night.offsite": True, "night.offsite_at": "2:15 AM"}})[0], 200)
        self.assertEqual(self.jobs()["offsite"]["at"], "2:15 AM")

    def test_turning_off_and_moving_a_job(self):
        code, out = harness.call(self.base, "POST", "/schedule", {"set": {"night.journal_at": "5:15 AM", "schedule.evening_on": False, "night.backup": True}})
        self.assertEqual(code, 200, out)
        j = self.jobs()
        self.assertEqual((j["journal"]["at"], j["insights"]["at"]), ("5:15 AM", "5:45 AM"))
        self.assertFalse(j["evening"]["on"])
        self.assertTrue(j["backup"]["on"])
        self.assertEqual(harness.call(self.base, "POST", "/schedule", {"set": {"owner.name": "X"}})[0], 400)  # not a schedule setting
        self.assertEqual(harness.call(self.base, "POST", "/schedule", {"set": {"night.journal_at": "soon"}})[0], 400)


if __name__ == "__main__":
    unittest.main()
