"""Kolaborasi peer (ASK:) end-to-end + regresi bug B-3/B-4 yang dilaporkan QA.

Bug asli (QA round 1):
  B-3  `Run.delegate()` memutar `while q:` pada cabang peer TANPA batas: agent yang terus
       mencetak `ASK:` membuat run memanggil LLM tanpa henti (LLM >1000 kali, timeout).
       Ini fitur inti "semua agent bisa berkolaborasi".
  B-4  `PACKAGE_KIND["researcher"] = "code"` melabeli paket riset sebagai pekerjaan kode.

Test di sini dijalankan pada perilaku NYATA (flow.Run.execute dengan LLM scripted),
bukan pada ROUTES statis, supaya loop peer benar-benar dieksekusi.

Run: python -m unittest tests.test_peer_collaboration -v
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
    """Roster 5-agent + researcher, semua LLM direct (dijawab mock Agent.ask)."""
    cfg = copy.deepcopy(cfg)
    cfg["project"].update(gbrain={"enabled": False}, superpowers={"enabled": False},
                          mattpocock={"enabled": False}, parallel_prep=False, require_approval=[],
                          ask_ceo=True, max_peer_questions=6)
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


class PeerLoopBoundTest(unittest.TestCase):
    """B-3: `delegate()` harus berhenti walau agent terus mengeluarkan `ASK:`."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, True)
        p = mock.patch.object(flow, "RUNS_DIR", os.path.join(self.tmp, "runs"))
        p.start()
        self.addCleanup(p.stop)
        self.cfg = fixture_with_researcher(load_config(FIXTURE))

    def run_with(self, cfg, ask_fn, asker=None):
        asks = []

        def counted(agent, prompt, **kw):
            asks.append(agent.id)
            return ask_fn(agent, prompt, **kw)

        with mock.patch.object(Agent, "ask", counted):
            state = flow.Run(Team(cfg, log=quiet), "Research then build", asker=asker).execute()
        return state, asks

    def test_asks_are_bounded_when_the_agent_never_stops_asking(self):
        """Agent yang selalu mencetak `ASK: researcher` tidak boleh membuat loop tak terbatas.

        Sebelum fix: `while q:` tanpa hitungan peer -> LLM tak terbatas (QA: >1000 call, timeout).
        Sesudah: jumlah call terbatas (setara max_questions), run tetap `done`.
        """
        def always_ask(agent, prompt, **kw):
            return "still unsure\nASK: researcher\nQUESTION: again?"

        state, asks = self.run_with(self.cfg, always_ask, asker=lambda q: "just proceed")
        self.assertEqual(state["status"], "done", state.get("error"))
        # Batas nyata: peer Q&A berhenti sendiri (catatan "kept asking teammates") alih-alih
        # memutar run selamanya. Tanpa fix: loop tak terbatas (QA: >1000 call, timeout).
        # Angka longgar karena peer-answer bisa jalan PARALEL antar agent, jadi jumlahnya bisa
        # beberapa kali `max_peer_questions` — tetap jauh dari runaway (ratusan/∞).
        # CATATAN: stop ini adalah `note` (bukan `blocker`), karena docstring PeerLoop sendiri
        # menyatakan ini "not a failure of the task": task yang selesai tak boleh jadi BLOCKED.
        self.assertTrue(any("kept asking teammates" in n for n in state.get("notes", [])),
                        f"the stop must be visible as a note: {state.get('notes')}")
        self.assertFalse(any("kept asking teammates" in b for b in state["blockers"]),
                         f"the stop must NOT block a finished task: {state['blockers']}")
        self.assertLess(len(asks), 60, f"too many LLM calls: {len(asks)} (peer loop is unbounded)")

    def test_peer_turns_never_exceed_the_cap(self):
        """Batas peer harus dihormati TEPAT, tanpa overshoot.

        Regresi ditemukan Developer pada fix pertama B-3: guard `peer_budget_left() <= 0`
        diperiksa SETELAH `ask_peer()` dipanggil, padahal `ask_peer()` sudah menambah entri ke
        state["peer_questions"] DAN memanggil LLM peer. Akibatnya setiap agent yang masuk cabang
        peer menjawab satu kali melebihi batas. Dengan roster nyata (beberapa agent bertanya),
        overshoot menumpuk: cap=4 pernah menghasilkan 10 peer answer yang benar-benar dieksekusi.

        Test ini mengunci angka persisnya, bukan ambang longgar, supaya overshoot tidak bisa
        bersembunyi lagi.
        """
        def always_ask(agent, prompt, **kw):
            return "still unsure\nASK: researcher\nQUESTION: again?"

        state, _asks = self.run_with(self.cfg, always_ask, asker=lambda q: "just proceed")
        cap = self.cfg["project"]["max_peer_questions"]
        peers = state.get("peer_questions") or []
        self.assertLessEqual(len(peers), cap,
                             f"peer cap {cap} exceeded with {len(peers)} answers: {peers}")

    def test_a_single_peer_answer_closes_the_loop(self):
        """Kasus normal: satu tanya-jawab peer, lalu agent menyelesaikan tugasnya (tidak mengulang)."""
        calls = {"n": 0}

        def ask_once(agent, prompt, **kw):
            if agent.id == "developer" and "### Your teammate answered" not in prompt:
                return "I need a fact.\nASK: researcher\nQUESTION: what is the latest httpx version?"
            if agent.id == "developer":
                return "Built with httpx 0.27."
            return "ok\nVERDICT: PASS" if agent.id == "qa" else f"{agent.id} did its part"

        state, asks = self.run_with(self.cfg, ask_once)
        self.assertEqual(state["status"], "done", state.get("error"))
        self.assertEqual(len(state["peer_questions"]), 1, state.get("peer_questions"))
        entry = state["peer_questions"][0]
        self.assertEqual((entry["from"], entry["to"]), ("developer", "researcher"))
        self.assertTrue(entry["answer"], "the peer never answered")
        with open(os.path.join(state["dir"], "03-developer.md")) as f:
            self.assertIn("built with httpx 0.27", f.read().lower())


class ResearcherPackageKindTest(unittest.TestCase):
    """B-4: riset bukan pekerjaan kode."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, True)
        p = mock.patch.object(flow, "RUNS_DIR", os.path.join(self.tmp, "runs"))
        p.start()
        self.addCleanup(p.stop)
        self.cfg = fixture_with_researcher(load_config(FIXTURE))

    def test_package_kind_for_researcher_is_not_code(self):
        self.assertIn("researcher", flow.PACKAGE_KIND)
        self.assertNotEqual(flow.PACKAGE_KIND["researcher"], "code",
                            "researcher work packages must not be labelled as code")

    def test_researcher_package_is_dispatched_with_its_own_kind(self):
        """B-4 (perilaku, bukan tabel statis): `PACKAGE_KIND["researcher"]` benar-benar dipakai.

        `run_packages()` mengambil `kind = PACKAGE_KIND.get(p["agent"], "code")` dan meneruskannya
        sebagai `reply_kind` ke `delegate()` -> `write_files()` + event `files`. Tes statis di atas
        bisa tetap hijau walau tabelnya salah baca; tes ini mengunci perilaku nyata: paket
        researcher HARUS dieksekusi dengan kind selain `"code"`. RED bila penelitian dilabeli
        sebagai pekerjaan kode lagi.
        """
        plan = {"plan_summary": "Riset lalu bangun.",
                "assignments": {"architect": "Rancang", "developer": "Bangun",
                                "researcher": "Cari versi httpx", "qa": "Uji"},
                "work_packages": [
                    {"id": "p1", "title": "build", "agent": "developer",
                     "task": "build it", "depends_on": []},
                    {"id": "p2", "title": "search", "agent": "researcher",
                     "task": "find the latest httpx version", "depends_on": []}]}
        seen = {}

        def fake_delegate(self, agent_id, kind, task, prompt, reply_kind, **kw):
            seen[agent_id] = reply_kind
            return f"{agent_id} did its part"

        def ask_once(agent, prompt, **kw):
            return json.dumps(plan) if agent.id == "lead" else "ok\nVERDICT: PASS"

        with mock.patch.object(Agent, "ask", ask_once), \
                mock.patch.object(flow.Run, "delegate", fake_delegate):
            state = flow.Run(Team(self.cfg, log=quiet), "Research then build").execute()

        self.assertEqual(state["status"], "done", state.get("error"))
        self.assertIn("researcher", seen, f"researcher never dispatched: {seen}")
        self.assertNotEqual(seen["researcher"], "code",
                            f"the researcher package was run as code: {seen}")


class BackwardsCompatibilityTest(unittest.TestCase):
    """Regresi: instalasi lama (tanpa researcher) tetap berjalan; B-1/B-2 tetap benar."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, True)
        p = mock.patch.object(flow, "RUNS_DIR", os.path.join(self.tmp, "runs"))
        p.start()
        self.addCleanup(p.stop)

    def test_old_five_agent_config_still_runs_and_asks_the_ceo(self):
        """Tanpa researcher, `ASK: researcher` harus jatuh ke CEO — dan run tetap berhenti."""
        cfg = copy.deepcopy(load_config(FIXTURE))
        cfg["project"].update(gbrain={"enabled": False}, superpowers={"enabled": False},
                              mattpocock={"enabled": False}, parallel_prep=False, require_approval=[])
        for a in cfg["agents"]:
            a["harness"] = {"type": "direct"}
            a["llm"]["api_key"] = "test"

        def ask_once(agent, prompt, **kw):
            if agent.id == "developer" and "### The CEO answered" not in prompt:
                return "unknown\nASK: researcher\nQUESTION: latest httpx version?"
            if agent.id == "developer":
                return "done by developer"
            return "ok\nVERDICT: PASS" if agent.id == "qa" else f"{agent.id} output"

        asked = []

        def asker(q):
            asked.append(q)
            return "0.27"

        with mock.patch.object(Agent, "ask", ask_once):
            state = flow.Run(Team(cfg, log=quiet), "Build", asker=asker).execute()
        self.assertEqual(state["status"], "done", state.get("error"))
        self.assertEqual(len(asked), 1, "a missing peer must fall back to the CEO exactly once")
        self.assertEqual(state["questions"][0]["answer"], "0.27")

    def test_is_skipped_and_has_tools_regression(self):
        """B-1/B-2 butuh tes permanen: keduanya tanpa tes sebelumnya."""
        from babd.harness.base import Harness
        from babd.harness.others import Process

        run = object.__new__(flow.Run)
        run.skip = {"researcher"}
        self.assertTrue(run.is_skipped("researcher"))
        self.assertFalse(run.is_skipped("devops"))
        run.skip = "researcher"  # bentuk str
        self.assertTrue(run.is_skipped("researcher"))
        del run.skip
        self.assertFalse(run.is_skipped("researcher"))

        llm = {"llm": {"provider": "Custom", "api": "openai", "model": "m"}}
        self.assertTrue(Process({**llm, "id": "researcher",
                                 "harness": {"type": "process", "command": "scripts/researcher_adapter.py"}}).has_tools)
        self.assertFalse(Process({**llm, "id": "x", "harness": {"type": "process"}}).has_tools)
        self.assertFalse(Harness.has_tools)


if __name__ == "__main__":
    unittest.main()
