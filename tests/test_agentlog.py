"""Each agent's activity log: written from the run's events, read newest first through the API,
filtered by type and words; saved tasks no process runs any more never show steps as running.

Run: python -m unittest discover -s tests
"""
import json
import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import test_dashboard as td  # noqa: E402
from babd import agentlog, flow  # noqa: E402
from babd.dashboard import server  # noqa: E402
from babd.team import Agent  # noqa: E402


class AgentLogTest(unittest.TestCase):
    setUp = td.DashboardTest.setUp
    call = td.DashboardTest.call
    wait = td.DashboardTest.wait

    def test_a_task_fills_every_agents_log(self):
        self.call("PUT", "/api/project", {"require_approval": []})
        with mock.patch.object(Agent, "ask", td.scripted_ask):
            _, run = self.call("POST", "/api/runs", {"goal": "Build login"})
            self.wait(lambda: run["id"] not in self.dash.active, timeout=20)
        status, out = self.call("GET", "/api/agents/developer/log")
        self.assertEqual(status, 200)
        entries = out["entries"]
        self.assertTrue(entries)
        self.assertEqual(entries, sorted(entries, key=lambda e: -e["seq"]))  # newest first
        texts = [e["text"] for e in entries]
        self.assertTrue(any(t.startswith("started code") for t in texts), texts)
        self.assertTrue(any(t.startswith("finished code") for t in texts), texts)
        self.assertTrue(any(t.startswith("from ") and e["dir"] == "in" for t, e in zip(texts, entries) if e["type"] == "message"))
        got = [e for e in entries if e["type"] == "message" and e["dir"] == "out"]
        self.assertEqual(got[0]["detail"], "developer output")
        self.assertTrue(all(e["run"] == run["id"] and e["goal"] == "Build login" for e in entries))
        _, only = self.call("GET", "/api/agents/developer/log?type=step")
        self.assertEqual({e["type"] for e in only["entries"]}, {"step"})
        _, found = self.call("GET", "/api/agents/qa/log?q=VERDICT")
        self.assertTrue(found["entries"])
        _, older = self.call("GET", f"/api/agents/developer/log?before={entries[1]['seq']}&limit=1")
        self.assertEqual(older["entries"][0]["seq"], entries[2]["seq"])
        _, summary = self.call("GET", "/api/agentlogs")
        self.assertTrue(summary["agents"]["lead"]["last_text"])
        self.assertEqual(self.call("GET", "/api/agents/nobody/log")[0], 404)

    def test_entries_for_events(self):
        names = {"lead": "Team Lead", "qa": "QA"}
        out = agentlog.entries_for("message", {"from": "lead", "to": "qa", "kind": "assign", "content": "x" * 10}, names)
        self.assertEqual([(a, e["dir"]) for a, e in out], [("qa", "in"), ("lead", "out")])
        self.assertEqual(agentlog.entries_for("message", {"from": "lead", "to": "ceo", "kind": "report", "content": ""})[0][0], "lead")
        retry = agentlog.entries_for("retry", {"agent": "qa", "attempt": 1, "of": 3, "wait": 2, "error": "503"})
        self.assertEqual(retry[0][1]["detail"], "503")
        self.assertEqual(agentlog.entries_for("stage", {"stage": "plan"}), [])

    def test_settle_saved_tasks(self):
        s = {"id": "r1", "status": "running", "pid": 999999, "finished_at": "2026-01-01T10:05:00",
             "steps": [{"status": "working", "started_at": "2026-01-01T10:00:00"}, {"status": "queued", "queued_at": "2026-01-01T10:01:00"}]}
        with mock.patch.object(server, "_alive", lambda pid: False):
            server.settle(s)
        self.assertEqual(s["status"], "interrupted")
        self.assertEqual([st["status"] for st in s["steps"]], ["interrupted", "interrupted"])
        self.assertEqual(s["steps"][0]["finished_at"], "2026-01-01T10:05:00")
        live = {"id": "r2", "status": "running", "pid": os.getpid(), "steps": [{"status": "working"}]}
        server.settle(live, active={"r2"})
        self.assertEqual((live["status"], live["steps"][0]["status"]), ("running", "working"))


if __name__ == "__main__":
    unittest.main()
