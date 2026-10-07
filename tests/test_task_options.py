"""Per-task options: leave out the Architect, DevOps or the parallel preparation, and use another
model for an agent in one task (flow, dashboard API, CLI).

Run: python -m unittest discover -s tests
"""
import copy
import io
import os
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import test_dashboard as td  # noqa: E402
from babd import flow  # noqa: E402
from babd.config import load_config  # noqa: E402
from babd.harness.others import Direct  # noqa: E402
from babd.team import Agent, Team  # noqa: E402

FIXTURE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures", "agents.json")


class OptionsTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        p = mock.patch.object(flow, "RUNS_DIR", os.path.join(self.tmp, "runs"))
        p.start()
        self.addCleanup(p.stop)
        self.cfg = copy.deepcopy(load_config(FIXTURE))
        self.cfg["project"].update(gbrain={"enabled": False}, superpowers={"enabled": False}, mattpocock={"enabled": False},
                                   parallel_prep=True, require_approval=["deploy"])
        for a in self.cfg["agents"]:
            a["harness"] = {"type": "direct"}
            a["llm"]["api_key"] = "test"
        self.prompts = []

    def run_with(self, options, approver=lambda r: (True, "")):
        def ask(agent, prompt, **kw):
            self.prompts.append((agent.id, prompt))
            return td.scripted_ask(agent, prompt, **kw)
        with mock.patch.object(Agent, "ask", ask):
            return flow.Run(Team(self.cfg, log=lambda m: None), "Fix the typo", approver=approver, options=options).execute()

    def test_validation(self):
        self.assertEqual(flow.task_options(None), {"skip": [], "models": {}})
        self.assertEqual(flow.task_options({"skip": ["devops", "devops"], "models": {"qa": " m ", "dev": ""}}),
                         {"skip": ["devops"], "models": {"qa": "m"}})
        with self.assertRaisesRegex(flow.FlowError, "cannot skip qa"):
            flow.task_options({"skip": ["qa"]})
        with self.assertRaisesRegex(flow.FlowError, "no agent"):
            flow.task_options({"models": {"nobody": "m"}}, {"qa"})

    def test_quick_change_without_architect_and_devops(self):
        asked = []
        state = self.run_with({"skip": ["architect", "devops"]}, approver=lambda r: (asked.append(r), (True, ""))[1])
        self.assertEqual(state["status"], "done", state["error"])
        agents = {a for a, _ in self.prompts}
        self.assertEqual(agents, {"lead", "developer", "qa"})
        self.assertEqual(asked, [])  # no deploy, so no deploy approval
        self.assertEqual((state["stages"]["design"], state["stages"]["deploy"]), ("skipped", "skipped"))
        self.assertEqual((state["report"]["status"], state["report"]["progress"]), ("DONE", 100))
        self.assertFalse(state["deployed"])
        plan = [p for a, p in self.prompts if a == "lead"][0]
        self.assertIn("There is no Architect on this task", plan)
        self.assertNotIn('"architect": "<task>"', plan)
        dev = [p for a, p in self.prompts if a == "developer"][0]
        self.assertIn("No Architect on this task: follow the Team Lead's plan", dev)

    def test_no_parallel_prep(self):
        self.run_with({"skip": ["prep"]})
        self.assertFalse(any("Prepare the tests first" in p for _, p in self.prompts))

    def test_models_for_one_task(self):
        seen = {}

        def complete(harness, system, messages, **kw):
            seen[harness.agent_id] = harness.llm["model"]
            agent = type("A", (), {"id": harness.agent_id})()
            return td.scripted_ask(agent, messages[-1]["content"])
        cfg = flow.apply_models(self.cfg, {"developer": "cheap-coder"})
        self.assertNotEqual(self.cfg["agents"][2]["llm"]["model"], "cheap-coder")  # the config itself is untouched
        with mock.patch.object(Direct, "complete", complete):
            flow.Run(Team(cfg, log=lambda m: None), "x", approver=lambda r: (True, "")).execute()
        self.assertEqual(seen["developer"], "cheap-coder")
        self.assertNotEqual(seen["qa"], "cheap-coder")


class OptionsApiTest(unittest.TestCase):
    setUp = td.DashboardTest.setUp
    call = td.DashboardTest.call
    wait = td.DashboardTest.wait

    def idle(self):
        with self.dash.tasks_lock:
            return not self.dash.active and not self.dash.queue

    def test_options_through_the_api(self):
        seen = {}

        def complete(harness, system, messages, **kw):
            seen.setdefault(harness.agent_id, harness.llm["model"])
            agent = type("A", (), {"id": harness.agent_id})()
            return td.scripted_ask(agent, messages[-1]["content"])
        with mock.patch.object(Direct, "complete", complete), \
                mock.patch.dict(os.environ, {"ANTHROPIC_API_KEY": "k", "LOCAL_LLM_API_KEY": "k"}):
            status, run = self.call("POST", "/api/runs", {"goal": "Typo", "options": {"skip": ["architect", "devops"],
                                                                                      "models": {"qa": "tiny-qa"}}})
            self.assertEqual(status, 200, run)
            self.wait(self.idle, timeout=20)
        self.assertEqual(seen["qa"], "tiny-qa")
        self.assertNotIn("architect", seen)
        _, r = self.call("GET", f"/api/runs/{run['id']}")
        self.assertEqual(r["task_options"], {"skip": ["architect", "devops"], "models": {"qa": "tiny-qa"}})
        self.assertEqual(self.call("POST", "/api/runs", {"goal": "x", "options": {"skip": ["qa"]}})[0], 400)
        self.assertEqual(self.call("POST", "/api/runs", {"goal": "x", "options": {"models": {"ghost": "m"}}})[0], 400)

    def test_cli_flags(self):
        from babd import __main__ as cli
        cfg = td.json.loads(td.read(self.cfg_path))
        cfg["project"]["require_approval"] = []
        with mock.patch.object(cli, "load_config", lambda: cfg), mock.patch.object(Agent, "ask", td.scripted_ask), \
                mock.patch("sys.stdout", new_callable=io.StringIO), mock.patch("sys.stderr", new_callable=io.StringIO) as err:
            self.assertEqual(cli.main(["run", "Typo", "--skip", "architect,devops", "--model", "qa=tiny"]), 0)
            self.assertEqual(cli.main(["run", "Typo", "--skip", "qa"]), 2)
        self.assertIn("cannot skip qa", err.getvalue())


if __name__ == "__main__":
    unittest.main()
