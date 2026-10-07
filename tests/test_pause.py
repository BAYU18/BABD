"""Pause, continue and stop a task: a paused task starts no new step, Resume continues it, Stop
kills the agent's running program at once.

Run: python -m unittest discover -s tests
"""
import copy
import os
import shutil
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
from babd.harness import create_harness  # noqa: E402
from babd.harness.base import HarnessError  # noqa: E402
from babd.team import Agent, Team  # noqa: E402

FIXTURE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures", "agents.json")


def wait(cond, timeout=10):
    end = time.time() + timeout
    while time.time() < end:
        if cond():
            return True
        time.sleep(0.02)
    raise AssertionError("timed out")


class PauseFlowTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, True)
        p = mock.patch.object(flow, "RUNS_DIR", os.path.join(self.tmp, "runs"))
        p.start()
        self.addCleanup(p.stop)
        self.cfg = copy.deepcopy(load_config(FIXTURE))
        self.cfg["project"].update(gbrain={"enabled": False}, superpowers={"enabled": False}, mattpocock={"enabled": False},
                                   parallel_prep=False, require_approval=[])
        for a in self.cfg["agents"]:
            a["harness"] = {"type": "direct"}
            a["llm"]["api_key"] = "test"

    def test_pause_then_continue(self):
        calls = []

        def ask(agent, prompt, **kw):
            calls.append(agent.id)
            return td.scripted_ask(agent, prompt, **kw)
        with mock.patch.object(Agent, "ask", ask):
            run = flow.Run(Team(self.cfg, log=lambda m: None), "Build login")
            run.pause(True)
            t = threading.Thread(target=run.execute)
            t.start()
            wait(lambda: run.state["status"] == "paused")
            time.sleep(0.3)
            self.assertEqual(calls, [])  # nothing runs while paused
            run.pause(False)
            t.join(10)
        self.assertEqual(run.state["status"], "done", run.state["error"])
        self.assertIn("developer", calls)

    def test_stop_while_paused(self):
        with mock.patch.object(Agent, "ask", td.scripted_ask):
            run = flow.Run(Team(self.cfg, log=lambda m: None), "Build login")
            run.pause(True)
            t = threading.Thread(target=run.execute)
            t.start()
            wait(lambda: run.state["status"] == "paused")
            run.cancelled.set()
            t.join(10)
        self.assertEqual(run.state["status"], "cancelled")


class StopKillsTheProgramTest(unittest.TestCase):
    def test_cancel_kills_the_running_program(self):
        h = create_harness({"id": "dev", "llm": {"model": "m"}, "harness": {"type": "process", "command": "sleep"}})
        h.cancel_event = threading.Event()
        threading.Timer(0.3, h.cancel_event.set).start()
        started = time.monotonic()
        with self.assertRaisesRegex(HarnessError, "stopped"):
            h.run_process(["sh", "-c", "sleep 30; echo late"], {})
        self.assertLess(time.monotonic() - started, 5)

    def test_normal_run_and_errors(self):
        h = create_harness({"id": "dev", "llm": {"model": "m"}, "harness": {"type": "process", "command": "cat"}})
        self.assertEqual(h.run_process(["cat"], {}, stdin_text="hello"), "hello")
        with self.assertRaisesRegex(HarnessError, "exit code 3"):
            h.run_process(["sh", "-c", "echo boom; exit 3"], {})


class PauseApiTest(unittest.TestCase):
    setUp = td.DashboardTest.setUp
    call = td.DashboardTest.call
    wait = td.DashboardTest.wait

    def test_pause_and_resume_through_the_api(self):
        self.call("PUT", "/api/project", {"require_approval": []})
        gate = threading.Event()

        def ask(agent, prompt, **kw):
            if agent.id == "lead" and '"assignments"' in prompt:
                gate.wait(5)
            return td.scripted_ask(agent, prompt, **kw)
        with mock.patch.object(Agent, "ask", ask):
            _, run = self.call("POST", "/api/runs", {"goal": "Build login"})
            rid = run["id"]
            self.wait(lambda: rid in self.dash.active)
            status, out = self.call("POST", f"/api/runs/{rid}/pause")
            self.assertEqual((status, out["paused"]), (200, True))
            gate.set()  # the plan step finishes; the next step waits
            self.wait(lambda: self.dash.active[rid]["run"].state["status"] == "paused")
            _, board = self.call("GET", "/api/board")
            self.assertEqual(next(t for t in board["tasks"] if t["id"] == rid)["status"], "paused")
            status, _ = self.call("POST", f"/api/runs/{rid}/resume")
            self.assertEqual(status, 200)
            self.wait(lambda: rid not in self.dash.active, timeout=20)
        _, r = self.call("GET", f"/api/runs/{rid}")
        self.assertEqual(r["status"], "done")
        self.assertEqual(self.call("POST", f"/api/runs/{rid}/pause")[0], 404)


if __name__ == "__main__":
    unittest.main()
