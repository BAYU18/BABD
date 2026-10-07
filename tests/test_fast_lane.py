"""The fast lane: the Team Lead triages a task and only the agents it needs work on it
(answer it itself, one agent directly, or the team without the Architect / DevOps); secrets the
agents create are never committed.

Run: python -m unittest discover -s tests
"""
import copy
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import test_dashboard as td  # noqa: E402
from babd import flow, projects  # noqa: E402
from babd.config import load_config  # noqa: E402
from babd.team import Agent, Team  # noqa: E402

FIXTURE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures", "agents.json")
GOAL = "buatkan saya ssh key berjudul server lpnotif agar anda nanti bisa akses server saya"


class FastLaneTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, True)
        p = mock.patch.object(flow, "RUNS_DIR", os.path.join(self.tmp, "runs"))
        p.start()
        self.addCleanup(p.stop)
        self.cfg = copy.deepcopy(load_config(FIXTURE))
        self.cfg["project"].update(gbrain={"enabled": False}, superpowers={"enabled": False}, mattpocock={"enabled": False},
                                   parallel_prep=True, require_approval=["deploy"], fast_lane=True)
        for a in self.cfg["agents"]:
            a["harness"] = {"type": "direct"}
            a["llm"]["api_key"] = "test"
        self.calls = []

    def run_with(self, triage, options=None, goal=GOAL):
        def ask(agent, prompt, **kw):
            self.calls.append((agent.id, prompt, kw))
            if agent.id == "lead" and "Decide who is needed" in prompt:
                if isinstance(triage, Exception):
                    raise triage
                return triage if isinstance(triage, str) else json.dumps(triage)
            if agent.id == "devops" and "quick job" in prompt:
                return "Ran ssh-keygen -t ed25519 -C 'server lpnotif' -f ~/.ssh/server_lpnotif\nPublic key: ssh-ed25519 AAAA server lpnotif"
            return td.scripted_ask(agent, prompt, **kw)
        with mock.patch.object(Agent, "ask", ask):
            return flow.Run(Team(self.cfg, log=lambda m: None), goal, approver=lambda r: (True, ""), options=options).execute()

    def who(self):
        return [a for a, *_ in self.calls]

    def test_direct_runs_only_one_agent(self):
        state = self.run_with({"route": "direct", "agent": "devops", "task": "Create the SSH key 'server lpnotif'",
                               "reason": "one command"})
        self.assertEqual(state["status"], "done", state["error"])
        self.assertEqual(self.who(), ["lead", "devops"])  # triage + the work: no plan, design, QA, deploy, report call
        self.assertEqual(state["route"]["route"], "direct")
        self.assertEqual(state["route"]["agent"], "devops")
        self.assertEqual([s["kind"] for s in state["steps"]], ["triage", "result"])
        self.assertEqual({k: state["stages"][k] for k in ("design", "test", "approval", "deploy")},
                         dict.fromkeys(("design", "test", "approval", "deploy"), "skipped"))
        rep = state["report"]
        self.assertEqual((rep["status"], rep["progress"]), ("DONE", 100))
        self.assertIn("ssh-ed25519 AAAA", rep["summary"])
        for _, prompt, kw in self.calls:  # quick calls: the short system prompt, no skill texts
            self.assertIn("quick job", kw["system"])
        self.assertIn("Secrets you create", self.calls[1][1])
        self.assertIn("Create the SSH key 'server lpnotif'", self.calls[1][1])

    def test_answer_from_the_team_lead(self):
        state = self.run_with({"route": "answer", "answer": "Use ed25519 keys.", "reason": "a question"})
        self.assertEqual(self.who(), ["lead"])
        self.assertEqual((state["status"], state["report"]["summary"], state["report"]["status"]),
                         ("done", "Use ed25519 keys.", "DONE"))
        self.assertEqual(state["messages"][-1]["kind"], "report")

    def test_team_with_only_the_needed_agents(self):
        state = self.run_with({"route": "team", "agents": ["developer", "qa"], "reason": "small fix"})
        self.assertEqual(state["status"], "done", state["error"])
        self.assertNotIn("architect", self.who())
        self.assertNotIn("devops", self.who())
        self.assertEqual(state["route"]["agents"], ["developer", "qa"])
        self.assertEqual((state["stages"]["design"], state["stages"]["deploy"]), ("skipped", "skipped"))
        self.assertEqual(state["report"]["status"], "DONE")

    def test_unclear_triage_runs_the_whole_team(self):
        for triage in ("I think the team should do it", RuntimeError("model down")):
            self.calls.clear()
            state = self.run_with(triage)
            self.assertEqual(state["route"]["route"], "team")
            self.assertTrue({"architect", "developer", "qa", "devops"} <= set(self.who()), triage)
            self.assertTrue(state["deployed"])

    def test_modes(self):
        state = self.run_with({"route": "direct", "agent": "devops"}, options={"mode": "full"})
        self.assertEqual(state["route"]["source"], "settings")
        self.assertFalse(any("Decide who is needed" in p for _, p, _ in self.calls))
        self.assertIn("architect", self.who())
        self.calls.clear()
        state = self.run_with({"route": "team", "agents": ["developer", "qa"]}, options={"mode": "quick"})
        self.assertEqual(state["route"]["route"], "direct")  # quick never runs the whole team
        self.assertNotIn('"team"', self.calls[0][1].split("Answer with only")[1])
        self.calls.clear()
        self.cfg["project"]["fast_lane"] = False
        state = self.run_with({"route": "direct", "agent": "devops"})
        self.assertEqual(state["route"]["route"], "team")
        self.assertIn("architect", self.who())

    def test_unknown_direct_agent(self):
        state = self.run_with({"route": "direct", "agent": "ceo"})
        self.assertEqual(state["route"]["agent"], "developer")  # direct API agents cannot run commands
        with mock.patch.object(flow.Run, "can_run", lambda self, a: a == "devops"):
            state = self.run_with({"route": "direct", "agent": "ceo"})
        self.assertEqual(state["route"]["agent"], "devops")  # the first that can run commands


class FastLaneApiTest(unittest.TestCase):
    setUp = td.DashboardTest.setUp
    call = td.DashboardTest.call
    wait = td.DashboardTest.wait

    def test_quick_task_through_the_api(self):
        status, _ = self.call("PUT", "/api/project", {"fast_lane": True})
        self.assertEqual(status, 200)

        def ask(agent, prompt, **kw):
            if agent.id == "lead" and "Decide who is needed" in prompt:
                return json.dumps({"route": "direct", "agent": "developer", "task": "Print hello", "reason": "tiny"})
            return f"{agent.id} did it"
        with mock.patch.object(Agent, "ask", ask):
            status, run = self.call("POST", "/api/runs", {"goal": "Print hello", "options": {"mode": "quick"}})
            self.assertEqual(status, 200, run)
            self.wait(lambda: run["id"] not in self.dash.active)
        _, r = self.call("GET", f"/api/runs/{run['id']}")
        self.assertEqual((r["status"], r["route"]["route"], r["route"]["agent"]), ("done", "direct", "developer"))
        self.assertEqual((r["task_options"]["mode"], r["report"]["summary"]), ("quick", "developer did it"))
        _, board = self.call("GET", "/api/board")
        task = next(t for t in board["tasks"] if t["id"] == run["id"])
        self.assertEqual(task["route"]["route"], "direct")
        self.assertTrue(board["limits"]["fast_lane"])
        self.assertEqual(self.call("POST", "/api/runs", {"goal": "x", "options": {"mode": "turbo"}})[0], 400)


class SecretsTest(unittest.TestCase):
    def test_private_keys_are_never_committed(self):
        tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, tmp, True)
        with mock.patch.object(projects, "WORKTREES_DIR", os.path.join(tmp, "wt")):
            project = projects.normalize({"id": "p", "path": os.path.join(tmp, "p"), "merge": "on_pass"})
            ws = projects.start(project, "r1")
            files = {"keys/server": "-----BEGIN OPENSSH " + "PRIVATE KEY-----\nabc\n", "keys/server.pub": "ssh-ed25519 AAAA x\n",
                     ".env": "TOKEN=1\n", "id_ed25519": "x", "app.py": "print(1)\n"}
            for rel, body in files.items():
                os.makedirs(os.path.dirname(os.path.join(ws["dir"], rel)), exist_ok=True)
                with open(os.path.join(ws["dir"], rel), "w") as f:
                    f.write(body)
            out = projects.finish(project, ws, "work", merge=True)
            self.assertEqual(sorted(out["secrets_left_out"]), [".env", "id_ed25519", "keys/server"])
            committed = subprocess.run(["git", "ls-tree", "-r", "--name-only", ws["branch"]], cwd=project["path"],
                                       capture_output=True, text=True).stdout.split()
            self.assertEqual(sorted(committed), ["app.py", "keys/server.pub"])
            self.assertTrue(os.path.exists(os.path.join(ws["dir"], "keys/server")))  # kept on disk
            self.assertIn("not committed (secrets)", out["note"])


if __name__ == "__main__":
    unittest.main()
