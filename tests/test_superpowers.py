"""Superpowers skills tests: vendored skills, distribution per agent, always-on use in every step,
the "Skills applied" check with one redo, and native install for Hermes / Claude Code.

Run: python -m unittest discover -s tests
"""
import copy
import json
import os
import re
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from babd import flow, superpowers as sp  # noqa: E402
from babd.config import load_config  # noqa: E402
from babd.harness import create_harness  # noqa: E402
from babd.team import Agent, Team  # noqa: E402

IRON_LAWS = {  # a line from each skill's own text, to prove the full skill reached the prompt
    "test-driven-development": "NO PRODUCTION CODE WITHOUT A FAILING TEST FIRST",
    "systematic-debugging": "NO FIXES WITHOUT ROOT CAUSE INVESTIGATION FIRST",
    "verification-before-completion": "NO COMPLETION CLAIMS WITHOUT FRESH VERIFICATION EVIDENCE",
    "brainstorming": "# Brainstorming Ideas Into Designs",
    "writing-plans": "# Writing Plans",
    "receiving-code-review": "# Code Review Reception",
}


def required(prompt):
    m = re.search(r"# Skills you must use for this step: (.*)", prompt)
    return [s.strip() for s in m.group(1).split(",")] if m else []


class Responder:
    """Scripted agents. `comply` decides whether an answer ends with a correct "Skills applied:"."""

    def __init__(self, comply=lambda agent_id, attempt: True):
        self.comply = comply
        self.prompts = []

    def __call__(self, agent, prompt, **kw):
        attempt = 2 if "## Redo required" in prompt else 1
        self.prompts.append((agent.id, prompt, attempt))
        if agent.id == "lead" and '"assignments"' in prompt and "Plan the work" in prompt:
            body = json.dumps({"plan_summary": "Plan.", "assignments": {}})
        elif agent.id == "lead":
            body = json.dumps({"summary": "Done.", "next_action": "Monitor"})
        elif agent.id == "qa":
            body = "Tests written and run.\nVERDICT: PASS"
        else:
            body = f"{agent.id} work"
        skills = required(prompt)
        if skills and self.comply(agent.id, attempt):
            body += "\n\nSkills applied:\n" + "\n".join(f"- {s}: followed it" for s in skills)
        return body


class SuperpowersTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        p = mock.patch.object(flow, "RUNS_DIR", os.path.join(self.tmp, "runs"))
        p.start()
        self.addCleanup(p.stop)
        self.cfg = copy.deepcopy(load_config())
        self.cfg["project"]["gbrain"] = {"enabled": False}
        self.cfg["project"]["mattpocock"] = {"enabled": False}  # covered in test_mattpocock.py
        for a in self.cfg["agents"]:
            a["harness"] = {"type": "direct"}
            a["llm"]["api_key"] = "test"

    def run_team(self, responder, verdicts=None):
        with mock.patch.object(Agent, "ask", lambda agent, prompt, **kw: responder(agent, prompt, **kw)):
            return Team(self.cfg, log=lambda m: None).run("Build login", approver=lambda r: (True, "ok"))

    # -- the vendored skills and their distribution ------------------------------------------

    def test_all_15_skills_vendored_with_license_and_source(self):
        names = sp.skill_names()
        self.assertEqual(len(names), 15)
        for n in names:
            meta, body = sp.load(n)
            self.assertEqual(meta["name"], n)
            self.assertTrue(meta["description"] and body)
        base = sp.SKILLS_DIR
        self.assertTrue(os.path.exists(os.path.join(base, "LICENSE")))
        with open(os.path.join(base, "SOURCE.md")) as f:
            self.assertRegex(f.read(), r"Commit: `[0-9a-f]{40}`")

    def test_every_skill_goes_to_at_least_one_agent(self):
        agents = {a["id"]: a for a in load_config()["agents"]}
        given = set()
        for a in agents.values():
            self.assertTrue(set(a["superpowers"]) <= set(sp.skill_names()), a["id"])
            self.assertIn("using-superpowers", a["superpowers"])
            given |= set(a["superpowers"])
        self.assertEqual(given, set(sp.skill_names()))
        self.assertIn("test-driven-development", agents["developer"]["superpowers"])
        self.assertNotIn("brainstorming", agents["qa"]["superpowers"])

    def test_step_mapping(self):
        dev = {"id": "developer"}
        self.assertEqual(sp.for_step(dev, "fix"), ["systematic-debugging", "receiving-code-review",
                                                   "test-driven-development", "verification-before-completion"])
        self.assertEqual(sp.for_step({"id": "architect"}, "design"), ["brainstorming", "writing-plans"])
        self.assertEqual(sp.for_step({"id": "qa", "superpowers": ["using-superpowers"]}, "test_report"), [])

    # -- always used --------------------------------------------------------------------------

    def test_every_step_gets_its_skills_in_full(self):
        r = Responder()
        state = self.run_team(r)
        self.assertEqual(state["status"], "done", state["error"])
        by_agent = {}
        for agent_id, prompt, _ in r.prompts:
            by_agent.setdefault(agent_id, []).append(prompt)
        dev_code = by_agent["developer"][0]
        self.assertEqual(required(dev_code), ["test-driven-development", "executing-plans", "using-git-worktrees",
                                              "verification-before-completion"])
        self.assertIn(IRON_LAWS["test-driven-development"], dev_code)
        self.assertIn("## How the Superpowers skills apply inside this team", dev_code)
        self.assertIn(IRON_LAWS["brainstorming"], by_agent["lead"][0])
        self.assertIn(IRON_LAWS["writing-plans"], by_agent["architect"][0])
        self.assertIn(IRON_LAWS["systematic-debugging"], by_agent["qa"][0])
        self.assertIn(IRON_LAWS["verification-before-completion"], by_agent["devops"][0])
        steps = [(k["agent"], k["kind"], k["missing"]) for k in state["skills"]]
        self.assertEqual([s[:2] for s in steps], [("lead", "plan"), ("architect", "design"), ("developer", "code"),
                                                  ("qa", "test_report"), ("devops", "deploy_report"), ("lead", "report")])
        self.assertTrue(all(not missing for *_, missing in steps))

    def test_fix_round_uses_debugging_and_review_skills(self):
        verdicts = iter(["FAIL", "PASS"])
        r = Responder()
        original = r.__call__

        def call(agent, prompt, **kw):
            out = original(agent, prompt, **kw)
            return out.replace("VERDICT: PASS", f"VERDICT: {next(verdicts)}") if agent.id == "qa" else out

        state = self.run_team(call)
        fix = [p for a, p, _ in r.prompts if a == "developer" and "Fix the bugs" in p][0]
        self.assertIn(IRON_LAWS["systematic-debugging"], fix)
        self.assertIn(IRON_LAWS["receiving-code-review"], fix)
        self.assertIn(("developer", "fix"), [(k["agent"], k["kind"]) for k in state["skills"]])

    def test_missing_skills_get_one_redo(self):
        r = Responder(comply=lambda agent_id, attempt: agent_id != "developer" or attempt == 2)
        state = self.run_team(r)
        dev = [k for k in state["skills"] if k["agent"] == "developer"][0]
        self.assertTrue(dev["retried"])
        self.assertEqual(dev["missing"], [])
        redo = [p for a, p, n in r.prompts if a == "developer" and n == 2][0]
        self.assertIn("You did not show how you applied: test-driven-development", redo)
        self.assertIn("## Your previous answer\ndeveloper work", redo)

    def test_still_missing_after_redo_is_recorded(self):
        state = self.run_team(Responder(comply=lambda agent_id, attempt: agent_id != "qa"))
        qa = [k for k in state["skills"] if k["agent"] == "qa"][0]
        self.assertTrue(qa["retried"])
        self.assertIn("verification-before-completion", qa["missing"])
        self.assertEqual(state["status"], "done")  # recorded and shown, the run goes on

    def test_enforce_off_means_no_redo(self):
        self.cfg["project"]["superpowers"] = {"enabled": True, "enforce": False}
        r = Responder(comply=lambda agent_id, attempt: False)
        state = self.run_team(r)
        self.assertFalse(any(n == 2 for *_, n in r.prompts))
        self.assertTrue(all(k["missing"] and not k["retried"] for k in state["skills"]))

    def test_disabled(self):
        self.cfg["project"]["superpowers"] = {"enabled": False}
        r = Responder()
        state = self.run_team(r)
        self.assertEqual(state["skills"], [])
        self.assertFalse(any("Skills you must use" in p for _, p, _ in r.prompts))

    def test_system_prompt_has_the_agents_catalog_only(self):
        qa = Agent(self.cfg["agents"][3], project=self.cfg["project"])
        prompt = qa.system_prompt()
        self.assertIn("## Skills (always on)", prompt)
        self.assertIn("### Superpowers (obra/superpowers)", prompt)
        self.assertIn("- test-driven-development:", prompt)
        self.assertNotIn("- brainstorming:", prompt)

    # -- local, native install -----------------------------------------------------------------

    def test_hermes_gets_native_skills(self):
        qa = copy.deepcopy(self.cfg["agents"][3])
        qa["harness"] = {"type": "hermes_local", "home": os.path.join(self.tmp, "hermes-qa")}
        h = create_harness(qa, self.cfg["project"])
        notes = h.configure()
        dest = os.path.join(self.tmp, "hermes-qa", "skills", "superpowers")
        self.assertEqual(sorted(os.listdir(dest)), sorted(qa["superpowers"]))
        self.assertTrue(os.path.exists(os.path.join(dest, "systematic-debugging", "find-polluter.sh")))
        self.assertIn(f"{len(qa['superpowers'])} superpowers skills", notes)
        qa["superpowers"] = ["using-superpowers"]  # a removed skill disappears too
        create_harness(qa, self.cfg["project"]).configure()
        self.assertEqual(os.listdir(dest), ["using-superpowers"])

    def test_claude_code_only_in_its_private_config_dir(self):
        dev = copy.deepcopy(self.cfg["agents"][2])
        dev["harness"] = {"type": "claude_local", "config_dir": os.path.join(self.tmp, "claude-dev")}
        create_harness(dev, self.cfg["project"]).configure()
        self.assertIn("test-driven-development", os.listdir(os.path.join(self.tmp, "claude-dev", "skills")))
        dev["llm"].pop("api_key")
        dev["harness"] = {"type": "claude_local"}
        with mock.patch.dict(os.environ, {"ANTHROPIC_API_KEY": ""}):
            notes = create_harness(dev, self.cfg["project"]).configure()
        self.assertEqual(notes, ["using this machine's Claude Code login"])  # the user's ~/.claude untouched

    def test_missing_check(self):
        out = "work\n\nSkills applied:\n- test-driven-development: red then green"
        self.assertEqual(sp.missing(out, ["test-driven-development", "verification-before-completion"]),
                         ["verification-before-completion"])
        self.assertEqual(sp.missing("test-driven-development mentioned in passing", ["test-driven-development"]),
                         ["test-driven-development"])


if __name__ == "__main__":
    unittest.main()
