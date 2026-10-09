"""Tes agent "researcher": keanggotaan roster, harness process, adapter lokal, dan dashboard.

Run: python -m unittest tests.test_researcher -v
"""
import copy
import json
import os
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import shutil  # noqa: E402

from babd import flow, harness  # noqa: E402
from babd.config import ROOT, load_config  # noqa: E402
from babd.team import Team  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
FIXTURE = os.path.join(HERE, "fixtures", "agents.json")   # 5 agent, tanpa researcher
REAL_AGENTS_JSON = os.path.join(os.path.dirname(HERE), "agents.json")
WORKTREE = os.path.dirname(HERE)


def quiet(*_a, **_k):
    return None


class ResearcherRosterTest(unittest.TestCase):
    """Roster: researcher dikenal, tapi instalasi lama tanpa researcher tetap jalan."""

    def test_roles_include_researcher(self):
        self.assertIn("researcher", flow.ROLES)
        self.assertIn("researcher", flow.SKIPPABLE)
        self.assertTrue(flow.Run.PEER_WHO.get("researcher", "").strip())
        self.assertIn("researcher", flow.ASK_INSTRUCTION)
        self.assertIn("researcher", flow.SPECIALIST_DUTY)
        self.assertIn("researcher", flow.PACKAGE_KIND)

    def test_old_config_without_researcher_still_works(self):
        cfg = copy.deepcopy(load_config(FIXTURE))       # fixture 5 agent, tanpa researcher
        team = Team(cfg, log=quiet)
        self.assertEqual(flow.specialist_roles(team),
                         ["architect", "developer", "qa", "devops"])

    def test_config_with_researcher_appends_it(self):
        cfg = copy.deepcopy(load_config(REAL_AGENTS_JSON))
        team = Team(cfg, log=quiet)
        self.assertEqual(flow.specialist_roles(team),
                         ["architect", "developer", "qa", "devops", "researcher"])

    def test_new_agent_is_a_specialist_not_the_lead(self):
        cfg = copy.deepcopy(load_config(REAL_AGENTS_JSON))
        team = Team(cfg, log=quiet)
        self.assertEqual(team.lead.id, "lead")
        self.assertIn("researcher", [a.id for a in team.specialists])

    def test_peer_question_routes_to_researcher_two_ways(self):
        # Kolaborasi dua arah: developer boleh bertanya ke researcher, researcher boleh
        # melaporkan ke lead. Keduanya harus ada di tabel ROUTES.
        question = "ASK: researcher\nQUESTION: what is the latest httpx version?"
        q = flow.parse_question(question)
        self.assertIsNotNone(q)
        self.assertEqual(q["ask"], ["researcher"])
        self.assertIn(("developer", "researcher"), flow.ROUTES)
        self.assertIn(("researcher", "lead"), flow.ROUTES)

    def test_researcher_persona_prompt_mentions_internet_and_sources(self):
        cfg = copy.deepcopy(load_config(REAL_AGENTS_JSON))
        team = Team(cfg, log=quiet)
        prompt = team.by_id["researcher"].system_prompt().lower()
        self.assertIn("internet", prompt)
        self.assertIn("source", prompt)

    def test_plan_descriptions_do_not_keyerror_on_researcher(self):
        # LANDMINE: flow.py membangun deskripsi alur dari lookup dict per role; role baru
        # harus punya entri (atau fallback) supaya plan tidak KeyError.
        for role in flow.ROLES[1:]:
            self.assertIn(role, flow.SPECIALIST_DUTY, f"role {role!r} has no plan description")
            self.assertIn(role, flow.PACKAGE_KIND, f"role {role!r} has no package kind")

    def test_researcher_is_skippable_and_task_options_accepts_it(self):
        opts = flow.task_options({"skip": ["researcher"]}, agent_ids={"lead", "researcher"})
        self.assertEqual(opts["skip"], ["researcher"])
        with self.assertRaises(flow.FlowError):
            flow.task_options({"skip": ["nobody"]})


if __name__ == "__main__":
    unittest.main()
