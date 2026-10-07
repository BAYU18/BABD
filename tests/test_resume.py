"""Surviving restarts and failures: checkpoints per step, resuming a failed / stopped / interrupted
run from its last finished step, the queue kept on disk, and recovery when the dashboard starts.

Run: python -m unittest discover -s tests
"""
import copy
import json
import os
import shutil
import sys
import tempfile
import threading
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import test_dashboard as td  # noqa: E402
from babd import flow  # noqa: E402
from babd.config import load_config  # noqa: E402
from babd.dashboard.server import Dashboard  # noqa: E402
from babd.team import Agent, Team  # noqa: E402

FIXTURE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures", "agents.json")


class Flaky:
    """Scripted agents; `fail` names (agent, kind-word) pairs that raise once."""

    def __init__(self, fail=()):
        self.fail = set(fail)
        self.calls = []

    def __call__(self, agent, prompt, **kw):
        kind = ("plan" if '"assignments"' in prompt else "report" if "Write the CEO report" in prompt
                else "deploy" if "Deploy it" in prompt else "test" if "VERDICT" in prompt else agent.id)
        self.calls.append((agent.id, kind))
        if (agent.id, kind) in self.fail:
            self.fail.discard((agent.id, kind))
            raise RuntimeError(f"{agent.id} {kind} broke")
        return td.scripted_ask(agent, prompt, **kw)


class ResumeFlowTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, True)
        p = mock.patch.object(flow, "RUNS_DIR", os.path.join(self.tmp, "runs"))
        p.start()
        self.addCleanup(p.stop)
        self.cfg = copy.deepcopy(load_config(FIXTURE))
        self.cfg["project"].update(gbrain={"enabled": False}, superpowers={"enabled": False}, mattpocock={"enabled": False},
                                   parallel_prep=True)
        for a in self.cfg["agents"]:
            a["harness"] = {"type": "direct"}
            a["llm"]["api_key"] = "test"

    def run_flow(self, agents, approver=lambda r: (True, "ok"), **kw):
        with mock.patch.object(Agent, "ask", lambda agent, prompt, **kw: agents(agent, prompt, **kw)):
            return flow.Run(Team(self.cfg, log=lambda m: None), "Build login", approver=approver, **kw).execute()

    def test_failed_run_resumes_after_its_last_finished_step(self):
        agents = Flaky(fail=[("qa", "test")])
        first = self.run_flow(agents)
        self.assertEqual(first["status"], "failed")
        self.assertIn("qa test broke", first["error"])
        self.assertEqual(sorted(first["checkpoints"]), ["code", "deploy_prep", "design", "plan", "test_plan"])
        before = len(agents.calls)
        second = self.run_flow(agents, run_id=first["id"], resume=True)
        self.assertEqual(second["status"], "done", second["error"])
        self.assertEqual(second["id"], first["id"])
        redone = agents.calls[before:]
        self.assertEqual([k for _, k in redone], ["test", "deploy", "report"])  # nothing done twice
        self.assertEqual(second["resumes"], 1)
        seqs = [m["seq"] for m in second["messages"]]
        self.assertEqual(seqs, list(range(1, len(seqs) + 1)))
        self.assertEqual(sum(1 for m in second["messages"] if m["kind"] == "goal"), 1)
        with open(os.path.join(first["dir"], "state.json")) as f:
            self.assertEqual(json.load(f)["status"], "done")

    def test_approval_is_not_asked_twice(self):
        asked = []
        agents = Flaky(fail=[("devops", "deploy")])
        approver = lambda r: (asked.append(r), (True, "ship it"))[1]  # noqa: E731
        self.cfg["project"]["require_approval"] = ["deploy"]
        first = self.run_flow(agents, approver)
        self.assertEqual(first["status"], "failed")
        second = self.run_flow(agents, approver, run_id=first["id"], resume=True)
        self.assertEqual(second["status"], "done", second["error"])
        self.assertEqual(len(asked), 1)
        self.assertTrue(second["deployed"])

    def test_cannot_resume_a_missing_run(self):
        with self.assertRaisesRegex(flow.FlowError, "no saved run"):
            flow.Run(Team(self.cfg, log=lambda m: None), "", run_id="nope", resume=True)


class RecoveryTest(unittest.TestCase):
    setUp = td.DashboardTest.setUp
    call = td.DashboardTest.call
    wait = td.DashboardTest.wait

    def idle(self, dash=None):
        dash = dash or self.dash
        with dash.tasks_lock:
            return not dash.active and not dash.queue

    def interrupted_run(self):
        """A run that was mid-flight when BABD stopped: its state still says running."""
        agents = Flaky(fail=[("qa", "test")])
        cfg = json.loads(td.read(self.cfg_path))
        for a in cfg["agents"]:
            a["llm"]["api_key"] = "test"
        with mock.patch.object(Agent, "ask", lambda agent, prompt, **kw: agents(agent, prompt, **kw)):
            state = flow.Run(Team(cfg, log=lambda m: None), "Half done").execute()
        path = os.path.join(state["dir"], "state.json")
        with open(path) as f:
            s = json.load(f)
        s.update(status="running", error=None, pid=2 ** 22 + 12345)  # that process is gone
        with open(path, "w") as f:
            json.dump(s, f)
        return state["id"]

    def test_restart_resumes_interrupted_tasks(self):
        run_id = self.interrupted_run()
        self.call("PUT", "/api/project", {"require_approval": False})
        with mock.patch.object(Agent, "ask", td.scripted_ask):
            dash = Dashboard(self.cfg_path, regenerate_image=False)  # BABD starts again
            self.wait(lambda: self.idle(dash), timeout=20)
        _, run = self.call("GET", f"/api/runs/{run_id}")
        self.assertEqual((run["status"], run["resumes"]), ("done", 1))

    def test_without_auto_resume_it_waits_for_the_resume_button(self):
        run_id = self.interrupted_run()
        self.call("PUT", "/api/project", {"require_approval": False})
        cfg = json.loads(td.read(self.cfg_path))
        cfg["project"]["auto_resume"] = False
        with open(self.cfg_path, "w") as f:
            json.dump(cfg, f)
        Dashboard(self.cfg_path, regenerate_image=False)
        _, run = self.call("GET", f"/api/runs/{run_id}")
        self.assertEqual(run["status"], "interrupted")
        with mock.patch.object(Agent, "ask", td.scripted_ask):
            status, out = self.call("POST", f"/api/runs/{run_id}/resume")
            self.assertEqual(status, 200, out)
            self.wait(self.idle, timeout=20)
        self.assertEqual(self.call("GET", f"/api/runs/{run_id}")[1]["status"], "done")
        self.assertEqual(self.call("POST", f"/api/runs/{run_id}/resume")[0], 409)  # done: nothing to resume
        self.assertEqual(self.call("POST", "/api/runs/nope/resume")[0], 404)

    def test_queue_survives_a_restart(self):
        self.call("PUT", "/api/project", {"max_parallel_tasks": 1, "require_approval": False})
        gate = threading.Event()

        def slow(agent, prompt, **kw):
            gate.wait(10)
            return td.scripted_ask(agent, prompt, **kw)

        with mock.patch.object(Agent, "ask", slow):
            self.call("POST", "/api/tasks", {"goals": ["One", "Two", "Three"]})
            with open(os.path.join(flow.RUNS_DIR, "_queue.json")) as f:
                self.assertEqual([q["goal"] for q in json.load(f)], ["Two", "Three"])
            gate.set()
            self.wait(self.idle, timeout=30)
        with open(os.path.join(flow.RUNS_DIR, "_queue.json")) as f:
            self.assertEqual(json.load(f), [])


if __name__ == "__main__":
    unittest.main()
