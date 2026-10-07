"""Team flow tests with scripted agents: who talks to whom, in which order, and what happens on
QA failures, CEO approval / rejection, agent errors and cancellation.

Run: python -m unittest discover -s tests
"""
import copy
import json
import os
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from babd import flow  # noqa: E402
from babd.config import load_config  # noqa: E402
from babd.flow import FlowError, MessageBus, parse_verdict  # noqa: E402
from babd.team import Team, apply_run_to_config  # noqa: E402

PLAN = {"plan_summary": "Build login.", "assignments": {
    "architect": "Design auth", "developer": "Write auth code", "qa": "Test auth", "devops": "Ship auth"}}
REPORT = {"current_goal": "Ship Login", "active_task": "Deploy", "recent_result": "Login Live",
          "next_action": "Monitor", "summary": "Login shipped.", "status": "BOGUS", "progress": 3}


class Script:
    """Replies per agent; QA verdicts come from `verdicts` in order."""

    def __init__(self, verdicts=("PASS",), fail_agent=None):
        self.verdicts = list(verdicts)
        self.fail_agent = fail_agent
        self.prompts = []

    def responder(self, agent_id):
        def ask(prompt, **kw):
            self.prompts.append((agent_id, prompt))
            if agent_id == self.fail_agent:
                raise RuntimeError(f"{agent_id} harness crashed")
            if agent_id == "lead":
                return json.dumps(PLAN) if '"assignments"' in prompt else json.dumps(REPORT)
            if agent_id == "qa":
                return f"bugs: none\nVERDICT: {self.verdicts.pop(0)}"
            return f"{agent_id} output"
        return ask


class FlowTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        p = mock.patch.object(flow, "RUNS_DIR", self.tmp)
        p.start()
        self.addCleanup(p.stop)
        self.cfg = copy.deepcopy(load_config())
        self.cfg["project"]["gbrain"] = {"enabled": False}  # memory is covered in test_gbrain.py
        self.cfg["project"]["superpowers"] = {"enabled": False}  # covered in test_superpowers.py
        self.cfg["project"]["mattpocock"] = {"enabled": False}  # covered in test_mattpocock.py
        for a in self.cfg["agents"]:
            a["harness"] = {"type": "direct"}
            a["llm"]["api_key"] = "test"
        self.events = []

    def run_team(self, script, approver=lambda req: (True, "go"), project=None):
        self.cfg["project"].update(project or {})
        team = Team(self.cfg, log=lambda m: None)
        for a in team.agents:
            a.ask = script.responder(a.id)
        return team.run("Build login", approver=approver, on_event=lambda k, d: self.events.append((k, d)))

    def route(self, state):
        return [(m["from"], m["to"], m["kind"]) for m in state["messages"]]

    def test_happy_path_order(self):
        state = self.run_team(Script())
        self.assertEqual(state["status"], "done")
        self.assertEqual(self.route(state), [
            ("ceo", "lead", "goal"),
            ("lead", "architect", "assign"), ("architect", "lead", "design"),
            ("lead", "developer", "assign"), ("developer", "lead", "code"),
            ("lead", "qa", "assign"), ("qa", "lead", "test_report"),
            ("lead", "ceo", "approval_request"), ("ceo", "lead", "approval"),
            ("lead", "devops", "assign"), ("devops", "lead", "deploy_report"),
            ("lead", "ceo", "report"),
        ])
        rep = state["report"]
        # numbers come from what happened, not from the model (which said BOGUS / 3)
        self.assertEqual((rep["status"], rep["progress"], rep["deployed"], rep["qa_verdict"]), ("DONE", 100, True, "PASS"))
        self.assertEqual(rep["next_action"], "Monitor")
        self.assertTrue(all(v in ("done",) for v in state["stages"].values()), state["stages"])

    def test_each_agent_receives_upstream_work(self):
        script = Script()
        self.run_team(script)
        prompts = dict((a, p) for a, p in script.prompts if a != "lead")
        self.assertIn("Write auth code", prompts["developer"])
        self.assertIn("architect output", prompts["developer"])
        self.assertIn("developer output", prompts["qa"])
        self.assertIn("VERDICT: PASS or VERDICT: FAIL", prompts["qa"])
        self.assertIn("QA verdict: PASS", prompts["devops"])

    def test_qa_fail_goes_back_to_developer(self):
        state = self.run_team(Script(verdicts=("FAIL", "PASS")))
        route = self.route(state)
        i = route.index(("qa", "lead", "test_report"))
        self.assertEqual(route[i + 1:i + 5], [("lead", "developer", "fix_request"), ("developer", "lead", "fix"),
                                              ("lead", "qa", "retest"), ("qa", "lead", "test_report")])
        self.assertEqual(state["report"]["fix_rounds"], 1)
        self.assertTrue(state["deployed"])

    def test_qa_keeps_failing_blocks_deploy(self):
        state = self.run_team(Script(verdicts=("FAIL", "FAIL", "FAIL")), project={"max_fix_rounds": 2})
        kinds = [k for _, _, k in self.route(state)]
        self.assertEqual(kinds.count("fix_request"), 2)
        self.assertNotIn("approval_request", kinds)
        self.assertFalse(any(to == "devops" for _, to, _ in self.route(state)))
        rep = state["report"]
        self.assertEqual((rep["status"], rep["blockers"], rep["deployed"]), ("BLOCKED", 1, False))
        self.assertEqual(state["stages"]["test"], "failed")
        self.assertEqual(state["stages"]["deploy"], "skipped")
        self.assertEqual(state["agents"]["devops"]["status"], "waiting")

    def test_ceo_rejects_deploy(self):
        state = self.run_team(Script(), approver=lambda req: (False, "not before Friday"))
        self.assertNotIn(("lead", "devops", "assign"), self.route(state))
        self.assertEqual(state["approval"]["result"], "rejected")
        rep = state["report"]
        self.assertEqual((rep["status"], rep["approval_needed"], rep["blockers"]), ("BLOCKED", 1, 1))
        self.assertIn("not before Friday", rep["blocker_list"][0])

    def test_no_approver_means_approval_needed(self):
        state = self.run_team(Script(), approver=None)
        self.assertEqual(state["report"]["approval_needed"], 1)
        self.assertFalse(state["deployed"])

    def test_approval_can_be_switched_off(self):
        state = self.run_team(Script(), approver=None, project={"require_approval": []})
        self.assertTrue(state["deployed"])
        self.assertEqual(state["stages"]["approval"], "skipped")
        self.assertNotIn("approval_request", [k for _, _, k in self.route(state)])

    def test_agent_failure_fails_the_run(self):
        state = self.run_team(Script(fail_agent="developer"))
        self.assertEqual(state["status"], "failed")
        self.assertIn("developer harness crashed", state["error"])
        self.assertEqual(state["agents"]["developer"]["status"], "blocked")
        self.assertEqual(self.events[-1][0], "finished")

    def test_cancel(self):
        def approver(req):
            run_obj.cancelled.set()
            return True, ""
        team = Team(self.cfg, log=lambda m: None)
        script = Script()
        for a in team.agents:
            a.ask = script.responder(a.id)
        run_obj = flow.Run(team, "Build login", approver=approver)
        state = run_obj.execute()
        self.assertEqual(state["status"], "cancelled")
        self.assertFalse(state["deployed"])

    def test_routes_are_enforced(self):
        bus = MessageBus(lambda *a: None, self.tmp)
        with self.assertRaises(FlowError):
            bus.send("developer", "qa", "code", "x")   # specialists only talk to the Team Lead
        with self.assertRaises(FlowError):
            bus.send("devops", "ceo", "report", "x")   # only the Team Lead reports to the CEO
        bus.send("lead", "qa", "assign", "ok")

    def test_run_ids_are_unique(self):
        team = Team(self.cfg, log=lambda m: None)
        a, b = flow.Run(team, "x", run_id="same"), flow.Run(team, "y", run_id="same")
        self.assertNotEqual(a.dir, b.dir)

    def test_messages_and_state_saved(self):
        state = self.run_team(Script())
        with open(os.path.join(state["dir"], "messages.jsonl")) as f:
            self.assertEqual(len(f.readlines()), len(state["messages"]))
        with open(os.path.join(state["dir"], "state.json")) as f:
            self.assertEqual(json.load(f)["status"], "done")

    def test_parse_verdict(self):
        self.assertEqual(parse_verdict("ok\n**VERDICT: pass**"), "PASS")
        self.assertEqual(parse_verdict("VERDICT: PASS\nretest...\nVERDICT: FAIL"), "FAIL")
        self.assertEqual(parse_verdict("looks fine"), "FAIL")

    def test_apply_run_to_config(self):
        state = self.run_team(Script(verdicts=("FAIL", "FAIL", "FAIL")))
        cfg = apply_run_to_config(copy.deepcopy(self.cfg), state)
        steps = {s["step"]: s["state"] for s in cfg["workflow"]}
        self.assertEqual(steps, {"PLAN": "done", "DESIGN": "done", "CODE": "done", "TEST": "active",
                                 "DEPLOY": "todo", "MONITOR": "todo"})
        status = {a["id"]: a["status"] for a in cfg["agents"]}
        self.assertEqual(status["qa"], "blocked")
        self.assertEqual(status["devops"], "waiting")
        self.assertEqual(cfg["project"]["status"], "BLOCKED")


if __name__ == "__main__":
    unittest.main()
