"""Tests for progressive skill loading + skill evolution (token-saving skill routing).

The classic suites (test_superpowers / test_mattpocock) pin skills_mode="full" and prove the
full-text path still works. This suite covers the new default path:
  * progressive mode ships a compact catalog and no skill bodies,
  * a consumer cannot tell progressive and full prompts apart by *behaviour* (both name the step's
    skills), only by size,
  * skill_evolution records usage, ranks proven skills first, and drops dormant ones,
  * token cost of progressive << token cost of full.
"""
import copy
import json
import os
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from babd import flow, skill_evolution, skillpacks  # noqa: E402
from babd.config import load_config  # noqa: E402
from babd.team import Agent, Team  # noqa: E402

FIXTURE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures", "agents.json")


def _cfg(mode):
    cfg = copy.deepcopy(load_config(FIXTURE))
    cfg["project"]["gbrain"] = {"enabled": False}
    cfg["project"]["parallel_prep"] = False
    cfg["project"]["skills_mode"] = mode
    for a in cfg["agents"]:
        a["harness"] = {"type": "direct"}
        a["llm"]["api_key"] = "test"
    return cfg


class ProgressiveLoadingTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        p = mock.patch.object(flow, "RUNS_DIR", os.path.join(self.tmp, "runs"))
        p.start()
        self.addCleanup(p.stop)
        # isolate the evolution store so tests do not touch the live one
        self._ev = mock.patch.object(skill_evolution, "_path", lambda: os.path.join(self.tmp, "skill_usage.json"))
        self._ev.start()
        self.addCleanup(self._ev.stop)

    def test_progressive_prompt_is_much_smaller_than_full(self):
        skills = ["test-driven-development", "verification-before-completion"]
        full = skillpacks.step_block(skills, agent_id="developer", mode="full")
        prog = skillpacks.step_block(skills, agent_id="developer", mode="progressive")
        self.assertLess(len(prog), len(full) // 3, "progressive must cut the step block by >3x")
        # progressive still names the skills the step must use
        self.assertIn("test-driven-development", prog)
        self.assertIn("verification-before-completion", prog)

    def test_progressive_has_catalog_but_no_skill_body(self):
        prog = skillpacks.step_block(["test-driven-development"], agent_id="developer", mode="progressive")
        self.assertIn("Your skills (catalog)", prog)  # the shelf is there
        self.assertNotIn("NO PRODUCTION CODE WITHOUT A FAILING TEST FIRST", prog)  # body is not

    def test_full_mode_pins_skill_body(self):
        full = skillpacks.step_block(["test-driven-development"], agent_id="developer", mode="full")
        self.assertIn("NO PRODUCTION CODE WITHOUT A FAILING TEST FIRST", full)


class SkillEvolutionTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self._ev = mock.patch.object(skill_evolution, "_path", lambda: os.path.join(self.tmp, "skill_usage.json"))
        self._ev.start()
        self.addCleanup(self._ev.stop)

    def test_record_and_reliability(self):
        for _ in range(4):
            skill_evolution.record("developer", ["tdd", "review"], applied=["tdd", "review"])
        skill_evolution.record("developer", ["tdd"], applied=[])  # one miss
        rel = skill_evolution.reliability("developer", "tdd")
        self.assertAlmostEqual(rel, 4 / 5, places=5)
        self.assertEqual(skill_evolution.reliability("developer", "never-used"), None)

    def test_rank_prefers_proven_skills(self):
        skill_evolution.record("developer", ["proven"], applied=["proven"])
        ranked = skill_evolution.rank("developer", ["fresh", "proven"])
        self.assertEqual(ranked[0], "proven")

    def test_dormant_after_many_misses(self):
        for _ in range(skill_evolution.DORMANT_AFTER):
            skill_evolution.record("qa", ["flaky"], applied=[])
        self.assertTrue(skill_evolution.is_dormant("qa", "flaky"))
        # dormant skills are dropped from the catalog
        cat = skillpacks.progressive_catalog_for_agent("qa", ["flaky", "solid"])
        self.assertNotIn("flaky", cat)
        self.assertIn("solid", cat)

    def test_reset_clears_history(self):
        skill_evolution.record("developer", ["tdd"], applied=["tdd"])
        skill_evolution.reset("developer")
        self.assertIsNone(skill_evolution.reliability("developer", "tdd"))


class EndToEndProgressiveTest(ProgressiveLoadingTest):
    """The real workflow under progressive mode: agents still get their step's skills named."""

    def _run(self, mode):
        cfg = _cfg(mode)
        prompts = []

        def responder(agent, prompt, **kw):
            prompts.append((agent.id, prompt))
            if agent.id == "qa":
                return "Tests.\nVERDICT: PASS"
            if agent.id == "lead":
                return json.dumps({"plan_summary": "P.", "assignments": {}})
            return f"{agent.id} work"

        with mock.patch.object(Agent, "ask", lambda agent, prompt, **kw: responder(agent, prompt, **kw)):
            state = Team(cfg, log=lambda m: None).run("Build login", approver=lambda r: (True, "ok"))
        return prompts, state

    def test_run_completes_in_progressive_mode(self):
        _, state = self._run("progressive")
        self.assertEqual(state["status"], "done", state.get("error"))

    def test_progressive_run_uses_far_fewer_chars_than_full(self):
        prog_prompts, _ = self._run("progressive")
        full_prompts, _ = self._run("full")
        prog_chars = sum(len(p) for _, p in prog_prompts)
        full_chars = sum(len(p) for _, p in full_prompts)
        self.assertLess(prog_chars, full_chars * 0.6,
                        f"progressive should be <60% of full ({prog_chars} vs {full_chars})")


if __name__ == "__main__":
    unittest.main()
