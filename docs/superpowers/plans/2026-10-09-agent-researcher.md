# Agent "researcher" (gpt-researcher lokal) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Tambah agent keenam `researcher` ke BABD yang mencari di internet lewat gpt-researcher yang di-vendor lokal, bisa dipanggil semua agent, dan muncul di semua dashboard.

**Architecture:** `researcher` adalah specialist biasa (bukan stage baru). Ia memakai harness `process` yang **sudah ada** di BABD: BABD menulis prompt ke stdin, adapter membaca stdin, memanggil gpt-researcher sebagai library lokal, dan mencetak JSON + ringkasan ke stdout. Lima titik `ROLES[1:]` diganti satu helper `specialist_roles(team)` supaya instalasi lama (tanpa researcher) tetap jalan.

**Tech Stack:** Python 3 (BABD), `unittest` (suite BABD memakai `python -m unittest`), harness `process` + gpt-researcher sebagai library Python yang di-vendor.

**Spec:** `docs/superpowers/specs/2026-10-09-agent-researcher-design.md`

## Global Constraints

- Semua path relatif terhadap worktree `/home/serverbot/aidev/workspace/worktrees/babd-self/20261009-093920`.
- `agents.json`: researcher ditaruh **setelah `devops`** (setelah elemen terakhir array `agents`). `Team.__init__` (`babd/team.py:213`) memakai `agents[0]` sebagai lead.
- **`command` harness `process` boleh ditulis relatif** di `agents.json`, dan `Process.command_path()` me-resolusi terhadap `ROOT` (`os.path.join(ROOT, command)`) mengikuti pola `cwd` (`babd/harness/base.py:144-147`) dan `config_dir` (`babd/harness/others.py:57-58`). Ini wajib karena `ensure_command` (`babd/harness/tools.py:200-205`) hanya menerima path absolut atau nama di PATH.
- Tidak ada token/kunci di `agents.json`. Rahasia tetap di env (`api_key_env`).
- `tests/fixtures/agents.json` **tidak** diubah (melindungi `tests/test_team.py:176` dan `:179`).
- `workflow[]` di `agents.json` **tidak** ditambah step.
- Nama skill pack harus benar-benar ada di `skills/<pack>/<name>/SKILL.md` — `Pack.assigned()` memfilternya (`babd/skillpacks.py:87-93`). Terverifikasi ada: `research`, `domain-modeling`, `handoff` (mattpocock); `using-superpowers`, `dispatching-parallel-agents`, `verification-before-completion` (superpowers).
- Persetujuan deploy ada di tangan CEO (`project.require_approval: ["deploy"]`).

## Review Focus

1. **`agents.json` tanpa researcher** (fixture test, instalasi lama) → flow harus jalan; `_flow()` tidak boleh melempar `FlowError` dan `specialist_roles()` harus mengembalikan daftar tanpa researcher.
2. **Provider pencarian tidak ada / jaringan mati** → adapter exit code **2** dengan pesan yang memuat `no search provider`; **tidak boleh** mencetak sumber fiktif.
3. **Prompt besar** dari `render_prompt()` (system prompt persona + `---` + task) → adapter mengambil bagian **setelah `---` terakhir** sebagai query, bukan seluruh stdin.
4. **`command` relatif** di `agents.json` → tetap ditemukan setelah resolusi `ROOT`.
5. **Plan Team Lead menyebut researcher** → loop deskripsi di `babd/flow.py:834-836` tidak boleh `KeyError`.

---

### Task 1: Roster dinamis, landmine plan, dan entri agent researcher
**Status: SELESAI** — commit `ddbe350` (roster + `agents.json` + kamus skill/permission + `specialist_roles()` + `PEER_WHO`/`ASK_INSTRUCTION`; lihat juga `426a30d` untuk irisan awal). Suite hijau.

**Catatan test file baru:** `tests/test_researcher.py` perlu header seperti `tests/test_team.py:1-22`:
`sys.path.insert(0, <root>)` sebelum import `babd`, lalu `import copy, json, os, subprocess, sys, unittest`,
`from babd import flow`, `from babd.config import ROOT, load_config`, `from babd.team import Team`.
Semua kelas test (Task 1–4) hidup di file ini; kelasnya: `ResearcherRosterTest`, `ResearcherHarnessTest`,
`ResearcherAdapterTest`, `ResearcherDashboardTest`.

**Files:**
- Modify: `babd/flow.py` (ROLES line 42; ASK_INSTRUCTION line 66-72; SKIPPABLE line 143-145; PEER_WHO line 667-673; `_flow()` line 807; loop deskripsi line 827-837; `packages_of()` line 1017; `route()` line 1166; `triage_prompt()` line 1179; `parse_route()` line 1222; tambah `specialist_roles()` dekat line 145)
- Modify: `babd/permissions.py:36` (`DEFAULT_PROFILE`)
- Modify: `babd/skillpacks.py:27-33` (`GENERAL_RECOMMENDED`)
- Modify: `babd/superpowers.py:9-20` (`DEFAULT_ASSIGNMENT`)
- Modify: `babd/mattpocock.py:10-18` (`RECOMMENDED`)
- Modify: `agents.json` (tambah objek researcher setelah array `agents` elemen `devops`, line 422)
- Test: `tests/test_researcher.py` (baru)

**Interfaces — Consumes:** `team.by_id`, `flow.ROLES`, `flow.PEER_WHO`.
**Produces:** `flow.specialist_roles(team) -> list[str]`; `flow.PEER_WHO["researcher"]`; `flow.SKIPPABLE["researcher"]`; konfigurasi agent `researcher` di `agents.json`.

- [x] **Step 1: Write the failing test**

`tests/test_researcher.py` (pola `unittest`, meniru `tests/test_team.py`):

```python
import copy
import json
import os
import unittest

from babd import flow
from babd.config import load_config
from babd.team import Team

HERE = os.path.dirname(os.path.abspath(__file__))
FIXTURE = os.path.join(HERE, "fixtures", "agents.json")


class ResearcherRosterTest(unittest.TestCase):
    def test_roles_include_researcher(self):
        self.assertIn("researcher", flow.ROLES)
        self.assertIn("researcher", flow.SKIPPABLE)
        self.assertTrue(flow.PEER_WHO.get("researcher", "").strip())
        self.assertIn("researcher", flow.ASK_INSTRUCTION)

    def test_old_config_without_researcher_still_works(self):
        cfg = copy.deepcopy(load_config(FIXTURE))          # fixture 5 agent, tanpa researcher
        team = Team(cfg, log=lambda m: None)
        self.assertEqual(flow.specialist_roles(team),
                         ["architect", "developer", "qa", "devops"])

    def test_real_config_has_a_working_researcher(self):
        cfg = load_config(os.path.join(os.path.dirname(HERE), "agents.json"))
        team = Team(cfg, log=lambda m: None)
        self.assertIn("researcher", team.by_id)
        self.assertEqual(flow.specialist_roles(team),
                         ["architect", "developer", "qa", "devops", "researcher"])
        prompt = team.by_id["researcher"].system_prompt().lower()
        self.assertIn("internet", prompt)
        self.assertIn("sumber", prompt)
```

- [x] **Step 2: Run test to verify it fails**

Run: `python -m unittest tests.test_researcher -v`
Expected: FAIL — `AttributeError: module 'babd.flow' has no attribute 'specialist_roles'` (dan `AssertionError` untuk `ROLES`).

- [x] **Step 3: Implement in `babd/flow.py`**

(a) Line 42 jadi:

```python
ROLES = ("lead", "architect", "developer", "qa", "devops", "researcher")
CORE_ROLES = ROLES[:5]          # the roles every agents.json must have
```

(b) Tambah helper murni tepat setelah `SKIPPABLE`:

```python
def specialist_roles(team):
    """The specialist roles this team actually has, in ROLES order (a role missing from
    agents.json is skipped, so an older installation without `researcher` still runs)."""
    return [r for r in ROLES[1:] if r in team.by_id]
```

(c) `SKIPPABLE` (line 143-145): tambah satu entri

```python
             "researcher": "no Researcher: the task needs no internet search"}
```

(d) `ASK_INSTRUCTION` line 67: ganti teks literal `(architect, developer, qa, devops or lead)` menjadi `(architect, developer, qa, devops, researcher or lead)`.

(e) `PEER_WHO` (line 667-673): tambah `"researcher": "finding things on the internet, facts from outside sources, and citing them",`.

(f) `_flow()` line 807: `missing = [r for r in CORE_ROLES if r not in team.by_id]` (bukan `ROLES`) — sehingga instalasi tanpa researcher tetap valid.

(g) **Landmine** line 827-837: ganti dict lookup yang bisa `KeyError` dengan dict yang punya entri researcher **dan** fallback:

```python
        specialists = [r for r in specialist_roles(team) if r not in self.skip]
        ...
        WHAT_IT_DOES = {"architect": "Architect designs", "developer": "Developer builds",
                        "qa": "QA tests (failed tests go back to the Developer)",
                        "devops": "DevOps deploys and sets up monitoring after QA passes and the CEO approves",
                        "researcher": "Researcher searches the internet and reports findings with sources"}
        ...
               + ("The work flows through you: " + ", ".join(
                   WHAT_IT_DOES.get(r, r) for r in specialists) + ".\n"
```

(h) Ganti **keempat** sisa pemakaian `ROLES[1:]` dengan `specialist_roles(team)`:
`packages_of()` line 1017 (`allowed = [r for r in specialist_roles(self.team) if r not in self.skip]`),
`route()` line 1166 (`r["agents"] = [x for x in specialist_roles(self.team) if x not in self.skip]`),
`triage_prompt()` line 1179 (`for r in specialist_roles(team):`),
`parse_route()` line 1222 (`if agent not in specialist_roles(self.team) or agent in self.skip:`).

- [x] **Step 4: Run test to verify it passes**

Run: `python -m unittest tests.test_researcher -v`
Expected: PASS untuk `test_roles_include_researcher` dan `test_old_config_without_researcher_still_works`. `test_real_config_has_a_working_researcher` masih FAIL sampai Step 5.

- [x] **Step 5: Add the `researcher` entry to `agents.json` and the four role dictionaries**

Tambah objek ini sebagai elemen **terakhir** array `agents` (setelah `devops`, line 422), bentuknya persis seperti `devops`:

```json
    {
      "id": "researcher",
      "name": "RESEARCHER",
      "short_name": "Researcher",
      "color": "#c084fc",
      "status": "idle",
      "main_task": ["RESEARCH", "INTERNET"],
      "sub_tasks": [
        {"name": "Search the web", "state": "todo"},
        {"name": "Verify sources", "state": "todo"},
        {"name": "Report findings", "state": "todo"}
      ],
      "llm": {
        "provider": "Custom",
        "api": "openai",
        "base_url": "http://43.134.238.213:20128/v1",
        "model": "ag-hermes",
        "api_key_env": "KEY1",
        "effort": "high"
      },
      "harness": {
        "type": "process",
        "command": ".babd/researcher/bin/research",
        "args": ["--json"],
        "install": ".babd/researcher/bin/setup",
        "timeout_sec": 600
      },
      "permissions": "workspace",
      "sandbox": "none",
      "parallel": 1,
      "telegram": {"enabled": false, "bot_username": "@babd_researcher_bot",
                   "token_env": "TELEGRAM_RESEARCHER_BOT_TOKEN"},
      "skills": ["GBrain", "Web Research", "Internet Search", "Source Citation"],
      "superpowers": ["using-superpowers", "dispatching-parallel-agents", "verification-before-completion"],
      "mattpocock": ["research", "domain-modeling", "handoff"]
    }
```

Tambah entri `researcher` ke kamus role:
- `babd/permissions.py:36` — `"researcher": "workspace",`
- `babd/skillpacks.py` `GENERAL_RECOMMENDED` — `"researcher": ["GBrain", "Web Research", "Internet Search", "Source Citation"],`
- `babd/superpowers.py` `DEFAULT_ASSIGNMENT` — `"researcher": ["using-superpowers", "dispatching-parallel-agents", "verification-before-completion"],`
- `babd/mattpocock.py` `RECOMMENDED` — `"researcher": ["research", "domain-modeling", "handoff"],`

- [x] **Step 6: Run the tests**

Run: `python -m json.tool agents.json > /dev/null && python -m unittest discover -s tests -q`
Expected: PASS. `test_team.py::test_full_run` tetap hijau (fixture tidak berubah → masih 6 request LLM). Output nyata wajib ditempel di laporan, bukan diklaim.

- [x] **Step 7: Commit**

```bash
git add babd/flow.py babd/permissions.py babd/skillpacks.py babd/superpowers.py babd/mattpocock.py agents.json tests/test_researcher.py
git commit -m "feat: researcher agent in the roster, config and skill packs"
```

---

### Task 2: Path relatif untuk harness `process` (dipicu jawaban CEO)
**Status: SELESAI** — `Process.command_path()` me-resolusi `command` relatif terhadap `ROOT`; test `test_process_command_may_be_relative` + `test_process_command_absolute_is_untouched` di `tests/test_harness.py` hijau.

**Files:**
- Modify: `babd/harness/others.py:154-156` (`Process.command_path`)
- Test: `tests/test_researcher.py` (tambah kelas)

**Interfaces — Consumes:** `os.path.join(ROOT, command)` pola `cwd`/`config_dir`.
**Produces:** `Process.command_path()` menerima `command` relatif; dipakai Task 3 lewat `agents.json`.

- [x] **Step 1: Write the failing test**

```python
    def test_process_command_may_be_relative(self):
        from babd.config import ROOT
        from babd.harness import create_harness
        cfg = {"id": "researcher",
               "llm": {"provider": "Custom", "api": "openai", "model": "m", "api_key_env": "KEY1",
                       "base_url": "http://x/v1"},
               "harness": {"type": "process", "command": "babd/flow.py", "args": []},
               "permissions": "workspace"}
        h = create_harness(cfg)          # babd/harness/__init__.py:21
        self.assertEqual(h.command_path(), os.path.join(ROOT, "babd/flow.py"))

    def test_process_command_absolute_is_untouched(self):
        from babd.harness import create_harness
        cfg = {"id": "researcher",
               "llm": {"provider": "Custom", "api": "openai", "model": "m", "api_key_env": "KEY1",
                       "base_url": "http://x/v1"},
               "harness": {"type": "process", "command": sys.executable, "args": []},
               "permissions": "workspace"}
        self.assertEqual(create_harness(cfg).command_path(), sys.executable)
```

(Perhatikan: `babd/flow.py` dipakai sebagai file executable-tiruan karena ia ada di repo; test hanya menguji resolusi path, bukan menjalankannya. Nama fungsinya `create_harness`, **bukan** `build_harness` — `babd/harness/__init__.py:21`.)

- [x] **Step 2: Run test to verify it fails**

Run: `python -m unittest tests.test_researcher.ResearcherHarnessTest -v`
Expected: FAIL — `HarnessError: Custom process: command 'babd/flow.py' not found` (dari `ensure_command`).

- [x] **Step 3: Implement in `babd/harness/others.py`**

```python
    def command_path(self):
        from .tools import ensure_command
        command = self.cfg.get("command")
        if command and not os.path.isabs(command):
            # agents.json keeps paths relative (like `cwd` and `config_dir`); ensure_command only
            # accepts an absolute path or a name on PATH, so resolve against ROOT here.
            command = os.path.join(ROOT, command)
        return ensure_command(self.label, {**self.cfg, "command": command}, None)
```

- [x] **Step 4: Run test to verify it passes**

Run: `python -m unittest tests.test_researcher -v && python -m unittest discover -s tests -q`
Expected: PASS, termasuk `tests/test_harness.py` (tidak ada regresi pada harness `process`).

- [x] **Step 5: Commit**

```bash
git add babd/harness/others.py tests/test_researcher.py
git commit -m "fix(harness): resolve a relative process command against ROOT"
```

---

### Task 3: Adapter lokal gpt-researcher (program black box)
**Status: SELESAI (kecuali E2E berkredensial)** — commit `2aadf30`; adapter + kelas test adapter di `tests/test_researcher.py`. Perbaikan rc=3 palsu (prompt lewat `RESEARCHER_PROMPT` saat re-exec venv) terverifikasi RED->GREEN. E2E provider nyata BELUM dijalankan (tak ada SearXNG di mesin ini) — serah-terima ke QA/DevOps.

**Files:**
- Create: `scripts/researcher_adapter.py`
- Create: `scripts/researcher_setup.sh`
- Create: `docs/researcher/SETUP.md`
- Modify: `.gitignore` **hanya bila perlu** — verifikasi dulu: `.gitignore:4` sudah memuat `.babd/`, jadi vendored gpt-researcher + venv di `.babd/researcher/` **sudah** terabaikan. Jangan tambah baris yang tidak dibutuhkan.
- Test: `tests/test_researcher.py` (tambah kelas subprocess)

**Interfaces — Consumes:** stdin = `render_prompt()` (system prompt, `\n\n---\n\n`, task); env `BABD_LLM_BASE_URL` / `BABD_LLM_MODEL` / `BABD_LLM_API_KEY` (dari `generic_routing`, `babd/harness/routing.py:98-113`); env `RESEARCHER_SEARXNG_URL`, `RESEARCHER_ALLOW_DUCKDUCKGO`, `RESEARCHER_FAKE` (hanya untuk test).
**Produces:** stdout = satu blok JSON `{"query": str, "answer": str, "sources": [{"title": str, "url": str}], "local": bool}` lalu `\n---\n` + ringkasan teks; exit 0 sukses, exit 2 tanpa provider, exit 3 error lain.

- [x] **Step 1: Write the failing test**

```python
    def test_adapter_reads_prompt_from_stdin(self):
        env = {**os.environ, "RESEARCHER_FAKE": "1"}
        env.pop("RESEARCHER_SEARXNG_URL", None)
        prompt = "You are the RESEARCHER.\n\n---\n\nversi terbaru httpx\n"
        p = subprocess.run([sys.executable, ADAPTER], input=prompt, capture_output=True,
                           text=True, env=env, timeout=120)
        self.assertEqual(p.returncode, 0, p.stderr)
        payload = json.loads(p.stdout.split("\n---\n")[0])
        self.assertEqual(payload["query"], "versi terbaru httpx")
        self.assertEqual(payload["local"], True)
        self.assertIsInstance(payload["sources"], list)
        self.assertTrue(payload["answer"].strip())

    def test_adapter_is_honest_without_a_provider(self):
        env = {k: v for k, v in os.environ.items()
               if k not in ("RESEARCHER_SEARXNG_URL", "RESEARCHER_ALLOW_DUCKDUCKGO", "RESEARCHER_FAKE")}
        p = subprocess.run([sys.executable, ADAPTER], input="task\n", capture_output=True,
                           text=True, env=env, timeout=120)
        self.assertEqual(p.returncode, 2)
        self.assertIn("no search provider", (p.stderr + p.stdout).lower())
```

(dengan `ADAPTER = os.path.join(os.path.dirname(os.path.dirname(HERE)), "scripts", "researcher_adapter.py")`)

- [x] **Step 2: Run test to verify it fails**

Run: `python -m unittest tests.test_researcher.ResearcherAdapterTest -v`
Expected: FAIL — file adapter belum ada (`FileNotFoundError` / returncode 2 dari python).

- [x] **Step 3: Implement `scripts/researcher_adapter.py`**

Poin implementasi yang harus tepat:
- Baca seluruh stdin (`sys.stdin.read()`).
- Query = bagian setelah `---\n\n` **terakhir**; kalau tidak ada pemisah, pakai seluruh stdin. Buang baris kosong dan heading `#`/`##`.
- Pilih provider: `RESEARCHER_SEARXNG_URL` ada → gpt-researcher dengan SearXNG; kalau tidak dan `RESEARCHER_ALLOW_DUCKDUCKGO=1` → DuckDuckGo; kalau tidak ada keduanya → cetak ke stderr `researcher: no search provider configured (set RESEARCHER_SEARXNG_URL or RESEARCHER_ALLOW_DUCKDUCKGO=1)` dan **exit 2**.
- `RESEARCHER_FAKE=1` → kembalikan hasil contoh yang **jelas ditandai** (`"local": true`, `answer` menyebut mode fake) untuk test; tidak pernah dipakai produksi.
- Bungkus jadi skema JSON + `\n---\n` + ringkasan teks; `json.dumps(..., ensure_ascii=False)`.
- Semua exception lain → pesan ke stderr + **exit 3**. **Jangan pernah** mencetak sumber yang tidak benar-benar dikembalikan provider.
- LLM: baca `os.environ["BABD_LLM_BASE_URL"/"BABD_LLM_MODEL"/"BABD_LLM_API_KEY"]`; jangan hardcode kunci.

- [x] **Step 4: Run test to verify it passes**

Run: `python -m unittest tests.test_researcher -v` → PASS.
Run manual (output nyata wajib ditempel; kalau jaringan mati tulis **NOT RUN** + alasan):
`printf 'You are the RESEARCHER.\n\n---\n\nversi terbaru httpx\n' | python scripts/researcher_adapter.py --json ; echo "exit=$?"`

- [x] **Step 5: `scripts/researcher_setup.sh` dan `docs/researcher/SETUP.md`**

`researcher_setup.sh`: clone/pin gpt-researcher ke `.babd/researcher/gpt-researcher/`, buat venv `.babd/researcher/venv`, `pip install -e`, buat symlink `.babd/researcher/bin/research` → `scripts/researcher_adapter.py` (executable) dan `.babd/researcher/bin/setup` → skrip ini. Harus idempoten. Catat di `SETUP.md` bahwa kegagalan jaringan → jalur `--offline` yang jujur.

- [x] **Step 6: Commit**

```bash
git add scripts/researcher_adapter.py scripts/researcher_setup.sh docs/researcher/SETUP.md
git add tests/test_researcher.py
git commit -m "feat: local gpt-researcher adapter for the researcher agent"
```

---

### Task 4: Dashboard researcher
**Status: SELESAI** — commit `cb707b5`: checkbox `skip=researcher` di `app.js` + test board/skip di `tests/test_dashboard.py` (13 OK).

**Files:**
- Modify: `babd/dashboard/static/app.js:149-151` (checkbox skip), `:283` (hint `sv_agents`)
- Test: `tests/test_researcher.py` (tambah kelas)

**Interfaces — Consumes:** `Dashboard.board()` loop over `cfg["agents"]` (`babd/dashboard/server.py:1171-1190`).
**Produces:** kartu agent + checkbox skip researcher; hint server menyebut riset web.

- [x] **Step 1: Write the failing test**

```python
    def test_board_shows_researcher(self):
        # agents.json nyata (bukan fixture) sudah memuat researcher setelah Task 1
        self.assertIn("researcher", flow.specialist_roles(REAL_TEAM))
        # board() membangun daftar dari cfg["agents"] (babd/dashboard/server.py:1171-1190)
        ids = [a["id"] for a in load_config(REAL_AGENTS_JSON)["agents"]]
        self.assertIn("researcher", ids)

    def test_app_js_has_a_skip_box_for_researcher(self):
        js = open(os.path.join(os.path.dirname(HERE), "babd", "dashboard", "static", "app.js"),
                  encoding="utf-8").read()
        self.assertIn('name="skip" value="researcher"', js)
```

(dengan `REAL_TEAM = Team(load_config(REAL_AGENTS_JSON), log=lambda m: None)` dan
`REAL_AGENTS_JSON = os.path.join(os.path.dirname(HERE), "agents.json")` didefinisikan di
`setUpClass`; `load_config` ada di `babd/config.py`, sudah dipakai `tests/test_team.py:18`.)

- [x] **Step 2: Run test to verify it fails**

Run: `python -m unittest tests.test_researcher.ResearcherDashboardTest -v`
Expected: FAIL — `app.js` belum punya checkbox skip researcher.

- [x] **Step 3: Implement in `app.js`**

Sesudah line 151 tambah:

```html
      <label class="check"><input type="checkbox" name="skip" value="researcher"> No Researcher: the task needs no internet search</label>
```

Dan ubah hint server (line 283) dari `"Agents that may use it, e.g. devops, developer"` menjadi
`"Agents that may use it, e.g. devops, developer, researcher"`.

- [x] **Step 4: Run test to verify it passes**

Run: `python -m unittest tests.test_researcher -v && python -m unittest discover -s tests -q`
Expected: PASS.

- [x] **Step 5: Commit**

```bash
git add babd/dashboard/static/app.js tests/test_researcher.py
git commit -m "feat(dashboard): show and allow skipping the researcher agent"
```

---

### Task 5: QA — unit + E2E kolaborasi dua arah

**Files:** none (verifikasi). Boleh tambah `tests/test_researcher_e2e.py`.

- [x] Jalankan `python -m unittest discover -s tests -q` dan `python -m pytest -q` (bila tersedia). Tempel output **nyata**.
- [x] E2E kolaborasi (fixture salinan berisi researcher, mock LLM): assert (a) researcher menerima step; (b) `parse_question("ASK: researcher\nQUESTION: apa versi terbaru X")` → `ask == ["researcher"]`; (c) `ask_peer("developer", ...)` merutekan ke researcher dan balik ke penanya; (d) `board()` memuat researcher; (e) report markdown memuat researcher.
- [x] Buktikan Review Focus #1: `_flow()` pada fixture 5 agent (tanpa researcher) **tidak** melempar `FlowError`.
- [x] Buktikan Review Focus #5: plan Team Lead yang menyebut researcher tidak `KeyError` (jalankan `_flow()` dengan mock plan memuat assignment researcher).
- [!] Verifikasi jam activity log researcher memakai skrip **terbaru** (`verify_live_wib.mjs` / `verify_live_tz_locale.mjs`), **bukan** `verify_live_clock.mjs` yang sudah dihapus. *(Skrip `.mjs` itu TIDAK ada di repo ini; penggantinya permanen: `tests/test_researcher_e2e.py::test_activity_log_time_is_local_server_wall_clock`.)*
- [x] Laporan wajib berakhir `VERDICT: PASS` atau `VERDICT: FAIL` + bagian `EVIDENCE:` berisi perintah dan output asli. FAIL → kembali ke Developer.

### Task 6: DevOps — operasional lokal + rollback (blocked by Task 5 PASS)

- [x] `docs/researcher/RUNBOOK.md`: cara `setup`, start manual, cek sehat (`printf 'x\n' | .babd/researcher/bin/research` + exit code), baca log, rollback = `git revert` commit agent + hapus `.babd/researcher/`. *(Ditambah `docs/researcher/DEPLOY.env.example` — kini TERLACAK git; dijaga `tests/test_deploy_env.py`.)*
- [x] Konfirmasi researcher **tidak** masuk `servers[].agents` dan tidak butuh `TELEGRAM_*`. *(diverifikasi: tidak ada di server mana pun; `telegram.enabled=False`.)*
- [ ] Deploy hanya setelah **CEO menyetujui**.

---

## Work Packages & dependensi

```
p1 Task1 ──┬─> p2 Task2 ─┐
           └─> p3 Task4 ─┴─> p4 Task5 ─> p5 Task6
p3 Task3 (adapter) boleh paralel dengan p2 Task2 setelah p1
```

| Package | Task | Agent | depends_on |
|---|---|---|---|
| p1 | Roster + landmine + entri agent | developer | — |
| p2 | Path relatif `Process.command_path` | developer | p1 |
| p3 | Adapter gpt-researcher | developer | p1 |
| p4 | Dashboard | developer | p2 (mengubah file yang sama dengan Task 4 test) |
| p5 | QA verifikasi | qa | p1, p2, p3, p4 |
| p6 | DevOps runbook | devops | p5 |

**Catatan paralel:** Task 3 (adapter, `scripts/`) dan Task 4 (dashboard, `babd/dashboard/static/`) tidak berbagi file — boleh jalan bersamaan. Task 2 dan Task 4 sama-sama menyentuh `tests/test_researcher.py`; jalankan berurutan bila memakai satu worktree.

## Self-Review (dijalankan sendiri)

1. **Spec coverage:** D1→T1, D2→T1(helper), D3→T1(PEER_WHO+ASK_INSTRUCTION), D4→T1(landmine), D5→T1, D6→T3, D7→T3, D8→T1, D9→T4, D10→Global Constraints (fixture tidak diubah), D11→T2, D12→T6. Semua keputusan punya task.
2. **Step scan:** tiap langkah punya hasil yang bisa dicek; tidak ada "TBD"/"handle edge cases".
3. **Type consistency:** `specialist_roles(team)` dipakai konsisten di 5 situs + 3 test; `SKIPPABLE`, `PEER_WHO`, `ASK_INSTRUCTION` namanya sama di plan dan test.
4. **Review Focus:** 5 baris, masing-masing punya test di task pemiliknya (T1 #1, T3 #2 #3, T2 #4, T1/T5 #5).
5. **Proportion:** plan lebih pendek dari kode yang dihasilkan; blok kode hanya untuk test dan nilai exact.

---

## Fix round 2 — penutupan blocker QA round 1 (Developer)

QA round 1 menilai **FAIL** dengan 6 blocker. Semua sudah ditutup **dan terverifikasi di worktree ini**
(perintah dijalankan oleh Developer pada commit `ddbe350` + `6946f89` + `bd46df3`):

| Blocker | Inti | Fix | Tes permanen | Bukti RED |
|---|---|---|---|---|
| **B-1** | `Run.is_skipped()` tak ada | helper generik di `flow.py` (tahan `str`/`None`/`set`) | `tests/test_peer_collaboration.py::test_is_skipped_and_has_tools_regression` | kode lama → **ERROR** |
| **B-2** | `Process.has_tools` tak ada | properti di `harness/others.py` | tes yang sama | kode lama → **ERROR** |
| **B-3** | `delegate()` `while q:` cabang peer **tanpa batas** → hang | `project.max_peer_questions` + `Run.peer_budget_left()` + `PeerLoop` ditangkap jadi blocker | `::test_asks_are_bounded_when_the_agent_never_stops_asking` + `::test_a_single_peer_answer_closes_the_loop` | kode lama (`ac1d6c1`) → **hang, RC=124** |
| **B-4** | `PACKAGE_KIND["researcher"]="code"` | diubah jadi `"research"` | `::test_package_kind_for_researcher_is_not_code` | — |
| **B-5** | fix uncommitted, tanpa tes | `flow.py`+`others.py` di-commit di `ddbe350`; working tree bersih | grep `is_skipped`/`has_tools` di `tests/` > 0 | — |
| **B-6** | tak ada E2E kolaborasi di suite | jalur peer dieksekusi nyata via `flow.Run.execute` | `tests/test_researcher_e2e.py::test_peer_question_is_routed_to_researcher_and_answered_back` (+5 E2E lain) | — |

**Perintah verifikasi & output nyata (Developer, commit ini):**

```
$ python -m unittest discover -s tests -q
Ran 321 tests in 94.569s
OK (skipped=3)

$ python -m unittest tests.test_peer_collaboration -v
Ran 5 tests  ... OK

$ python -m unittest tests.test_researcher tests.test_researcher_e2e tests.test_evidence
Ran 16 tests ... OK (skipped=1)   # + 14 E2E/evidence OK

$ echo "versi terbaru httpx" | python scripts/researcher_adapter.py   # tanpa provider
researcher: no search provider: ... Refusing to invent sources.
EXIT=2
```

**RED nyata (bukti tes menangkap bug):** `git show ac1d6c1:babd/flow.py > babd/flow.py` lalu
`python -m unittest tests.test_peer_collaboration -v` →
`test_is_skipped_and_has_tools_regression ... ERROR` dan
`test_asks_are_bounded_when_the_agent_never_stops_asking ... <timeout RC=124>` (persis bug B-3 QA).
Kode fix dipulihkan → 5 OK.

**Serah-terima ke QA (round 2):** jalankan `python -m unittest discover -s tests -q` (harap 321 OK) dan
E2E kolaborasi termock. E2E **berkredensial/provider pencarian nyata tetap NOT RUN** (tidak ada SearXNG
di mesin ini; adapter jujur `exit 2` tanpa provider) — itu pekerjaan DevOps (Task 6), bukan klaim Developer.
