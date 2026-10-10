"""Matt Pocock's skills tests: vendored skills, distribution and recommendations per agent, always-on
use in every step next to Superpowers, the "Skills applied" check and native install.

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

from babd import flow, mattpocock as mp, skillpacks, superpowers  # noqa: E402
from babd.config import load_config  # noqa: E402

FIXTURE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures", "agents.json")  # not the live agents.json
from babd.harness import create_harness  # noqa: E402
from babd.team import Agent, Team  # noqa: E402

LINES = {  # a line from each skill's own text, to prove the full skill reached the prompt
    "tdd": "Red before green.",
    "grilling": "Interview the user relentlessly until you reach a shared understanding.",
    "to-spec": "## User Stories",
    "codebase-design": "Design **deep modules**",
    "diagnosing-bugs": "## Phase 1: Build a feedback loop",
    "code-review": "Two-axis review",
    "wizard": "A **wizard** is a bash script",
    "wait-what": "ASD-STE100 Simplified Technical English",
}


def required(prompt):
    m = re.search(r"# Skills you must use for this step: (.*)", prompt)
    if not m:  # progressive mode names the step's skills differently
        m = re.search(r"# For this step you must use: (.*)", prompt)
    return [s.strip() for s in m.group(1).split(",")] if m else []


class Responder:
    """Scripted agents. `comply(agent_id, attempt, skill)` decides which skills an answer accounts for."""

    def __init__(self, comply=lambda agent_id, attempt, skill: True):
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
        done = [s for s in required(prompt) if self.comply(agent.id, attempt, s)]
        if done:
            body += "\n\nSkills applied:\n" + "\n".join(f"- {s}: followed it" for s in done)
        return body


class MattPocockTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        p = mock.patch.object(flow, "RUNS_DIR", os.path.join(self.tmp, "runs"))
        p.start()
        self.addCleanup(p.stop)
        self.cfg = copy.deepcopy(load_config(FIXTURE))
        self.cfg["project"]["gbrain"] = {"enabled": False}
        self.cfg["project"]["parallel_prep"] = False  # the parallel flow is covered in test_parallel.py
        self.cfg["project"]["skills_mode"] = "full"  # this suite covers the full-text path
        for a in self.cfg["agents"]:
            a["harness"] = {"type": "direct"}
            a["llm"]["api_key"] = "test"

    def run_team(self, responder):
        with mock.patch.object(Agent, "ask", lambda agent, prompt, **kw: responder(agent, prompt, **kw)):
            return Team(self.cfg, log=lambda m: None).run("Build login", approver=lambda r: (True, "ok"))

    # -- the vendored skills, distribution and recommendations --------------------------------

    def test_all_38_skills_vendored_with_license_and_source(self):
        names = mp.PACK.skill_names()
        self.assertEqual(len(names), 38)
        for n in names:
            meta, body = mp.PACK.load(n)
            self.assertEqual(meta["name"], n)
            self.assertTrue(meta["description"] and body)
        self.assertTrue(os.path.exists(os.path.join(mp.PACK.dir, "LICENSE")))
        with open(os.path.join(mp.PACK.dir, "SOURCE.md")) as f:
            source = f.read()
        self.assertRegex(source, r"Commit: `[0-9a-f]{40}`")
        for n in names:
            self.assertIn(f"| {n} |", source)

    def test_every_skill_is_given_or_optional_with_a_reason(self):
        names = set(mp.PACK.skill_names())
        given = {n for v in mp.RECOMMENDED.values() for n in v}
        self.assertEqual(given | set(mp.OPTIONAL), names)
        self.assertFalse(given & set(mp.OPTIONAL))
        for n in given:
            self.assertTrue(mp.PLAIN.get(n) and mp.WHY.get(n), n)
        steps = {n for v in mp.STEP_SKILLS.values() for n in v}
        self.assertTrue(steps <= given)

    def test_no_skill_name_in_two_packs(self):
        self.assertFalse(set(mp.PACK.skill_names()) & set(superpowers.skill_names()))

    def test_agents_json_lists_the_recommended_skills(self):
        for a in load_config(FIXTURE)["agents"]:
            self.assertEqual(a["mattpocock"], mp.RECOMMENDED[a["id"]])
            status = skillpacks.recommendation_status(a)
            self.assertEqual(status["have"], status["recommended"], a["id"])
        self.assertIn("tdd", mp.RECOMMENDED["developer"])
        self.assertIn("code-review", mp.RECOMMENDED["qa"])
        self.assertIn("wizard", mp.RECOMMENDED["devops"])
        self.assertNotIn("tdd", mp.RECOMMENDED["lead"])

    def test_recommendation_status_shows_what_is_missing(self):
        dev = copy.deepcopy(self.cfg["agents"][2])
        dev["mattpocock"] = ["tdd", "teach"]
        dev["skills"] = ["gbrain", "Python"]
        st = skillpacks.recommendation_status(dev)
        self.assertEqual(st["packs"]["mattpocock"]["extra"], ["teach"])
        self.assertIn("diagnosing-bugs", st["packs"]["mattpocock"]["missing"])
        self.assertNotIn("tdd", st["packs"]["mattpocock"]["missing"])
        self.assertEqual(st["general"]["missing"], ["TypeScript", "Git"])  # GBrain matched case-insensitively
        self.assertLess(st["have"], st["recommended"])
        dev.pop("mattpocock")  # no list: the recommended ones are in effect
        self.assertEqual(skillpacks.recommendation_status(dev)["packs"]["mattpocock"]["missing"], [])

    # -- always used, next to Superpowers ------------------------------------------------------

    def test_every_step_gets_both_packs_in_full(self):
        r = Responder()
        state = self.run_team(r)
        self.assertEqual(state["status"], "done", state["error"])
        first = {}
        for agent_id, prompt, _ in r.prompts:
            first.setdefault(agent_id, prompt)
        dev = first["developer"]
        self.assertEqual(required(dev), ["test-driven-development", "executing-plans", "using-git-worktrees",
                                         "verification-before-completion", "implement", "tdd", "codebase-design"])
        self.assertIn("## How the Superpowers skills apply inside this team", dev)
        self.assertIn("## How Matt Pocock's skills apply inside this team", dev)
        self.assertIn('<skill name="tdd" pack="mattpocock/skills" path="skills/mattpocock/tdd/SKILL.md">', dev)
        self.assertIn(LINES["tdd"], dev)
        self.assertIn(LINES["codebase-design"], dev)
        self.assertIn(LINES["grilling"], first["lead"])
        self.assertIn(LINES["to-spec"], first["lead"])
        self.assertIn(LINES["grilling"], first["architect"])
        self.assertIn(LINES["code-review"], first["qa"])
        self.assertIn(LINES["diagnosing-bugs"], first["qa"])
        self.assertIn(LINES["wizard"], first["devops"])
        report = [p for a, p, _ in r.prompts if a == "lead"][-1]
        self.assertIn(LINES["wait-what"], report)
        self.assertNotIn(LINES["tdd"], first["lead"])  # only the agent's own skills for the step
        for k in state["skills"]:
            self.assertEqual(k["missing"], [], k)
            self.assertTrue(any(n in mp.PACK.skill_names() for n in k["skills"]), k)

    def test_system_prompt_lists_both_packs(self):
        prompt = Agent(self.cfg["agents"][4], project=self.cfg["project"]).system_prompt()
        self.assertIn("### Superpowers (obra/superpowers)", prompt)
        self.assertIn("### Matt Pocock's skills (mattpocock/skills)", prompt)
        self.assertIn("- wizard:", prompt)
        self.assertNotIn("- grilling:", prompt)

    def test_missing_skill_gets_one_redo(self):
        r = Responder(comply=lambda agent_id, attempt, skill: not (agent_id == "developer" and skill == "tdd"
                                                                    and attempt == 1))
        state = self.run_team(r)
        dev = [k for k in state["skills"] if k["agent"] == "developer"][0]
        self.assertTrue(dev["retried"])
        self.assertEqual(dev["missing"], [])
        redo = [p for a, p, n in r.prompts if a == "developer" and n == 2][0]
        self.assertIn("You did not show how you applied: tdd.", redo)

    def test_enforce_is_per_pack(self):
        self.cfg["project"]["mattpocock"] = {"enabled": True, "enforce": False}
        r = Responder(comply=lambda agent_id, attempt, skill: skill not in mp.PACK.skill_names())
        state = self.run_team(r)
        self.assertFalse(any(n == 2 for *_, n in r.prompts))  # skipped mattpocock skills: recorded, no redo
        self.assertTrue(all(k["missing"] and not k["retried"] for k in state["skills"]))
        self.cfg["project"]["superpowers"] = {"enabled": True, "enforce": False}
        self.cfg["project"]["mattpocock"] = {"enabled": True, "enforce": True}
        r = Responder(comply=lambda agent_id, attempt, skill: skill not in mp.PACK.skill_names())
        self.run_team(r)
        self.assertTrue(any(n == 2 for *_, n in r.prompts))

    def test_pack_can_be_turned_off(self):
        self.cfg["project"]["mattpocock"] = {"enabled": False}
        r = Responder()
        state = self.run_team(r)
        self.assertFalse(any("Matt Pocock" in p for _, p, _ in r.prompts))
        self.assertTrue(state["skills"])  # Superpowers still on

    def test_missing_needs_the_exact_name(self):
        out = "work\n\nSkills applied:\n- implement-spec: ran the task graph\n- tdd: red then green"
        self.assertEqual(skillpacks.missing(out, ["implement", "tdd"]), ["implement"])

    # -- local, native install -----------------------------------------------------------------

    def test_hermes_gets_each_pack_in_its_own_folder(self):
        devops = copy.deepcopy(self.cfg["agents"][4])
        devops["harness"] = {"type": "hermes_local", "home": os.path.join(self.tmp, "hermes-devops")}
        notes = create_harness(devops, self.cfg["project"]).configure()
        root = os.path.join(self.tmp, "hermes-devops", "skills")
        self.assertEqual(sorted(os.listdir(os.path.join(root, "mattpocock"))), sorted(devops["mattpocock"]))
        self.assertEqual(sorted(os.listdir(os.path.join(root, "superpowers"))), sorted(devops["superpowers"]))
        self.assertTrue(os.path.exists(os.path.join(root, "mattpocock", "wizard", "template.sh")))
        self.assertIn(f"{len(devops['mattpocock'])} mattpocock skills", notes)
        self.cfg["project"]["mattpocock"] = {"enabled": False}  # a pack turned off disappears
        create_harness(devops, self.cfg["project"]).configure()
        self.assertFalse(os.path.exists(os.path.join(root, "mattpocock")))
        self.assertTrue(os.path.exists(os.path.join(root, "superpowers")))

    def test_claude_code_gets_both_packs_in_one_skills_dir(self):
        dev = copy.deepcopy(self.cfg["agents"][2])
        dev["harness"] = {"type": "claude_local", "config_dir": os.path.join(self.tmp, "claude-dev")}
        create_harness(dev, self.cfg["project"]).configure()
        skills = os.path.join(self.tmp, "claude-dev", "skills")
        self.assertEqual(sorted(os.listdir(skills)), sorted(dev["superpowers"] + dev["mattpocock"]))
        dev["mattpocock"] = ["tdd"]
        create_harness(dev, self.cfg["project"]).configure()
        self.assertEqual(sorted(os.listdir(skills)), sorted(dev["superpowers"] + ["tdd"]))


if __name__ == "__main__":
    unittest.main()
