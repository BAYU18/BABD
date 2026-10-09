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

    def test_duckduckgo_provider_does_not_die_on_the_ddgs_import(self):
        """B-12 (QA round-3): dengan DuckDuckGo sebagai provider, adapter harus BISA memakai
        retriever-nya, tanpa bergantung pada patch lokal di vendor.

        Akar bug yang dibuktikan QA: `gpt_researcher/retrievers/duckduckgo/duckduckgo.py`
        memanggil `check_pkg('ddgs')` di `__init__` dan hanya bisa mengimpor paket BARU `ddgs`,
        sedangkan venv vendor memasang paket LAMA `duckduckgo_search` (>=4.1.1, yang memang
        dideklarasikan `pyproject.toml` vendor ini). Yang melempar adalah saat retriever
        di-INSTANSIASI, bukan saat modulnya diimpor - itu sebabnya sinyal `rc!=0` di adapter
        saja tidak cukup.

        Tes ini memanggil langsung jalur itu melalui fungsi adapter `ensure_ddg_shim()`
        (di-inject sebagai alias `ddgs` bila perlu), lalu meng-instansiasi retriever vendor
        SUNGGUHAN di venv vendor. Tanpa shim, `ImportError: Unable to import ddgs`.
        """
        prompt = "RESEARCHER\n\n---\n\nwhat is python"
        e = {k: v for k, v in os.environ.items()
             if not k.startswith(("BABD_LLM", "OPENAI_", "RESEARCHER_"))}
        e.update({"PATH": os.environ.get("PATH", ""), "RESEARCHER_PROVIDER": "duckduckgo",
                  "RESEARCHER_ALLOW_DUCKDUCKGO": "1"})

        # 1) Tabel provider: permintaan eksplisit `duckduckgo` harus dihormati.
        code = ("import importlib.util, sys; "
                "sys.argv = ['researcher_adapter.py']; "
                "spec = importlib.util.spec_from_file_location('adapter', %r); "
                "m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m); "
                "print(m.search_provider()[0])" % self.ADAPTER)
        p = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True,
                           env=e, timeout=60)
        self.assertEqual(p.stdout.strip(), "duckduckgo",
                         f"provider tidak terdeteksi: stdout={p.stdout!r} stderr={p.stderr!r}")

        # 2) Jalur NYATA: lewat `real_result()` (kode produksi) yang di dalamnya harus
        #    mengaktifkan shim sebelum library memuat retriever DuckDuckGo. Retriever-nya
        #    di-instansiasi langsung di venv vendor - itu titik yang melempar
        #    `ImportError: Unable to import ddgs` sebelum perbaikan.
        venv_python = os.path.join(WORKTREE, ".babd", "researcher", "venv", "bin", "python")
        if not os.path.exists(venv_python):
            self.skipTest("venv vendor tidak ada di mesin ini (jalur offline)")

        probe = (
            "import importlib.util, sys, json\n"
            "spec = importlib.util.spec_from_file_location('adapter', %r)\n"
            "m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)\n"
            # `real_result` memanggil gpt-researcher; kita hentikan tepat SEBELUM library
            # benar-benar melakukan riset (tanpa jaringan, tanpa LLM) tapi SESUDAH shim
            # diaktifkan, lalu instansiasi retriever DuckDuckGo yang asli.
            "import types, gpt_researcher\n"
            "def fake_get_researcher(*a, **k):\n"
            "    import gpt_researcher.retrievers.duckduckgo.duckduckgo as dd\n"
            "    dd.Duckduckgo('probe')\n"
            "    raise RuntimeError('probe-stop')\n"
            "gpt_researcher.GPTResearcher = fake_get_researcher\n"
            "try:\n"
            "    m.real_result('probe', 'duckduckgo', 'duckduckgo')\n"
            "except RuntimeError as e:\n"
            "    if 'probe-stop' not in str(e):\n"
            "        raise\n"
            "print(json.dumps({'ok': True}))\n"
        ) % self.ADAPTER
        p = subprocess.run([venv_python, "-c", probe], capture_output=True, text=True,
                           env=e, timeout=120)
        self.assertNotIn("Unable to import ddgs", p.stderr,
                         f"retriever DuckDuckGo mati pada impor: {p.stderr!r}")
        self.assertEqual(p.returncode, 0,
                         f"instansiasi retriever gagal: stdout={p.stdout!r} stderr={p.stderr!r}")
        self.assertTrue(json.loads(p.stdout.strip().splitlines()[-1])["ok"])

    def test_adapter_loads_the_babd_env_file_for_the_llm(self):
        """B-13 (QA round-3): di jalur manual/`--json` tidak ada harness yang mengisi
        `BABD_LLM_*`; nilai itu hidup di `.env` BABD (dengan nama dari `agents.json`, mis.
        `KEY1`). Adapter harus memuat `.env` itu lebih dulu, TANPA menimpa variabel yang
        sudah di-set (harness selalu menang).

        RED sebelum perbaikan: `.env` diabaikan sepenuhnya, sehingga adapter mati dengan
        `OpenAIError: Missing credentials` meski key sudah ada di `.env`.
        """
        env_file = os.path.join(self._tmp, ".env")
        with open(env_file, "w") as f:
            f.write("KEY1=sk-from-dotenv\nBABD_LLM_BASE_URL=http://127.0.0.1:9/v1\n"
                    "BABD_LLM_MODEL=model-from-dotenv\n")
        code = ("import importlib.util, sys, os, json; "
                "sys.argv = ['researcher_adapter.py']; "
                "spec = importlib.util.spec_from_file_location('adapter', %r); "
                "m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m); "
                "m.load_babd_env(%r); "
                "print(json.dumps({k: os.environ.get(k) for k in "
                "('KEY1', 'BABD_LLM_BASE_URL', 'BABD_LLM_MODEL')}))"
                % (self.ADAPTER, env_file))
        e = {k: v for k, v in os.environ.items()
             if not k.startswith(("BABD_LLM", "OPENAI_", "KEY1"))}
        e["PATH"] = os.environ.get("PATH", "")
        e["RESEARCHER_ENV_FILE"] = env_file
        p = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True,
                           env=e, timeout=60)
        self.assertEqual(p.returncode, 0, p.stderr)
        data = json.loads(p.stdout.strip().splitlines()[-1])
        self.assertEqual(data.get("KEY1"), "sk-from-dotenv")
        self.assertEqual(data.get("BABD_LLM_BASE_URL"), "http://127.0.0.1:9/v1")
        self.assertEqual(data.get("BABD_LLM_MODEL"), "model-from-dotenv")

        # Efek NYATA yang penting: `real_result()` sendiri harus memuat `.env`, meresolusi nama
        # key dari agents.json (KEY1 -> OPENAI_API_KEY), sehingga adapter tidak lagi mati
        # `OpenAIError: Missing credentials` di jalur manual. Probe menghentikan riset sebelum
        # jaringan dengan mengganti GPTResearcher, lalu memeriksa lingkungannya. Config asli
        # dipakai supaya `api_key_env: KEY1` benar-benar diuji.
        probe = (
            "import importlib.util, sys, os, json\n"
            "spec = importlib.util.spec_from_file_location('adapter', %r)\n"
            "m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)\n"
            "import gpt_researcher\n"
            "def fake_get_researcher(*a, **k):\n"
            "    raise RuntimeError('probe-stop')\n"
            "gpt_researcher.GPTResearcher = fake_get_researcher\n"
            "try:\n"
            "    m.real_result('probe', 'searxng', 'http://127.0.0.1:1')\n"
            "except RuntimeError:\n"
            "    pass\n"
            "print(json.dumps({k: os.environ.get(k) for k in "
            "('OPENAI_API_KEY', 'OPENAI_BASE_URL')}))\n"
        ) % self.ADAPTER
        # Probe butuh vendor ada; kalau tidak, lewati (jalur offline).
        venv_python = os.path.join(WORKTREE, ".babd", "researcher", "venv", "bin", "python")
        if os.path.exists(venv_python):
            e2 = dict(e)
            e2["RESEARCHER_CONFIG"] = REAL_AGENTS_JSON
            p = subprocess.run([venv_python, "-c", probe], capture_output=True, text=True,
                               env=e2, timeout=120)
            eff = json.loads(p.stdout.strip().splitlines()[-1])
            self.assertEqual(eff.get("OPENAI_API_KEY"), "sk-from-dotenv",
                             f"real_result tidak memuat .env / tidak meresolusi api_key_env: {p.stderr!r}")
            self.assertEqual(eff.get("OPENAI_BASE_URL"), "http://127.0.0.1:9/v1")

        # Variabel yang sudah ada di lingkungan TIDAK boleh ditimpa `.env` (harness menang).
        e["BABD_LLM_MODEL"] = "model-from-harness"
        p = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True,
                           env=e, timeout=60)
        data = json.loads(p.stdout.strip().splitlines()[-1])
        self.assertEqual(data.get("BABD_LLM_MODEL"), "model-from-harness")

    def test_fast_and_smart_llm_use_provider_colon_model(self):
        """B-15 (QA round-3): gpt-researcher mem-`parse_llm` FAST_LLM/SMART_LLM sebagai
        `'<provider>:<model>'` dan MELEMPAR `ValueError` bila tidak ada titik dua. Adapter dulu
        menyalin `BABD_LLM_MODEL` mentah (`ag-hermes`), sehingga riset selalu gagal
        `ValueError: Set SMART_LLM or FAST_LLM = '<llm_provider>:<llm_model>'` bahkan setelah
        kredensial benar.

        RED sebelum perbaikan: FAST_LLM/SMART_LLM = 'ag-hermes' (tanpa titik dua).
        """
        env_file = os.path.join(self._tmp, ".env")
        with open(env_file, "w") as f:
            f.write("KEY1=sk-x\n")
        probe = (
            "import importlib.util, sys, os, json\n"
            "spec = importlib.util.spec_from_file_location('adapter', %r)\n"
            "m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)\n"
            "import gpt_researcher\n"
            "def fake(*a, **k):\n"
            "    raise RuntimeError('probe-stop')\n"
            "gpt_researcher.GPTResearcher = fake\n"
            "try:\n"
            "    m.real_result('probe', 'searxng', 'http://127.0.0.1:1')\n"
            "except RuntimeError:\n"
            "    pass\n"
            "from gpt_researcher.config.config import Config\n"
            "print(json.dumps({k: os.environ.get(k) for k in ('FAST_LLM', 'SMART_LLM')}))\n"
            "Config.parse_llm(os.environ.get('SMART_LLM'))\n"
            "Config.parse_llm(os.environ.get('FAST_LLM'))\n"
        ) % self.ADAPTER
        venv_python = os.path.join(WORKTREE, ".babd", "researcher", "venv", "bin", "python")
        if not os.path.exists(venv_python):
            self.skipTest("venv vendor tidak ada di mesin ini (jalur offline)")
        e = {k: v for k, v in os.environ.items()
             if not k.startswith(("BABD_LLM", "OPENAI_", "KEY1", "FAST_LLM", "SMART_LLM"))}
        e.update({"PATH": os.environ.get("PATH", ""), "RESEARCHER_ENV_FILE": env_file,
                  "RESEARCHER_CONFIG": REAL_AGENTS_JSON})
        p = subprocess.run([venv_python, "-c", probe], capture_output=True, text=True,
                           env=e, timeout=120)
        self.assertNotIn("ValueError", p.stderr,
                         f"FAST_LLM/SMART_LLM tidak dalam format provider:model: {p.stderr!r}")
        self.assertEqual(p.returncode, 0, f"stdout={p.stdout!r} stderr={p.stderr!r}")
        data = json.loads(p.stdout.strip().splitlines()[-1])
        for key in ("FAST_LLM", "SMART_LLM"):
            self.assertIn(":", data.get(key, ""),
                          f"{key} harus '<provider>:<model>', dapat {data.get(key)!r}")
            self.assertTrue(data[key].endswith("ag-hermes"),
                            f"{key} harus berakhir nama model dari agents.json: {data[key]!r}")


if __name__ == "__main__":
    unittest.main()
