"""Token and cost tracking: per call, step, agent, task and day; task and daily budgets; lean skills.

Run: python -m unittest discover -s tests
"""
import copy
import json
import os
import sys
import tempfile
import time
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import test_dashboard as td  # noqa: E402
from babd import flow, skillpacks  # noqa: E402
from babd.config import load_config  # noqa: E402
from babd.harness.others import ClaudeCode, Direct  # noqa: E402
from babd.team import Team  # noqa: E402

FIXTURE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures", "agents.json")


def reporting_complete(harness, system, messages, **kw):
    """Direct API stand-in that reports 1000 input / 200 output tokens per call."""
    harness.record_usage({"input": 1000, "output": 200})
    agent = type("A", (), {"id": harness.agent_id})()
    return td.scripted_ask(agent, messages[-1]["content"])


def silent_complete(harness, system, messages, **kw):
    """A tool that reports no token counts (like Hermes): BABD estimates them."""
    agent = type("A", (), {"id": harness.agent_id})()
    return td.scripted_ask(agent, messages[-1]["content"])


class UsageTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        p = mock.patch.object(flow, "RUNS_DIR", os.path.join(self.tmp, "runs"))
        p.start()
        self.addCleanup(p.stop)
        self.cfg = copy.deepcopy(load_config(FIXTURE))
        self.cfg["project"].update(gbrain={"enabled": False}, superpowers={"enabled": False}, mattpocock={"enabled": False},
                                   parallel_prep=False, require_approval=[])
        for a in self.cfg["agents"]:
            a["harness"] = {"type": "direct"}
            a["llm"]["api_key"] = "test"

    def run_with(self, complete):
        with mock.patch.object(Direct, "complete", complete):
            return flow.Run(Team(self.cfg, log=lambda m: None), "Build login").execute()

    def test_reported_tokens_and_prices(self):
        for a in self.cfg["agents"]:
            a["llm"]["price"] = {"input": 3, "output": 15}  # USD per million tokens
        state = self.run_with(reporting_complete)
        self.assertEqual(state["status"], "done", state["error"])
        calls = len(state["steps"])
        u = state["usage"]
        self.assertEqual((u["input"], u["output"], u["calls"]), (1000 * calls, 200 * calls, calls))
        self.assertAlmostEqual(u["cost"], calls * (1000 * 3 + 200 * 15) / 1e6)
        self.assertNotIn("estimated", u)
        self.assertEqual(u["by_agent"]["lead"]["calls"], 2)  # plan + report
        self.assertEqual(state["steps"][0]["usage"]["input"], 1000)

    def test_estimated_when_the_tool_does_not_say(self):
        state = self.run_with(silent_complete)
        self.assertTrue(state["usage"]["estimated"])
        self.assertTrue(state["usage"]["cost_unknown"])  # no price set
        self.assertGreater(state["usage"]["input"], 100)

    def test_task_budget_stops_the_task(self):
        self.cfg["project"]["budget"] = {"tokens_per_task": 2500}
        state = self.run_with(reporting_complete)
        self.assertEqual(state["status"], "failed")
        self.assertIn("task budget reached", state["error"])
        self.assertEqual(len(state["steps"]), 3)  # 1200 + 1200 + 1200 >= 2500 stops the 4th

    def test_claude_code_usage(self):
        dev = copy.deepcopy(self.cfg["agents"][2])
        dev["harness"] = {"type": "claude_local", "config_dir": os.path.join(self.tmp, "c")}
        h = ClaudeCode(dev)
        out = json.dumps({"result": "done", "usage": {"input_tokens": 10, "cache_read_input_tokens": 90, "output_tokens": 5},
                          "total_cost_usd": 0.0123})
        with mock.patch.object(ClaudeCode, "command_path", lambda self: "/bin/claude"), \
                mock.patch.object(ClaudeCode, "run_process", lambda self, *a, **k: out):
            self.assertEqual(h.complete("s", [{"role": "user", "content": "x"}]), "done")
        self.assertEqual(h.take_usage(), {"input": 100, "output": 5, "cost": 0.0123})

    def test_lean_skills(self):
        names = ["brainstorming", "writing-plans", "to-spec"]
        full, lean = skillpacks.step_block(names), skillpacks.step_block(names, lean=True)
        self.assertLess(len(lean), len(full) / 2)
        self.assertIn("[... the rest of this skill is in skills/superpowers/brainstorming/SKILL.md]", lean)
        self.assertIn("Skills applied:", lean)


class DailyBudgetTest(unittest.TestCase):
    setUp = td.DashboardTest.setUp
    call = td.DashboardTest.call

    def test_daily_budget_holds_the_queue(self):
        today = os.path.join(flow.RUNS_DIR, time.strftime("%Y%m%d") + "-000001")
        os.makedirs(today)
        with open(os.path.join(today, "state.json"), "w") as f:
            json.dump({"id": os.path.basename(today), "goal": "earlier", "status": "done",
                       "usage": {"input": 900_000, "output": 200_000, "cost": 4.5}}, f)
        self.call("PUT", "/api/project", {"budget": {"tokens_per_day": 1_000_000}})
        status, task = self.call("POST", "/api/runs", {"goal": "One more"})
        self.assertEqual((status, task["status"]), (200, "queued"))
        _, board = self.call("GET", "/api/board")
        self.assertIn("daily budget reached", board["budget_block"])
        self.assertEqual(board["usage_today"]["input"] + board["usage_today"]["output"], 1_100_000)
        self.call("PUT", "/api/project", {"budget": {"tokens_per_day": 0}})  # lifting the budget starts it
        with self.dash.tasks_lock:
            self.assertFalse(self.dash.queue)
        self.dash.cancel_run(task["id"])


if __name__ == "__main__":
    unittest.main()
