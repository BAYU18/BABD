"""E2E kolaborasi researcher (Task 5 plan) — dijalankan pada perilaku NYATA.

Ditulis ulang oleh Developer pada fix-round 1. Versi awal QA TIDAK PERNAH hijau: 4 dari 6
test gagal karena salah membaca kontrak kode (bukan karena bug produksi). Yang dikoreksi:

  C-1  `flow.ROUTES` adalah **set of tuple**, bukan dict → `ROUTES["team"]` TypeError.
       Dipakai `flow.ROUTES` apa adanya lewat keanggotaan tuple.
  C-2  `ask_peer` memanggil `self.work(target, prompt, task, "peer_answer", ...)` — `kind`
       adalah argumen **posisional ke-4**, bukan keyword `reply_kind`. Mock lama membaca
       `kw.get("reply_kind")` sehingga selalu None.
  C-3  Rencana Team Lead adalah **JSON** (`{"assignments": {...}, "work_packages": [...]}`),
       bukan prosa "PLAN\\n1. developer: ...". Prosa tidak pernah memicu dispatch researcher,
       jadi test (a)/(d)/RF5 gagal karena fixture-nya salah bentuk.

Coverage (sesuai plan Task 5):
  (a) researcher menerima step/work-package dari Team Lead
  (b) `parse_question("ASK: researcher\\nQUESTION: ...")` -> ask == ["researcher"]
  (c) `ask_peer()` merutekan pertanyaan ke researcher dan menjawab balik ke penanya
  (d) board (`state["agents"]`) memuat researcher
  (e) `report_md()` memuat researcher
  RF1  fixture 5 agent (tanpa researcher) tidak melempar FlowError
  RF5  plan Team Lead yang menugaskan researcher tidak KeyError dan benar ter-dispatch

Run: python -m unittest tests.test_researcher_e2e -v
"""
import copy
import json
import os
import shutil
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from babd import flow  # noqa: E402
from babd.config import load_config  # noqa: E402
from babd.team import Agent, Team  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
FIXTURE = os.path.join(HERE, "fixtures", "agents.json")


def quiet(*_a, **_k):
    return None


def fixture_with_researcher(cfg):
    """Roster nyata + researcher, semua LLM direct supaya mock `Agent.ask` yang menjawab."""
    cfg = copy.deepcopy(cfg)
    cfg["project"].update(gbrain={"enabled": False}, superpowers={"enabled": False},
                          mattpocock={"enabled": False}, parallel_prep=False, require_approval=[],
                          ask_ceo=False, max_peer_questions=6)
    cfg["agents"].append({
        "id": "researcher", "name": "RESEARCHER", "short_name": "Researcher", "color": "#c084fc",
        "main_task": ["RESEARCH", "INTERNET"],
        "sub_tasks": [{"name": "Search the web", "state": "todo"}],
        "llm": {"provider": "Custom", "api": "openai", "model": "m", "base_url": "http://localhost/v1"},
        "harness": {"type": "direct"}, "permissions": "workspace"})
    for a in cfg["agents"]:
        a["harness"] = {"type": "direct"}
        a["llm"]["api_key"] = "test"
    return cfg


class ResearcherCollaborationE2ETest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, True)
        p = mock.patch.object(flow, "RUNS_DIR", os.path.join(self.tmp, "runs"))
        p.start()
        self.addCleanup(p.stop)
        self.cfg = fixture_with_researcher(load_config(FIXTURE))

    # -- (b) parsing ----------------------------------------------------------------
    def test_ask_parses_to_the_researcher(self):
        q = flow.parse_question("I am unsure.\nASK: researcher\nQUESTION: what is the latest httpx version?")
        self.assertEqual(q["ask"], ["researcher"], q)
        self.assertEqual(q["question"], "what is the latest httpx version?")

    # -- (c) two-way peer routing, on real Run.ask_peer -----------------------------
    def test_peer_question_is_routed_to_researcher_and_answered_back(self):
        team = Team(self.cfg, log=quiet)
        run = flow.Run(team, "Research", asker=lambda q: "proceed")
        seen = []

        # `self.work(agent_id, prompt, task, kind, ...)`: `kind` adalah argumen posisional ke-4.
        def fake_work(self, agent_id, prompt, task, kind, *a, **kw):
            seen.append((agent_id, prompt, kind))
            if agent_id == "researcher":
                return "RESEARCHER answered:\nhttpx 0.27.0 (source: https://pypi.org/project/httpx/)"
            return "ok"

        with mock.patch.object(flow.Run, "work", fake_work):
            answer = run.ask_peer("developer", {"ask": ["researcher"], "question": "latest httpx version?"})

        peers_asked = [w for w in seen if w[0] == "researcher"]
        self.assertEqual(len(peers_asked), 1, f"researcher was not asked exactly once: {seen}")
        self.assertEqual(peers_asked[0][2], "peer_answer")
        self.assertIn("httpx version?", peers_asked[0][1])
        self.assertIn("httpx 0.27.0", answer or "")
        self.assertEqual(len(run.state["peer_questions"]), 1)
        entry = run.state["peer_questions"][0]
        self.assertEqual((entry["from"], entry["to"]), ("developer", "researcher"))
        self.assertIn("httpx 0.27.0", entry["answer"])

    # -- (a) + (d) the researcher takes a work package and shows up on the board -----
    def test_researcher_takes_a_step_and_appears_on_the_board(self):
        """Kontrak nyata: plan JSON dengan `work_packages` yang menugaskan researcher."""
        plan = {"plan_summary": "Riset lalu bangun.",
                "assignments": {"architect": "Rancang", "developer": "Bangun",
                                "researcher": "Cari versi httpx terbaru", "qa": "Uji"},
                "work_packages": [
                    {"id": "p1", "title": "build", "agent": "developer",
                     "task": "build it", "depends_on": []},
                    {"id": "p2", "title": "search", "agent": "researcher",
                     "task": "find the latest httpx version", "depends_on": []}]}
        seen = []

        def ask_once(agent, prompt, **kw):
            seen.append(agent.id)
            if agent.id == "lead":
                return json.dumps(plan)
            if agent.id == "researcher":
                return "httpx 0.27.0 is the latest (https://pypi.org/project/httpx/)\nVERDICT: PASS"
            if agent.id == "qa":
                return "tested\nVERDICT: PASS"
            return f"{agent.id} did its part"

        with mock.patch.object(Agent, "ask", ask_once):
            state = flow.Run(Team(self.cfg, log=quiet), "Research then build").execute()

        self.assertEqual(state["status"], "done", state.get("error"))
        self.assertIn("researcher", state["agents"], "the researcher must be part of the run board")
        self.assertIn("researcher", seen, f"the researcher never received a work package: {seen}")
        pkg_agents = [p.get("agent") for p in state.get("packages", [])]
        self.assertIn("researcher", pkg_agents, f"researcher missing from packages: {pkg_agents}")

    # -- (e) report mentions the researcher ---------------------------------------
    def test_report_lists_the_researcher_after_a_real_run(self):
        """Seam nyata: `reports.markdown` menampilkan agent lewat tabel Steps, jadi researcher
        harus benar-benar mengambil step dulu (state kosong tidak akan memuat nama agent)."""
        from babd import reports
        plan = {"plan_summary": "Riset lalu bangun.",
                "assignments": {"architect": "Rancang", "developer": "Bangun",
                                "researcher": "Cari versi httpx", "qa": "Uji"},
                "work_packages": [
                    {"id": "p1", "title": "build", "agent": "developer",
                     "task": "build it", "depends_on": []},
                    {"id": "p2", "title": "search", "agent": "researcher",
                     "task": "find the latest httpx version", "depends_on": []}]}

        def ask_once(agent, prompt, **kw):
            if agent.id == "lead":
                return json.dumps(plan)
            if agent.id == "qa":
                return "tested\nVERDICT: PASS"
            return f"{agent.id} did its part"

        team = Team(self.cfg, log=quiet)
        with mock.patch.object(Agent, "ask", ask_once):
            state = flow.Run(team, "Research then build").execute()
        md = reports.markdown(state, [], {a.id: a.name for a in team.agents})
        self.assertIn("Researcher", md, "the researcher must appear in the run report")
        self.assertIn("research", md)

    def test_roles_and_routes_know_the_researcher(self):
        team = Team(self.cfg, log=quiet)
        self.assertIn("researcher", flow.specialist_roles(team))
        # C-1: ROUTES adalah set of tuple, bukan dict.
        self.assertIn(("developer", "researcher"), flow.ROUTES)
        self.assertIn(("researcher", "qa"), flow.ROUTES)
        self.assertIn("internet", flow.Run.PEER_WHO["researcher"])

    def test_activity_log_time_is_local_server_wall_clock(self):
        """Ganti pengganti permanen untuk skrip `.mjs` yang tidak pernah ada di repo ini
        (QA benar: `verify_live_wib.mjs` tidak ada di seluruh riwayat git). Yang benar-benar
        dijanjikan kode: `flow.now()` adalah ISO waktu-lokal server, dan server ini WIB.
        Diuji lewat seam `flow.now`, bukan lewat skrip eksternal."""
        import datetime
        stamp = flow.now()
        self.assertNotIn("+", stamp)  # waktu lokal (naive), bukan UTC ber-zona
        parsed = datetime.datetime.fromisoformat(stamp)
        local = datetime.datetime.now()
        self.assertLess(abs((parsed - local).total_seconds()), 5,
                        f"flow.now() harus jam dinding lokal server: {stamp} vs {local.isoformat()}")

    # -- RF1: instalasi lama (5 agent, tanpa researcher) tetap jalan --------------
    def test_old_five_agent_config_has_no_flow_error(self):
        cfg = copy.deepcopy(load_config(FIXTURE))
        cfg["project"].update(gbrain={"enabled": False}, superpowers={"enabled": False},
                              mattpocock={"enabled": False}, parallel_prep=False, require_approval=[])
        for a in cfg["agents"]:
            a["harness"] = {"type": "direct"}
            a["llm"]["api_key"] = "test"

        def ask_once(agent, prompt, **kw):
            if agent.id == "lead":
                return json.dumps({"plan_summary": "Bangun.",
                                   "assignments": {"architect": "Rancang", "developer": "Bangun",
                                                   "qa": "Uji"}, "work_packages": []})
            return "ok\nVERDICT: PASS" if agent.id == "qa" else f"{agent.id} output"

        with mock.patch.object(Agent, "ask", ask_once):
            state = flow.Run(Team(cfg, log=quiet), "Build").execute()
        self.assertNotEqual(state["status"], "failed",
                            f"a 5-agent install must not break: {state.get('error')}")
        self.assertNotIn("researcher", state["agents"])

    # -- RF5: a lead plan that names the researcher must not KeyError -------------
    def test_lead_plan_naming_researcher_does_not_keyerror(self):
        """C-3: plan JSON yang menugaskan researcher lewat `assignments` tidak KeyError."""
        plan = {"plan_summary": "Riset lalu bangun.",
                "assignments": {"architect": "design", "developer": "build",
                                "researcher": "search the web", "qa": "test", "devops": "deploy"},
                "work_packages": [
                    {"id": "p1", "title": "build", "agent": "developer",
                     "task": "build it", "depends_on": []},
                    {"id": "p2", "title": "search", "agent": "researcher",
                     "task": "search the web", "depends_on": []}]}
        seen = []

        def ask_once(agent, prompt, **kw):
            seen.append(agent.id)
            if agent.id == "lead":
                return json.dumps(plan)
            return "ok\nVERDICT: PASS"

        with mock.patch.object(Agent, "ask", ask_once):
            state = flow.Run(Team(self.cfg, log=quiet), "Research then build").execute()
        self.assertEqual(state["status"], "done", state.get("error"))
        self.assertIn("researcher", seen, "the researcher named in the plan was never dispatched")


if __name__ == "__main__":
    unittest.main()
