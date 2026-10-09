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


class ResearcherAdapterTest(unittest.TestCase):
    """Adapter adalah program di seam process-harness: prompt di stdin, JSON di stdout.

    Diuji sebagai black box (subprocess), bukan dengan memanggil fungsi internalnya.
    Aturan terpenting: adapter tidak pernah mengarang sumber. Bila tidak ada search
    provider, ia gagal dengan exit code 2 dan pesan yang jelas.
    """

    ADAPTER = os.path.join(WORKTREE, "scripts", "researcher_adapter.py")

    def setUp(self):
        self._tmp = tempfile.mkdtemp(prefix="researcher-test-")
        self._fake_home = os.path.join(self._tmp, "fake-venv-home")
        self.addCleanup(shutil.rmtree, self._tmp, ignore_errors=True)

    def run_adapter(self, stdin_text, env=None, args=("--json",), timeout=60):
        e = {k: v for k, v in os.environ.items() if not k.startswith(("BABD_LLM", "OPENAI_", "RESEARCHER_"))}
        e["PATH"] = os.environ.get("PATH", "")
        e.update(env or {})
        return subprocess.run([sys.executable, self.ADAPTER, *args], input=stdin_text,
                              capture_output=True, text=True, env=e, timeout=timeout)

    def test_adapter_exists_and_is_executable(self):
        self.assertTrue(os.path.isfile(self.ADAPTER), "scripts/researcher_adapter.py is missing")
        self.assertTrue(os.access(self.ADAPTER, os.X_OK), "adapter must be executable for the process harness")

    def test_fake_mode_returns_the_agreed_json_shape(self):
        prompt = "You are the RESEARCHER.\n\n---\n\nwhat is the latest httpx version?"
        p = self.run_adapter(prompt, env={"RESEARCHER_FAKE": "1"})
        self.assertEqual(p.returncode, 0, p.stderr)
        first = p.stdout.split("\n---\n", 1)[0]
        data = json.loads(first)
        self.assertEqual(data["query"], "what is the latest httpx version?")
        self.assertTrue(data["answer"].strip())
        self.assertIsInstance(data["sources"], list)
        self.assertTrue(data["local"])
        self.assertIn("---", p.stdout)  # a short text summary follows the JSON

    def test_no_search_provider_fails_loudly_instead_of_inventing_sources(self):
        prompt = "You are the RESEARCHER.\n\n---\n\nsome question"
        p = self.run_adapter(prompt, env={})          # no SearXNG, no DuckDuckGo opt-in
        self.assertEqual(p.returncode, 2, f"stdout={p.stdout!r} stderr={p.stderr!r}")
        self.assertIn("no search provider", (p.stderr + p.stdout).lower())
        self.assertNotIn('"sources": [{"', p.stdout)   # never fake a finding

    def test_query_is_taken_after_the_last_prompt_separator(self):
        prompt = "SYSTEM persona with an --- in it\n\n---\n\nthe real question"
        p = self.run_adapter(prompt, env={"RESEARCHER_FAKE": "1"})
        data = json.loads(p.stdout.split("\n---\n", 1)[0])
        self.assertEqual(data["query"], "the real question")

    def test_plain_text_mode_prints_a_readable_report(self):
        prompt = "RESEARCHER\n\n---\n\nwho wrote bash?"
        p = self.run_adapter(prompt, env={"RESEARCHER_FAKE": "1"}, args=())
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertIn("who wrote bash?", p.stdout)
        self.assertNotIn('{"query"', p.stdout)

    def test_vendored_gpt_researcher_interpreter_is_used_when_present(self):
        """Adapter dipanggil sebagai `python scripts/researcher_adapter.py`, jadi `import
        gpt_researcher` TIDAK menemukan library yang di-vendor (.babd/researcher/venv). Adapter
        harus mengeksekusi ulang dirinya dengan interpreter venv itu. Kontraknya: mode
        `--which-python` melaporkan interpreter yang akan dipakai (dan tidak menyentuh jaringan)."""
        venv_python = os.path.join(WORKTREE, ".babd", "researcher", "venv", "bin", "python")
        p = self.run_adapter("", env={}, args=("--which-python",))
        self.assertEqual(p.returncode, 0, p.stderr)
        if os.path.exists(venv_python):                      # vendor sudah disiapkan di mesin ini
            self.assertEqual(p.stdout.strip(), venv_python)
        else:
            self.assertEqual(p.stdout.strip(), sys.executable)

    def test_import_error_message_points_at_the_setup_script(self):
        """Tanpa venv/vendor, adapter harus gagal dengan pesan yang menyebut cara memperbaikinya,
        bukan dengan traceback mentah.

        Determinisme: jalur ini tidak boleh bergantung pada ada/tidaknya `.babd/researcher/venv`
        di mesin (dir itu ter-gitignore, jadi hasilnya beda antar mesin dan tesnya selalu SKIP di
        mesin yang vendornya sudah dipasang - persis catatan QA round-2). Kita paksa dengan
        `RESEARCHER_HOME` ke direktori kosong, seperti yang sudah dipakai test re-exec di atas.
        """
        empty_home = os.path.join(self._tmp, "no-vendor-home")
        os.makedirs(empty_home, exist_ok=True)
        prompt = "RESEARCHER\n\n---\n\nsome question"
        p = self.run_adapter(prompt, env={"RESEARCHER_SEARXNG_URL": "http://127.0.0.1:8888",
                                          "RESEARCHER_HOME": empty_home})
        self.assertEqual(p.returncode, 2, f"stdout={p.stdout!r} stderr={p.stderr!r}")
        self.assertIn("researcher_setup.sh", (p.stderr + p.stdout))

    def test_query_survives_the_venv_reexec(self):
        """Regresi: `reexec_if_needed()` memanggil `os.execve`, dan proses baru mewarisi stdin
        yang SUDAH habis dikonsumsi proses lama (`sys.stdin.read()` di `main()`). Kalau prompt
        hanya hidup di stdin, proses baru membaca string kosong dan keluar rc=3
        ("no question in the prompt") — agent tampak rusak padahal search provider-nya ada.

        Test ini memakai venv tiruan berisi interpreter nyata (symlink ke sys.executable)
        sehingga jalur re-exec benar-benar diambil, TANPA butuh gpt-researcher terpasang.
        Adapter harus tetap membawa pertanyaannya melewati execve; kegagalan sesudah itu
        boleh rc=2 (provider import), yang penting bukan rc=3 "stdin was empty"."""
        venv_bin = os.path.join(self._fake_home, "venv", "bin")
        os.makedirs(venv_bin, exist_ok=True)
        fake_python = os.path.join(venv_bin, "python")
        if not os.path.exists(fake_python):
            os.symlink(sys.executable, fake_python)      # interpreter nyata, prefix berbeda
        prompt = "SYSTEM persona\n\n---\n\nthe question that must survive re-exec"
        p = self.run_adapter(prompt, env={"RESEARCHER_SEARXNG_URL": "http://127.0.0.1:8899",
                                          "RESEARCHER_HOME": self._fake_home})
        combined = (p.stderr + p.stdout).lower()
        self.assertNotIn("stdin was empty", combined,
                         f"prompt lost across re-exec: stdout={p.stdout!r} stderr={p.stderr!r}")
        self.assertNotEqual(p.returncode, 3,
                            f"rc=3 means the re-exec lost the prompt: stdout={p.stdout!r} stderr={p.stderr!r}")
        # Setelah re-exec, adapter sampai ke tahap berikutnya (provider/library), bukan
        # kembali mengeluh prompt kosong. rc=2 = provider tidak siap, itu perilaku jujur.
        self.assertEqual(p.returncode, 2, f"stdout={p.stdout!r} stderr={p.stderr!r}")


if __name__ == "__main__":
    unittest.main()
