"""QA evidence: a PASS must rest on tests that really ran: the project's own test command (run by BABD
in the task's worktree) or the commands and outputs QA shows.

Run: python -m unittest discover -s tests
"""
import copy
import os
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import test_dashboard as td  # noqa: E402
from babd import flow, projects  # noqa: E402
from babd.config import load_config  # noqa: E402
from babd.harness.others import Direct  # noqa: E402
from babd.team import Agent, Team  # noqa: E402

FIXTURE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures", "agents.json")
EVIDENCE = "EVIDENCE:\n$ python -m pytest -q\n```\n3 passed in 0.1s\n```\nexit code 0\n"


class EvidenceParserTest(unittest.TestCase):
    def test_parser(self):
        self.assertIn("3 passed", flow.evidence_of(f"Looks fine.\n{EVIDENCE}VERDICT: PASS"))
        for no in ("All good.\nVERDICT: PASS", "EVIDENCE: NOT RUN\nVERDICT: PASS",
                   "EVIDENCE:\nI checked it carefully and it works.\nVERDICT: PASS"):
            self.assertIsNone(flow.evidence_of(no), no)


class EvidenceRunTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        for mod, name, sub in ((flow, "RUNS_DIR", "runs"), (projects, "PROJECTS_DIR", "projects"),
                               (projects, "WORKTREES_DIR", "worktrees")):
            p = mock.patch.object(mod, name, os.path.join(self.tmp, sub))
            p.start()
            self.addCleanup(p.stop)
        self.cfg = copy.deepcopy(load_config(FIXTURE))
        self.cfg["project"].update(gbrain={"enabled": False}, superpowers={"enabled": False}, mattpocock={"enabled": False},
                                   parallel_prep=False, require_approval=[], max_fix_rounds=0)
        for a in self.cfg["agents"]:
            a["harness"] = {"type": "direct"}
            a["llm"]["api_key"] = "test"
        self.prompts = []

    def run_with(self, qa_reply, test_command=None, qa_tools=False):
        if test_command is not None:
            self.cfg["project"]["use_projects"] = True
            self.cfg["projects"] = [{"id": "app", "test_command": test_command}]
        replies = iter(qa_reply) if isinstance(qa_reply, list) else None

        def ask(agent, prompt, **kw):
            if agent.id == "qa" and "VERDICT" in prompt:
                self.prompts.append(prompt)
                return next(replies) if replies else qa_reply
            return td.scripted_ask(agent, prompt, **kw)
        with mock.patch.object(Agent, "ask", ask), mock.patch.object(Direct, "has_tools", qa_tools):
            return flow.Run(Team(self.cfg, log=lambda m: None), "Build it", project_id="app" if test_command else None).execute()

    def test_failing_project_tests_overrule_a_pass(self):
        state = self.run_with("Works.\nVERDICT: PASS", test_command="python -c \"print('1 failed'); raise SystemExit(1)\"")
        self.assertEqual(state["verdict"], "FAIL")
        self.assertIn("project's tests fail", state["evidence"]["note"])
        self.assertIn("BABD ran the project's tests", self.prompts[0])
        self.assertIn("1 failed", self.prompts[0])
        self.assertEqual(state["tests"][0]["exit"], 1)
        self.assertFalse(state["deployed"])

    def test_passing_project_tests_verify(self):
        state = self.run_with("Works.\nVERDICT: PASS", test_command="python -c \"print('5 passed')\"")
        self.assertEqual((state["verdict"], state["evidence"]["verified"]), ("PASS", True))
        self.assertEqual(state["evidence"]["source"], "project tests")
        self.assertTrue(state["report"]["verified"])
        self.assertTrue(os.path.exists(os.path.join(state["dir"], "04-tests-round0.txt")))

    def test_qa_with_tools_is_asked_once_for_evidence(self):
        state = self.run_with(["Works.\nVERDICT: PASS", f"Ran them.\n{EVIDENCE}VERDICT: PASS"], qa_tools=True)
        self.assertEqual(len(self.prompts), 2)
        self.assertIn("Run the tests yourself", self.prompts[0])
        self.assertIn("You gave a PASS without evidence", self.prompts[1])
        self.assertEqual((state["verdict"], state["evidence"]["verified"], state["evidence"]["source"]),
                         ("PASS", True, "QA evidence"))

    def test_qa_without_tools_is_unverified(self):
        state = self.run_with("Works.\nVERDICT: PASS")
        self.assertEqual(len(self.prompts), 1)  # no redo: it could not run anything
        self.assertIn("EVIDENCE: NOT RUN", self.prompts[0])
        self.assertEqual(state["verdict"], "PASS")
        self.assertFalse(state["evidence"]["verified"])
        self.assertFalse(state["report"]["verified"])

    def test_require_evidence_turns_an_unproven_pass_into_fail(self):
        self.cfg["project"]["require_evidence"] = True
        state = self.run_with("Works.\nVERDICT: PASS")
        self.assertEqual(state["verdict"], "FAIL")
        self.assertIn("require_evidence", state["evidence"]["note"])


if __name__ == "__main__":
    unittest.main()
