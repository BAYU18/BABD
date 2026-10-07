"""Work packages: the Team Lead splits a complex task into packages; each starts as soon as the
packages it depends on are done, independent ones run at the same time.

Run: python -m unittest discover -s tests
"""
import copy
import json
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
from babd.team import Agent, Team  # noqa: E402

FIXTURE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures", "agents.json")
PACKAGES = [
    {"id": "p1", "title": "API design", "agent": "architect", "task": "Design the API", "depends_on": []},
    {"id": "p2", "title": "Backend", "agent": "developer", "task": "Build the API", "depends_on": ["p1"]},
    {"id": "p3", "title": "Frontend", "agent": "developer", "task": "Build the page", "depends_on": []},
    {"id": "p4", "title": "Tests", "agent": "qa", "task": "Write tests", "depends_on": ["p1"]},
    {"id": "p5", "title": "Deploy setup", "agent": "devops", "task": "Prepare deploy", "depends_on": []},
]


class PackagesTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, True)
        p = mock.patch.object(flow, "RUNS_DIR", os.path.join(self.tmp, "runs"))
        p.start()
        self.addCleanup(p.stop)
        self.cfg = copy.deepcopy(load_config(FIXTURE))
        self.cfg["project"].update(gbrain={"enabled": False}, superpowers={"enabled": False}, mattpocock={"enabled": False},
                                   parallel_prep=True, require_approval=[])
        for a in self.cfg["agents"]:
            a["harness"] = {"type": "direct"}
            a["llm"]["api_key"] = "test"
            a["parallel"] = 2

    def run_with(self, packages):
        self.events, lock = [], threading.Lock()

        def ask(agent, prompt, **kw):
            if agent.id == "lead" and '"assignments"' in prompt:
                return json.dumps({"plan_summary": "split", "assignments": {}, "work_packages": packages})
            pkg = next((p["id"] for p in packages if f"Yours is {p['id']}:" in prompt), None)
            with lock:
                self.events.append(("start", pkg or agent.id, time.monotonic(), prompt))
            time.sleep(0.2)
            with lock:
                self.events.append(("end", pkg or agent.id, time.monotonic(), ""))
            return td.scripted_ask(agent, prompt, **kw)
        with mock.patch.object(Agent, "ask", ask):
            return flow.Run(Team(self.cfg, log=lambda m: None), "Build a shop", approver=lambda r: (True, "")).execute()

    def at(self, kind, pid):
        return next(t for k, p, t, _ in self.events if k == kind and p == pid)

    def test_packages_run_as_soon_as_their_dependencies_are_done(self):
        state = self.run_with(PACKAGES)
        self.assertEqual(state["status"], "done", state["error"])
        self.assertEqual([p["status"] for p in state["packages"]], ["done"] * 5)
        # p1, p3 and p5 do not wait for anything: they start together
        starts = [self.at("start", p) for p in ("p1", "p3", "p5")]
        self.assertLess(max(starts) - min(starts), 0.15)
        # p2 and p4 wait for p1, and not for p3 / p5
        self.assertGreaterEqual(self.at("start", "p2"), self.at("end", "p1"))
        self.assertGreaterEqual(self.at("start", "p4"), self.at("end", "p1"))
        p2_prompt = next(pr for k, p, _, pr in self.events if k == "start" and p == "p2")
        self.assertIn("finished p1: API design", p2_prompt)
        self.assertNotIn("finished p3", p2_prompt)
        # the whole build took about two package lengths, not five
        self.assertLess(self.at("end", "p2") - min(starts), 0.8)
        self.assertEqual((state["stages"]["design"], state["stages"]["code"]), ("done", "done"))
        self.assertIn("pkg-p3", state["checkpoints"])
        self.assertEqual(state["verdict"], "PASS")

    def test_bad_packages_are_cleaned(self):
        run = flow.Run(Team(self.cfg, log=lambda m: None), "x")
        pk = run.packages_of({"work_packages": [
            {"id": "a", "agent": "developer", "task": "t1", "depends_on": ["b", "zzz", "a"]},
            {"id": "b", "agent": "nobody", "task": "t2", "depends_on": ["a"]},  # a cycle with a
            {"id": "a", "agent": "qa", "task": "t3"},
            {"agent": "qa", "task": ""}]})
        by = {p["id"]: p for p in pk}
        self.assertEqual(sorted(by), ["a", "ax", "b"])
        self.assertEqual(by["b"]["agent"], "developer")
        self.assertNotIn("zzz", by["a"]["depends_on"])
        self.assertTrue(not by["a"]["depends_on"] or not by["b"]["depends_on"])  # the cycle is broken
        seen = set()
        for p in pk:  # in an order where every dependency comes first
            self.assertTrue(set(p["depends_on"]) <= seen)
            seen.add(p["id"])
        self.assertEqual(run.packages_of({"work_packages": [{"agent": "developer", "task": "one"}]}), [])  # one = no split
        self.assertEqual(run.packages_of({"work_packages": [{"agent": "qa", "task": "a"}, {"agent": "qa", "task": "b"}]}), [])

    def test_no_packages_is_the_normal_flow(self):
        state = self.run_with([])
        self.assertEqual(state["status"], "done")
        self.assertNotIn("packages", state)


if __name__ == "__main__":
    unittest.main()
