"""Task history: search, older tasks on the board, and the Markdown report (dashboard and CLI).

Run: python -m unittest discover -s tests
"""
import io
import os
import sys
import unittest
import urllib.request
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import test_dashboard as td  # noqa: E402
from babd.team import Agent  # noqa: E402


class HistoryTest(unittest.TestCase):
    setUp_dash = td.DashboardTest.setUp
    call = td.DashboardTest.call
    wait = td.DashboardTest.wait

    def setUp(self):
        self.setUp_dash()
        self.call("PUT", "/api/project", {"require_approval": False})
        with mock.patch.object(Agent, "ask", td.scripted_ask):
            self.call("POST", "/api/tasks", {"goals": ["Login page with lockout", "CSV export for reports",
                                                       "Dark mode settings"]})
            self.wait(self.idle, timeout=30)

    def idle(self):
        with self.dash.tasks_lock:
            return not self.dash.active and not self.dash.queue

    def test_search(self):
        found = self.call("GET", "/api/search?q=csv%20reports")[1]["tasks"]
        self.assertEqual([t["goal"] for t in found], ["CSV export for reports"])
        self.assertEqual(len(self.call("GET", "/api/search?q=")[1]["tasks"]), 3)
        self.assertEqual(self.call("GET", "/api/search?q=nothing-like-this")[1]["tasks"], [])
        self.assertEqual(len(self.call("GET", "/api/search?status=done")[1]["tasks"]), 3)

    def test_board_history_limit(self):
        self.assertEqual(len(self.call("GET", "/api/board?history=2")[1]["tasks"]), 2)
        self.assertEqual(len(self.call("GET", "/api/board")[1]["tasks"]), 3)

    def test_markdown_report(self):
        run = self.call("GET", "/api/search?q=login")[1]["tasks"][0]
        req = urllib.request.Request(f"{self.base}/api/runs/{run['id']}/report.md", headers={"X-BABD-Token": td.TOKEN})
        with urllib.request.urlopen(req, timeout=10) as r:
            self.assertTrue(r.headers["Content-Type"].startswith("text/markdown"))
            self.assertIn(f'filename="babd-{run["id"]}.md"', r.headers["Content-Disposition"])
            md = r.read().decode()
        self.assertTrue(md.startswith("# Login page with lockout"))
        for part in ("**DONE**", "| QA verdict | PASS |", "## Report to the CEO", "## Steps", "## Conversation",
                     "### Architect → Team Lead · design", "| Deployed | yes |"):
            self.assertIn(part, md)
        self.assertEqual(self.call("GET", "/api/runs/nope/report.md")[0], 404)

    def test_cli_report(self):
        from babd import __main__ as cli
        run = self.call("GET", "/api/search?q=dark")[1]["tasks"][0]
        out = os.path.join(self.tmp, "r.md")
        with mock.patch.object(cli, "load_config", lambda: td.json.loads(td.read(self.cfg_path))), \
                mock.patch("sys.stdout", new_callable=io.StringIO):
            self.assertEqual(cli.main(["report", run["id"], "-o", out]), 0)
        self.assertTrue(td.read(out).startswith("# Dark mode settings"))


if __name__ == "__main__":
    unittest.main()
