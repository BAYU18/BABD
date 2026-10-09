# Desain: Agent Keenam "researcher" (gpt-researcher lokal)

Tanggal: 2026-10-09 · Penulis: Architect · Status: menunggu review CEO
Worktree: `workspace/worktrees/babd-self/20261009-093920`

## Problem Statement

Tim BABD punya empat spesialis (architect, developer, qa, devops) tapi tidak punya agent
yang tugasnya mencari di internet. Ketika sebuah task butuh fakta dari luar (versi library,
cara pakai API, perbandingan tools), jawabannya mengandalkan pengetahuan model saja: sering
usang, tanpa sumber, dan tidak bisa ditelusuri. CEO ingin agent kelima yang **memang** mesin
pencari, berjalan lokal, dengan repo `assafelovic/gpt-researcher` sebagai mesinnya, dan bisa
dipanggil semua agent lain.

## Solution

Tambah agent `researcher` ke BABD:

1. **Roster**: `researcher` masuk `flow.ROLES`, ia specialist biasa (bukan stage baru).
2. **Harness**: `process` (sudah ada di BABD) menjalankan adapter lokal di atas
   gpt-researcher yang di-vendor.
3. **Output**: terstruktur (jawaban + daftar sumber) supaya bisa diverifikasi dan disitasi.
4. **Kolaborasi**: bisa di-assign sebagai specialist maupun dipanggil-peer oleh agent lain.
5. **Dashboard**: muncul di board, kartu agent, activity log dan laporan.

## Grounding: apa yang sudah saya baca di kode nyata

Semua klaim "file:line" di bawah berasal dari pembacaan file nyata di worktree, bukan asumsi.

| File:line | Temuan |
|---|---|
| `babd/flow.py:42` | `ROLES = ("lead", "architect", "developer", "qa", "devops")` — konstanta keras. |
| `babd/flow.py:44-47` | `ROUTES` **sudah** memuat semua pasangan specialist↔specialist. Kolaborasi peer dua arah sudah ada mekanismenya. |
| `babd/flow.py:66-72` | `ASK_INSTRUCTION` menyebut role **sebagai teks literal**: "(architect, developer, qa, devops or lead)". Tanpa menambah `researcher` di sini, tak ada agent yang tahu ia boleh bertanya ke researcher. |
| `babd/flow.py:143-145` | `SKIPPABLE` = dict; dipakai **hanya** di `task_options()` line 164-166. |
| `babd/flow.py:807` | `_flow()`: `missing = [r for r in ROLES if r not in team.by_id]` → menambah ROLES membuat `agents.json` wajib punya researcher. |
| `babd/flow.py:827` | `specialists = [r for r in ROLES[1:] if r not in self.skip]` |
| `babd/flow.py:834-836` | **LANDMINE**: deskripsi alur dibangun dari `{"architect": ..., "developer": ..., "qa": ..., "devops": ...}[r]` — role baru memicu `KeyError`. |
| `babd/flow.py:1017` | `packages_of()`: `allowed = [r for r in ROLES[1:] if r not in self.skip]` |
| `babd/flow.py:1138-1140` | `can_run(agent_id)` = `harness.has_tools and permissions != "plan"` — harness `process` **tidak** punya `has_tools=True`, jadi researcher tidak akan dianggap "bisa jalan sendiri" (dan itu benar: adapter hanya mencari, bukan mengubah mesin). |
| `babd/flow.py:1166` | `route()`: `r["agents"] = [x for x in ROLES[1:] if x not in self.skip]` |
| `babd/flow.py:1179` | `triage_prompt()`: loop `for r in ROLES[1:]` → researcher otomatis masuk deskripsi tim triage. |
| `babd/flow.py:1222` | `parse_route()`: `if agent not in ROLES[1:]` → researcher otomatis sah sebagai tujuan route `direct`. |
| `babd/flow.py:667-673` | `PEER_WHO` dict: tanpa entri `researcher`, prompt peer memakai fallback `'your area'` (QA akan menandainya). |
| `babd/harness/others.py:123-169` | `Process`: `command` + `args`; `args` boleh `{model}`/`{base_url}`; menuang prompt ke **stdin** dan mengambil **stdout**; exit code ≠ 0 → `HarnessError`. |
| `babd/harness/base.py:286-298` | `render_prompt(system, messages)`: stdin = **system prompt + "\n\n---\n\n" + pesan terakhir**. Jadi adapter menerima instruksi persona lebih dulu, dipisah `---`, lalu task. |
| `babd/harness/tools.py:200-205` | `ensure_command`: `command` eksplisit diresolusi via `shutil.which(cmd)` **atau** `os.path.isabs(cmd) and X_OK`. **Path relatif GAGAL.** |
| `babd/harness/routing.py` | `generic_routing(llm)` menyuapkan `BABD_LLM_API/BASE_URL/MODEL/API_KEY` + `OPENAI_*` ke program anak. |
| `babd/harness/others.py:164-165` | Program anak juga menerima `BABD_AGENT_ID` dan `BABD_SYSTEM_PROMPT`. |
| `babd/team.py:213-216` | `Team.__init__`: `agents[0]` = lead; specialist = sisanya. Urutan `agents.json` menentukan. |
| `babd/dashboard/server.py:1171-1190` | `board()` loop `cfg["agents"]` → researcher otomatis muncul. |
| `babd/dashboard/static/app.js:149-151` | Checkbox skip **keras**: hanya `architect`, `devops`, `prep`. |
| `babd/dashboard/static/app.js:283` | Hint `sv_agents` = "Agents that may use it, e.g. devops, developer". |
| `tests/test_team.py:176` | `assertEqual(set(replies) - {"ceo"}, {"architect", "developer", "qa", "devops"})` |
| `tests/test_team.py:179` | `assertEqual(len(MockLLM.requests), 6)` |

**Kesimpulan grounding:** integrasi ini bukan "tambah baris di JSON". Ada **8 titik kode keras**
(ROLES, ASK_INSTRUCTION, loop deskripsi 834-836, PEER_WHO, + 4 kamus skill/permission) yang
harus bergerak bersamaan, atau researcher akan terlihat "ada" tapi tidak bisa dipanggil —
atau langsung `KeyError` saat plan.

## Jawaban atas pertanyaan yang saya ajukan ke CEO

**Q(a) — apakah `SKIPPABLE` diimpor sebagai objek dict oleh modul luar `flow.py`?**

**Dijawab dari kode, bukan dari CEO.** `search_files` untuk `SKIPPABLE` di seluruh worktree:
16 baris, **semua** di `babd/flow.py` (143-166). Tidak ada modul lain yang meng-import
`SKIPPABLE`, tidak ada yang meng-iterasinya di dashboard, server, atau test. Frontend
`app.js:149-151` menulis nilai skip sebagai literal string, bukan dari `SKIPPABLE`.
⇒ **Tidak perlu helper `skippable()`.** Cukup tambah 1 entri ke dict. Tidak ada pemakai
lain yang rusak.

**Q(b) — apakah `command` harness `process` harus path absolut?**

**CEO menjawab: "setuju absolut / ada pola path lain di kode ini"** — dan saya
memverifikasi **kenapa** harus absolut, di `babd/harness/tools.py:200-205`:

```python
explicit = cfg.get("command")
if explicit:
    path = shutil.which(explicit) or (explicit if os.path.isabs(explicit) and os.access(explicit, os.X_OK) else None)
    if not path:
        raise HarnessError(f"{label}: command {explicit!r} not found")
```

`shutil.which()` mencari **di PATH** (dan `.babd/researcher/bin/` tidak ada di PATH), dan
cabang kedua hanya menerima **path absolut**. Jadi `command` **harus absolut**.

**Pola path lain di kode ini** (yang saya temukan, jadi tidak perlu menebak):
- `babd/harness/others.py:57-58` — `config_dir` di-*absolut*-kan lewat `os.path.join(ROOT, ...)`,
  bukan disimpan relatif.
- `babd/flow.py:41` — `RUNS_DIR = os.path.join(ROOT, "runs")`.
- `babd/harness/base.py:144-147` — `cwd` memakai `os.path.join(ROOT, cwd)` bila relatif.
- Pola konsisten: **`agents.json` menyimpan relatif, kode meng-absolut-kan terhadap `ROOT`.**
- **TAPI** `ensure_command` **tidak** meng-absolut-kan `command`. Karena itu, keputusan desain
  saya: adapter menerima `command` **relatif** di `agents.json` (mudah dibaca manusia,
  konsisten dengan `cwd`/`config_dir`) dan **`Harness.setup()`/`command_path()` me-resolusi
  relatif terhadap `ROOT`** — perubahan kecil di satu tempat, mengikuti pola yang ada, dan
  membuat `agents.json` portabel antar worktree.

**Ruling baru D11 (menggantikan D4 versi Team Lead):** `command` di `agents.json` ditulis
relatif (`".babd/researcher/bin/research"`), dan `Process.command_path()` memakai
`os.path.join(ROOT, command)` bila `command` relatif. Ini menjaga `agents.json` tetap bersih
dan memperbaiki `ensure_command` untuk **semua** harness `process`, bukan hanya researcher.

## User Stories

1. Sebagai CEO, saya ingin satu agent yang bisa saya suruh mencari apa pun di internet,
   supaya saya tidak perlu menyalin-tempel hasil pencarian sendiri.
2. Sebagai Developer, saya ingin bertanya ke researcher "apa API terbaru untuk X" dan
   menerima jawaban *dengan URL sumber*, supaya saya tidak menulis kode berdasarkan ingatan.
3. Sebagai Architect, saya ingin researcher membandingkan 2-3 library dengan tautan resmi,
   supaya keputusan desain punya dasar.
4. Sebagai QA, saya ingin memastikan tiap klaim researcher punya minimal satu sumber yang
   bisa dibuka, supaya hasil riset bisa diverifikasi.
5. Sebagai CEO, saya ingin melihat researcher di dashboard (kartu, activity log, board,
   laporan) supaya statusnya setara agent lain.
6. Sebagai CEO, saya ingin researcher muncul di activity log dengan **jam WIB server yang
   benar** (konsisten dengan perbaikan log terakhir).
7. Sebagai CEO, saya ingin researcher *tidak* harus dijalankan (bisa di-`skip`) pada task
   yang tidak butuh riset, supaya tidak menambah biaya.
8. Sebagai Team Lead, saya ingin bisa menugaskan researcher sebagai bagian dari work package,
   supaya riset bisa jalan paralel dengan coding.
9. Sebagai Developer, saya ingin perubahan ini tidak memecahkan 4 spesialis yang sudah ada,
   supaya pekerjaan tim tetap jalan.
10. Sebagai DevOps, saya ingin tahu cara start/troubleshoot researcher lokal, supaya bisa
    memperbaiki kalau gagal.

## Implementasi Decisions

- **D1 — Roster.** `ROLES` menjadi `("lead", "architect", "developer", "qa", "devops", "researcher")`.
  Di `agents.json`, researcher diletakkan **setelah `devops`** (bukan sebelum `lead`, karena
  `team.py:213` memakai `agents[0]` sebagai lead).
- **D2 — Roster dinamis (pengaman).** Tambah helper murni:
  `specialist_roles(team) -> [r for r in ROLES[1:] if r in team.by_id]`.
  Ganti **lima** pemakaian `ROLES[1:]` (827, 1017, 1166, 1179, 1222) dengan helper ini.
  Validasi `_flow()` (line 807) hanya menuntut `ROLES[:5]` → instalasi lama tanpa researcher
  tetap jalan alih-alih hard error.
- **D3 — Kolaborasi.** Tambah `"researcher": "pencarian di internet, fakta dari sumber luar, dan sitasi"`
  ke `PEER_WHO`; tambah `researcher` ke daftar literal di `ASK_INSTRUCTION` (line 67).
  `ROUTES` tidak perlu diubah (sudah lengkap).
- **D4 — Landmine 834-836.** Ganti dict lookup yang bisa `KeyError` dengan dict yang punya
  `.get(r, ...)` fallback **dan** tambah entri `researcher` eksplisit. Wajib, kalau tidak
  plan apa pun dengan researcher langsung crash.
- **D5 — Agent entry.** Tambah ke `agents.json`: `id: "researcher"`, `name: "RESEARCHER"`,
  `short_name: "Researcher"`, `color: "#c084fc"`, `main_task` = riset internet,
  `harness.type: "process"`, `command: ".babd/researcher/bin/research"` (relatif; di-absolut-kan
  oleh D11), `args: ["--json"]`, `timeout_sec: 600`, `install`, `permissions: "workspace"`,
  `parallel: 1`, `sandbox: "none"`, `telegram.enabled: false`.
- **D6 — Adapter.** `scripts/researcher_adapter.py` menerima stdin = `render_prompt()` (system
  prompt persona, `---`, lalu task). Adapter mengambil **bagian setelah `---` terakhir** sebagai
  query. Mencetak stdout: satu blok JSON `{"query", "answer", "sources":[{title,url}], "local"}`
  lalu `\n---\n` + ringkasan teks. Exit 0 sukses, **exit 2 tanpa search provider**, exit 3 error lain.
  LLM dari env `BABD_LLM_BASE_URL/MODEL/API_KEY`. **Tidak pernah** mencetak sumber fiktif.
- **D7 — Vendor.** gpt-researcher di-vendor di `.babd/researcher/gpt-researcher/` dengan venv
  terpisah `.babd/researcher/venv` (masuk `.gitignore`). Venv tidak mengotori lingkungan BABD.
  Mode `--offline` bila sumber tidak tersedia → hasil kosong **yang jujur**, bukan palsu.
- **D8 — Skill pack.** Tambah entri `researcher` ke `GENERAL_RECOMMENDED` (skillpacks.py),
  `DEFAULT_ASSIGNMENT` (superpowers.py), `RECOMMENDED` (mattpocock.py), `DEFAULT_PROFILE`
  (permissions.py). Tanpa ini dashboard menandai skill researcher "missing" terus-menerus.
- **D9 — Dashboard.** `app.js`: tambah checkbox skip `researcher` (line 149-151) + perbarui
  hint `sv_agents` (line 283) agar menyebut researcher sebagai agent yang relevan untuk riset
  web, bukan server. Backend tidak perlu diubah (semua loop over `cfg["agents"]`).
  `workflow[]` di `agents.json` **tidak** ditambah step (researcher bukan stage).
- **D10 — Fixture.** `tests/fixtures/agents.json` **tidak** ditambah researcher. Melindungi
  `test_team.py:176` (assert set) dan `:179` (`len(requests) == 6`). Test baru memakai fixture
  salinan yang menyertakan researcher.
- **D11 — Path absolut (dari jawaban CEO).** `Process.command_path()` me-resolusi `command`
  relatif terhadap `ROOT`; `agents.json` menyimpan relatif. Mengikuti pola `cwd`/`config_dir`.
- **D12 — Batas keamanan.** Tidak ada token/kunci di `agents.json`; researcher **tidak** diberi
  akses server (`servers.py` default tetap `["devops"]`).

## Testing Decisions

Yang diuji adalah **perilaku eksternal**, bukan internal adapter.

| # | Yang diuji | Seam |
|---|---|---|
| i | `Team(cfg).by_id["researcher"]` ada; `system_prompt()` memuat kata "internet" dan "sumber" | `Team` |
| ii | `flow.ROLES` memuat researcher **dan** `_flow()` tidak gagal saat `agents.json` tanpa researcher | `flow` |
| iii | `specialist_roles(team)` mengembalikan 4 role pada fixture lama, 5 role pada fixture baru | helper murni |
| iv | `MessageBus` menerima route `developer → researcher` dan `researcher → qa`; `parse_question("ASK: researcher\nQUESTION: ...")` → `ask == ["researcher"]` | bus + parser |
| v | `PEER_WHO["researcher"]` ada; `ASK_INSTRUCTION` menyebut `researcher` | flow |
| vi | Adapter: stdin prompt → stdout JSON valid dengan `answer` + `sources`; **exit 2 + pesan "no search provider"** saat provider kosong | subprocess (black box) |
| vii | Regression: `test_full_run` tetap 6 request; `board()` tetap 5 agent pada fixture lama | suite |
| viii | Plan dengan researcher **tidak** `KeyError` (landmine 834-836) | flow |

Seam tertinggi: `Team`/`flow` (sudah ada). Satu seam baru di **batas program** (stdin→stdout
adapter) yang diuji sebagai black box lewat subprocess.

## Review Focus (input/keadaan yang spek diamkan tapi tetap harus tidak meledak)

1. **`agents.json` tanpa researcher** (instalasi lama, atau fixture test) → flow harus jalan,
   bukan `FlowError`.
2. **Provider pencarian tidak ada / jaringan mati** → adapter exit 2 dengan pesan jelas,
   **tidak** mengarang sumber.
3. **Prompt raksasa** (system prompt persona + task panjang >100 KiB) → adapter tetap
   mengekstrak query dengan benar dari bagian setelah `---` terakhir.
4. **`command` di `agents.json` relatif** → tetap ditemukan lewat resolusi `ROOT`.
5. **`researcher` masuk `skip`** → ia hilang dari `specialists`, `packages_of`, `route()` dan
   triage tanpa `KeyError`.

## Out of Scope

Mengubah timezone/scheduler (perbaikan log WIB sudah beres); menambah step `workflow` baru;
memberi researcher akses server/SSH; microservice HTTP (FastAPI); auto-merge atau push ke
repo upstream.

## Further Notes

gpt-researcher bisa lambat dan mahal. `timeout_sec: 600` + `parallel: 1` sengaja dipilih
supaya satu riset tidak mengunci kapasitas; angka bisa dinaikkan dari dashboard. Karena
`can_run()` (`flow.py:1138-1140`) mensyaratkan `harness.has_tools`, researcher **tidak** akan
dianggap "bisa jalan sendiri" — dan itu benar: adapter mencari, bukan mengubah mesin.
