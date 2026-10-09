"""Agents ask the CEO mid-task: a QUESTION: line pauses the step, the CEO answers (dashboard,
Telegram, terminal), the agent does the step again with the answer, later agents see it too.

Run: python -m unittest discover -s tests
"""
import copy
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
from babd.team import Agent, Team  # noqa: E402

FIXTURE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures", "agents.json")


def asking_ask(agent, prompt, **kw):
    """The developer asks once, then works with the answer."""
    if agent.id == "developer" and "### The CEO answered" not in prompt:
        return "I need one thing.\nQUESTION: Which port should the app use?\nOPTIONS: 8080 | 3000"
    if agent.id == "developer":
        return "built on port " + prompt.split("### The CEO answered\n")[1].split("\n")[0]
    return td.scripted_ask(agent, prompt, **kw)


class ParseTest(unittest.TestCase):
    def test_parse_question(self):
        q = flow.parse_question("text\n**QUESTION:** Which DB?\nOPTIONS: Postgres | SQLite | `MySQL`")
        self.assertEqual(q, {"question": "Which DB?", "options": ["Postgres", "SQLite", "MySQL"], "ask": []})
        self.assertIsNone(flow.parse_question("no question here"))
        self.assertIsNone(flow.parse_question("QUESTION: <your question>"))  # the instruction echoed back
        self.assertIsNone(flow.parse_question("QUESTION: early\n" + "line\n" * 30))  # only at the end

    def test_parse_question_reads_the_ask_line(self):
        # `ASK:` is what makes peer Q&A work: the named teammates answer before the CEO is bothered.
        q = flow.parse_question("QUESTION: Which DB?\nASK: developer | qa")
        self.assertEqual(q["ask"], ["developer", "qa"])
        self.assertEqual(flow.parse_question("QUESTION: Which DB?")["ask"], [])


class FlowQuestionTest(unittest.TestCase):
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

    def test_the_answer_reaches_the_agent_and_the_team(self):
        asked, prompts = [], []

        def ask(agent, prompt, **kw):
            prompts.append((agent.id, prompt))
            return asking_ask(agent, prompt, **kw)

        def asker(q):
            asked.append(q)
            return "8080"
        with mock.patch.object(Agent, "ask", ask):
            state = flow.Run(Team(self.cfg, log=lambda m: None), "Build an app", asker=asker).execute()
        self.assertEqual(state["status"], "done", state["error"])
        self.assertEqual(asked[0]["question"], "Which port should the app use?")
        self.assertEqual(asked[0]["options"], ["8080", "3000"])
        self.assertEqual(state["questions"][0]["answer"], "8080")
        self.assertIn("built on port 8080", open(os.path.join(state["dir"], "03-developer.md")).read())
        qa_prompt = [p for a, p in prompts if a == "qa"][-1]
        self.assertIn("A: 8080", qa_prompt)  # later agents see the CEO's answers
        self.assertIn(["question", "answer"], [[m["kind"] for m in state["messages"]][i:i + 2] for i in range(len(state["messages"]))])

    def test_without_an_asker_nobody_waits(self):
        with mock.patch.object(Agent, "ask", asking_ask):
            state = flow.Run(Team(self.cfg, log=lambda m: None), "Build an app").execute()
        self.assertEqual(state["status"], "done")
        self.assertEqual(state["questions"], [])

    def test_question_limit(self):
        self.cfg["project"]["max_questions"] = 1
        always = lambda agent, prompt, **kw: ("QUESTION: again?" if agent.id == "developer" else td.scripted_ask(agent, prompt, **kw))  # noqa: E731
        with mock.patch.object(Agent, "ask", always):
            state = flow.Run(Team(self.cfg, log=lambda m: None), "Build", asker=lambda q: "yes").execute()
        self.assertEqual(len(state["questions"]), 1)


class QuestionApiTest(unittest.TestCase):
    setUp = td.DashboardTest.setUp
    call = td.DashboardTest.call
    wait = td.DashboardTest.wait

    def test_answer_from_the_dashboard(self):
        self.call("PUT", "/api/project", {"require_approval": []})
        with mock.patch.object(Agent, "ask", asking_ask):
            _, run = self.call("POST", "/api/runs", {"goal": "Build an app"})
            rid = run["id"]
            self.wait(lambda: self.dash.open_questions())
            _, board = self.call("GET", "/api/board")
            task = next(t for t in board["tasks"] if t["id"] == rid)
            self.assertEqual((task["status"], task["waiting_answer"]), ("waiting_answer", True))
            self.assertEqual(task["question"]["question"], "Which port should the app use?")
            self.assertEqual(self.call("POST", f"/api/runs/{rid}/answer", {"answer": ""})[0], 400)
            status, _ = self.call("POST", f"/api/runs/{rid}/answer", {"answer": "3000"})
            self.assertEqual(status, 200)
            self.wait(lambda: rid not in self.dash.active, timeout=20)
        _, r = self.call("GET", f"/api/runs/{rid}")
        self.assertEqual((r["status"], r["questions"][0]["answer"]), ("done", "3000"))
        self.assertEqual(self.call("POST", f"/api/runs/{rid}/answer", {"answer": "x"})[0], 409)

    def test_stop_while_waiting(self):
        with mock.patch.object(Agent, "ask", asking_ask):
            _, run = self.call("POST", "/api/runs", {"goal": "Build an app"})
            self.wait(lambda: self.dash.open_questions())
            self.call("POST", f"/api/runs/{run['id']}/cancel")
            self.wait(lambda: run["id"] not in self.dash.active)
        self.assertEqual(self.dash.load_run(run["id"])["status"], "cancelled")


if __name__ == "__main__":
    unittest.main()
