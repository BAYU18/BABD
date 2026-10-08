"""Scheduled tasks: cron parsing and short forms, each schedule starts once per matching minute,
the dashboard API, run now, on / off.

Run: python -m unittest discover -s tests
"""
import datetime
import os
import shutil
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import test_dashboard as td  # noqa: E402
from babd import schedules  # noqa: E402
from babd.team import Agent  # noqa: E402

MON_7 = datetime.datetime(2026, 10, 12, 7, 0)  # a Monday


class CronTest(unittest.TestCase):
    def test_short_forms(self):
        self.assertEqual(schedules.expand("daily 07:00"), "0 7 * * *")
        self.assertEqual(schedules.expand("Daily 7:05"), "5 7 * * *")
        self.assertEqual(schedules.expand("hourly"), "0 * * * *")
        self.assertEqual(schedules.expand("weekly mon,fri 08:30"), "30 8 * * mon,fri")
        self.assertEqual(schedules.expand("monthly 1 06:00"), "0 6 1 * *")
        self.assertEqual(schedules.expand("cron */5 * * * *"), "*/5 * * * *")

    def test_matching(self):
        m = schedules.matches
        self.assertTrue(m("0 7 * * *", MON_7))
        self.assertTrue(m("0 7 * * mon", MON_7))
        self.assertFalse(m("0 7 * * sun", MON_7))
        self.assertTrue(m("0 7 * * 1-5", MON_7))
        self.assertTrue(m("*/15 * * * *", MON_7))
        self.assertFalse(m("1 7 * * *", MON_7))
        self.assertTrue(m("0 7 12 * *", MON_7))
        self.assertTrue(m("0 7 1 * mon", MON_7))  # day of month OR day of week, like cron
        self.assertTrue(m("0 7 * * 7", datetime.datetime(2026, 10, 11, 7, 0)))  # 7 = Sunday too
        self.assertEqual(schedules.next_run("daily 07:00", MON_7), MON_7 + datetime.timedelta(days=1))
        self.assertEqual(schedules.next_run("weekly fri 09:00", MON_7), datetime.datetime(2026, 10, 16, 9, 0))

    def test_errors(self):
        for bad in ("", "every day", "61 * * * *", "0 25 * * *", "0 7 * * funday", "*/0 * * * *", "0 7 * *"):
            with self.assertRaises(schedules.ScheduleError, msg=bad):
                schedules.parse(bad)
        with self.assertRaises(schedules.ScheduleError):
            schedules.normalize({"goal": "", "cron": "hourly"})
        with self.assertRaises(schedules.ScheduleError):
            schedules.normalize({"goal": "x", "cron": "hourly", "mode": "turbo"})
        self.assertEqual(schedules.describe("0 7 * * *"), "every day at 07:00")

    def test_once_per_minute(self):
        tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, tmp, True)
        book = schedules.Book(os.path.join(tmp, "s.json"))
        cfg = {"schedules": [{"id": "a", "goal": "check", "cron": "0 7 * * *"},
                             {"id": "b", "goal": "off", "cron": "0 7 * * *", "enabled": False}]}
        self.assertEqual([s["id"] for s in schedules.due(cfg, book, MON_7)], ["a"])
        self.assertEqual(schedules.due(cfg, book, MON_7 + datetime.timedelta(seconds=30)), [])  # same minute
        self.assertEqual(schedules.due(cfg, book, MON_7 + datetime.timedelta(minutes=1)), [])
        self.assertEqual(len(schedules.due(cfg, book, MON_7 + datetime.timedelta(days=1))), 1)


class ScheduleApiTest(unittest.TestCase):
    setUp = td.DashboardTest.setUp
    call = td.DashboardTest.call
    wait = td.DashboardTest.wait

    def test_schedules_start_tasks(self):
        status, out = self.call("PUT", "/api/schedules", {"schedules": [
            {"goal": "cek disk server lpnotif", "cron": "daily 07:00"}]})
        self.assertEqual(status, 200, out)
        sc = out["schedules"][0]
        self.assertEqual((sc["id"], sc["cron"], sc["mode"], sc["when"]), ("cek-disk-server-lpnotif", "0 7 * * *", "quick", "every day at 07:00"))
        self.assertTrue(sc["next"])
        self.assertEqual(self.call("PUT", "/api/schedules", {"schedules": [{"goal": "x", "cron": "sometimes"}]})[0], 400)
        self.assertEqual(self.call("PUT", "/api/schedules", {"schedules": [{"goal": "x", "cron": "hourly", "project": "nope"}]})[0], 400)
        with mock.patch.object(Agent, "ask", td.scripted_ask):
            started = self.dash.schedule_tick(MON_7)
            self.assertEqual(len(started), 1)
            self.assertEqual(self.dash.schedule_tick(MON_7), [])  # once per minute
            self.wait(lambda: not self.dash.active, timeout=20)
            _, r = self.call("GET", f"/api/runs/{started[0]['id']}")
            self.assertEqual(r["task_options"]["mode"], "quick")
            status, task = self.call("POST", "/api/schedules/cek-disk-server-lpnotif/run")
            self.assertEqual(status, 200, task)
            self.wait(lambda: not self.dash.active, timeout=20)
        _, out = self.call("POST", "/api/schedules/cek-disk-server-lpnotif/off")
        self.assertFalse(out["enabled"])
        self.assertEqual(self.dash.schedule_tick(MON_7 + datetime.timedelta(days=1)), [])
        _, state = self.call("GET", "/api/state")
        self.assertEqual(state["schedules"][0]["task"], task["id"])


if __name__ == "__main__":
    unittest.main()
