"""Parallel work tests: agent slots, the parallel build step inside a run (Developer codes while QA
writes the test plan and DevOps prepares the deploy), many runs at once sharing the agents, and the
dashboard's task queue and task board.

Run: python -m unittest discover -s tests
"""
import copy
import json
import os
import sys
import tempfile
import threading
import time
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import test_dashboard as td  # noqa: E402
from babd import flow  # noqa: E402
from babd.config import load_config  # noqa: E402
from babd.flow import AgentSlots, FlowCancelled, Run  # noqa: E402
from babd.team import Agent, Team  # noqa: E402


def kind_of(prompt):
    if '"assignments"' in prompt and "Plan the work" in prompt:
        return "plan"
    if "Write the CEO report" in prompt:
        return "report"
    if "Prepare the tests first" in prompt:
        return "test_plan"
    if "Prepare the deployment" in prompt:
        return "deploy_prep"
    if "Deploy it and set up monitoring" in prompt:
        return "deploy_report"
    if "VERDICT" in prompt:
        return "test_report"
    if "### Design from" in prompt:
        return "code"
    return "design"


class Recorder:
    """Scripted agents that record how many steps each agent runs at the same time."""

    def __init__(self, hold=0.0, barrier=None, barrier_kinds=(), fail_kind=None):
        self.lock = threading.Lock()
        self.now, self.peak = {}, {}
        self.prompts = []
        self.hold, self.barrier, self.barrier_kinds, self.fail_kind = hold, barrier, barrier_kinds, fail_kind

    def __call__(self, agent, prompt, **kw):
        kind = kind_of(prompt)
        with self.lock:
            self.prompts.append((agent.id, kind, prompt))
            self.now[agent.id] = self.now.get(agent.id, 0) + 1
            self.peak[agent.id] = max(self.peak.get(agent.id, 0), self.now[agent.id])
        try:
            if self.barrier is not None and kind in self.barrier_kinds:
                self.barrier.wait()  # breaks (and fails the run) unless all these steps run at once
            time.sleep(self.hold)
            if kind == self.fail_kind:
                raise RuntimeError(f"{agent.id} broke on {kind}")
            if kind == "plan":
                return json.dumps({"plan_summary": "Plan.", "assignments": {}})
            if kind == "report":
                return json.dumps({"summary": "Done.", "next_action": "Monitor"})
            if kind == "test_report":
                return "All good.\nVERDICT: PASS"
            return f"{agent.id} {kind} output"
        finally:
            with self.lock:
                self.now[agent.id] -= 1


def base_cfg():
    cfg = copy.deepcopy(load_config())
    cfg["project"]["gbrain"] = {"enabled": False}
    cfg["project"]["superpowers"] = {"enabled": False}
    cfg["project"]["mattpocock"] = {"enabled": False}
    cfg["project"]["parallel_prep"] = True
    cfg["project"]["require_approval"] = []
    for a in cfg["agents"]:
        a["harness"] = {"type": "direct"}
        a["llm"]["api_key"] = "test"
    return cfg


class SlotsTest(unittest.TestCase):
    def test_capacity_and_waiting(self):
        slots = AgentSlots({"agents": [{"id": "dev", "parallel": 1}]})
        slots.acquire("dev")
        got = threading.Event()
        t = threading.Thread(target=lambda: (slots.acquire("dev"), got.set()))
        t.start()
        time.sleep(0.2)
        self.assertFalse(got.is_set())
        self.assertEqual(slots.load()["dev"], {"capacity": 1, "active": 1, "waiting": 1})
        slots.release("dev")
        self.assertTrue(got.wait(2))
        t.join()
        slots.release("dev")
        self.assertEqual(slots.load()["dev"]["active"], 0)

    def test_cancel_while_waiting(self):
        slots = AgentSlots({"agents": [{"id": "dev", "parallel": 1}]})
        slots.acquire("dev")
        cancelled = threading.Event()
        cancelled.set()
        with self.assertRaises(FlowCancelled):
            slots.acquire("dev", cancelled)
        self.assertEqual(slots.load()["dev"]["waiting"], 0)

    def test_parallel_setting_is_bounded(self):
        self.assertEqual(flow.parallel_of({"parallel": 99}), 8)
        self.assertEqual(flow.parallel_of({"parallel": 0}), 1)
        self.assertEqual(flow.parallel_of({"parallel": "x"}), flow.DEFAULT_PARALLEL)
        self.assertEqual(flow.parallel_of({}), flow.DEFAULT_PARALLEL)


class ParallelRunTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        p = mock.patch.object(flow, "RUNS_DIR", os.path.join(self.tmp, "runs"))
        p.start()
        self.addCleanup(p.stop)
        self.cfg = base_cfg()

    def run_with(self, rec, goal="Build login", slots=None, patch=True):
        if not patch:  # the caller patched Agent.ask once for every thread
            return Run(Team(self.cfg, log=lambda m: None), goal, slots=slots).execute()
        with mock.patch.object(Agent, "ask", lambda agent, prompt, **kw: rec(agent, prompt, **kw)):
            return Run(Team(self.cfg, log=lambda m: None), goal, slots=slots).execute()

    def test_build_step_runs_three_agents_at_once(self):
        rec = Recorder(barrier=threading.Barrier(3, timeout=5), barrier_kinds=("code", "test_plan", "deploy_prep"))
        state = self.run_with(rec)
        self.assertEqual(state["status"], "done", state["error"])
        kinds = [(m["from"], m["to"], m["kind"]) for m in state["messages"]]
        for k in [("lead", "qa", "prepare"), ("qa", "lead", "test_plan"), ("lead", "devops", "prepare"),
                  ("devops", "lead", "deploy_prep"), ("developer", "lead", "code")]:
            self.assertIn(k, kinds)
        self.assertEqual([m["seq"] for m in state["messages"]], list(range(1, len(state["messages"]) + 1)))
        test = [p for a, k, p in rec.prompts if k == "test_report"][0]
        self.assertIn("### Your test plan\nqa test_plan output", test)
        deploy = [p for a, k, p in rec.prompts if k == "deploy_report"][0]
        self.assertIn("### Your deploy preparation\ndevops deploy_prep output", deploy)
        steps = state["steps"]
        self.assertEqual([s["kind"] for s in steps][:2], ["plan", "design"])
        self.assertTrue(all(s["status"] == "done" and s["started_at"] and s["seconds"] is not None for s in steps))
        for name in ("03-developer.md", "03-qa-test-plan.md", "03-devops-prep.md"):
            self.assertTrue(os.path.exists(os.path.join(state["dir"], name)), name)

    def test_parallel_prep_off_is_sequential(self):
        self.cfg["project"]["parallel_prep"] = False
        rec = Recorder()
        state = self.run_with(rec)
        self.assertEqual(state["status"], "done")
        self.assertNotIn("test_plan", [k for _, k, _ in rec.prompts])

    def test_error_in_one_parallel_step_fails_the_run_after_the_others_finish(self):
        rec = Recorder(hold=0.2, fail_kind="deploy_prep")
        state = self.run_with(rec)
        self.assertEqual(state["status"], "failed")
        self.assertIn("devops broke on deploy_prep", state["error"])
        by = {(s["agent"], s["kind"]): s["status"] for s in state["steps"]}
        self.assertEqual(by[("developer", "code")], "done")
        self.assertEqual(by[("devops", "deploy_prep")], "failed")
        self.assertEqual(state["agents"]["devops"]["status"], "blocked")

    def test_two_runs_share_the_agents(self):
        for a in self.cfg["agents"]:
            a["parallel"] = 1 if a["id"] == "developer" else 2
        slots = AgentSlots(self.cfg)
        rec = Recorder(hold=0.15, barrier=threading.Barrier(2, timeout=5), barrier_kinds=("design",))
        states = []
        threads = [threading.Thread(target=lambda g=g: states.append(self.run_with(rec, g, slots, patch=False)))
                   for g in ("Task A", "Task B")]
        with mock.patch.object(Agent, "ask", lambda agent, prompt, **kw: rec(agent, prompt, **kw)):
            for t in threads:
                t.start()
            for t in threads:
                t.join(30)
        self.assertEqual(sorted(s["status"] for s in states), ["done", "done"], [(s["error"], [(x["agent"], x["kind"], x["status"]) for x in s["steps"]]) for s in states])
        self.assertEqual(rec.peak["architect"], 2)  # both designs at the same time (capacity 2)
        self.assertEqual(rec.peak["developer"], 1)  # capacity 1: one build at a time across both runs
        self.assertNotEqual(states[0]["id"], states[1]["id"])
        self.assertTrue(any(s["status"] == "done" for st in states for s in st["steps"] if s["agent"] == "developer"))

    def test_command_line_runs_several_goals(self):
        from babd import __main__ as cli
        rec = Recorder(barrier=threading.Barrier(2, timeout=5), barrier_kinds=("plan",))  # both plans at once
        with mock.patch.object(cli, "load_config", lambda: self.cfg), \
                mock.patch.object(Agent, "ask", lambda agent, prompt, **kw: rec(agent, prompt, **kw)), \
                mock.patch("sys.stdout", new_callable=lambda: __import__("io").StringIO()) as out, \
                mock.patch("sys.stderr", new_callable=lambda: __import__("io").StringIO()):
            code = cli.main(["run", "Task A", "Task B", "--approve"])
        self.assertEqual(code, 0)
        self.assertIn("##### [1] Task A", out.getvalue())
        self.assertIn("##### [2] Task B", out.getvalue())
        self.assertEqual(len(os.listdir(flow.RUNS_DIR)), 2)


class TaskBoardTest(unittest.TestCase):
    setUp = td.DashboardTest.setUp
    call = td.DashboardTest.call
    wait = td.DashboardTest.wait
    waiting = td.DashboardTest.waiting

    def idle(self):
        with self.dash.tasks_lock:
            return not self.dash.active and not self.dash.queue

    def slow_ask(self, gate):
        def ask(agent, prompt, **kw):
            if agent.id == "architect":
                gate.wait(10)
            return td.scripted_ask(agent, prompt, **kw)
        return ask

    def test_queue_respects_max_parallel_tasks(self):
        self.call("PUT", "/api/project", {"max_parallel_tasks": 1, "require_approval": False})
        gate = threading.Event()
        with mock.patch.object(Agent, "ask", self.slow_ask(gate)):
            _, first = self.call("POST", "/api/runs", {"goal": "First"})
            self.assertEqual(first["status"], "running")
            status, out = self.call("POST", "/api/tasks", {"goals": ["Second", " ", "Third"]})
            self.assertEqual(status, 200)
            second, third = out["tasks"]
            self.assertEqual((second["status"], second["position"]), ("queued", 1))
            self.assertEqual(third["position"], 2)
            _, board = self.call("GET", "/api/board")
            self.assertEqual(board["counts"], {"queued": 2, "running": 1})
            self.assertEqual(board["limits"]["max_parallel_tasks"], 1)
            self.assertEqual(self.call("POST", f"/api/runs/{third['id']}/cancel")[1]["note"], "removed from the queue")
            gate.set()
            self.wait(self.idle, timeout=20)
        _, board = self.call("GET", "/api/board")
        done = {t["goal"]: t for t in board["tasks"]}
        self.assertEqual(done["First"]["status"], "done")
        self.assertEqual(done["Second"]["status"], "done")
        self.assertNotIn("Third", done)
        self.assertLess(done["First"]["finished_at"], done["Second"]["started_at"] + "~")  # one after the other
        lead = [a for a in board["agents"] if a["id"] == "lead"][0]
        self.assertEqual(lead["done"], 4)  # plan + report, twice
        self.assertEqual(lead["working"], [])
        self.assertTrue(lead["avg_seconds"] is not None)

    def test_task_waiting_for_the_ceo_frees_its_slot(self):
        self.call("PUT", "/api/project", {"max_parallel_tasks": 1})
        gate = threading.Event()
        with mock.patch.object(Agent, "ask", self.slow_ask(gate)):
            _, first = self.call("POST", "/api/runs", {"goal": "First"})
            _, second = self.call("POST", "/api/runs", {"goal": "Second"})
            self.assertEqual(second["status"], "queued")
            gate.set()
            self.wait(lambda: self.waiting(first["id"]) and self.waiting(second["id"]), timeout=20)
            _, state = self.call("GET", "/api/state")
            self.assertEqual(sorted(r["status"] for r in state["active_runs"]), ["waiting_approval"] * 2)
            for r in (first, second):
                self.assertEqual(self.call("POST", f"/api/runs/{r['id']}/approve", {"approved": True})[0], 200)
            self.wait(self.idle, timeout=20)
        self.assertEqual({r["id"]: r["status"] for r in self.call("GET", "/api/state")[1]["runs"][:2]},
                         {first["id"]: "done", second["id"]: "done"})

    def test_bad_input(self):
        self.assertEqual(self.call("POST", "/api/tasks", {"goals": "one"})[0], 400)
        self.assertEqual(self.call("POST", "/api/tasks", {"goals": [" "]})[0], 400)
        self.assertEqual(self.call("POST", "/api/runs/nope/cancel")[0], 404)
        status, a = self.call("PUT", "/api/agents/developer", {"parallel": 20})
        self.assertEqual((status, a["parallel"]), (200, 8))
        self.assertEqual(self.dash.slots.load()["developer"]["capacity"], 8)
        p = self.call("PUT", "/api/project", {"max_parallel_tasks": 0, "parallel_prep": True})[1]
        self.assertEqual((p["max_parallel_tasks"], p["parallel_prep"]), (1, True))


if __name__ == "__main__":
    unittest.main()
