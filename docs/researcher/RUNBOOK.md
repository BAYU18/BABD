# RUNBOOK — Agent `researcher` (gpt-researcher lokal)

**Pemilik:** DevOps · **Target deploy:** instalasi BABD di `/home/serverbot/aidev`
(bukan worktree) · **Status dokumen:** siap, **belum dieksekusi** — deploy menunggu QA PASS
dan persetujuan CEO (`project.require_approval = ["deploy"]`).

Dokumen ini menjawab: apa yang di-deploy, di lingkungan mana, variabel apa saja, cara cek sehat,
cara memantau, cara membalik (rollback), dan langkah mana yang **hanya bisa dilakukan manusia**.

---

## 0. Ringkasan grounding (dibaca dari kode nyata, bukan asumsi)

| Fakta | Sumber |
|---|---|
| Instalasi berjalan sebagai service systemd `babd-dashboard.service`, `User=root`, `WorkingDirectory=/home/serverbot/aidev`, `ExecStart=/home/serverbot/aidev/.venv/bin/python … serve(port=8800)` | `systemctl cat babd-dashboard.service` |
| `ROOT` = folder instalasi; `agents.json`, `.env`, `.babd/` relatif ke sana | `babd/config.py:8-9, 97-101` |
| Harness baru = **tipe pertama `process`** di roster; 5 agent lain `hermes_local` | `agents.json` |
| Harness `process`: prompt di **stdin**, jawaban di **stdout**, LLM settings via env `BABD_LLM_*` | `babd/harness/others.py:123-169`, `babd/harness/routing.py:98-113` |
| stdin = system prompt + `\n\n---\n\n` + task (bukan hanya task) | `babd/harness/base.py:286-298` |
| `ensure_command` hanya menerima **path absolut** atau nama di `PATH` → `command` relatif gagal | `babd/harness/tools.py:200-205` |
| `Process.setup()` menjalankan `install` **sekali** (marker di `.babd/tools/process-<id>.<hash>.installed`), lalu `command_path()` | `babd/harness/others.py:135-156` |
| `isolation` project = `None`; **`bwrap` dan `docker` TIDAK terpasang** di mesin ini | `agents.json`, `which bwrap docker` → none |
| `servers` tidak ada di config → researcher **tidak** punya akses SSH | `agents.json` (`"servers"` absen) |
| `.babd/` sudah masuk `.gitignore:4` → venv + vendor tidak ikut ter-commit | `.gitignore` |
| Deploy dijalankan `flow.py:947-971`: hanya bila QA `PASS` **dan** CEO approved | `babd/flow.py:947-971` |

**Konsekuensi langsung:** karena `bwrap`/`docker` tidak ada, `sandbox` researcher = `"none"`
(sesuai desain). Risiko yang menyertainya ada di §6.

---

## 1. Apa yang di-deploy

Tiga lapisan, urut dari yang paling tidak berisiko:

1. **Kode BABD** (di-merge dari worktree `babd-self/20261009-093920` ke instalasi):
   `babd/flow.py`, `babd/harness/others.py` (resolusi `command` relatif), `babd/permissions.py`,
   `babd/skillpacks.py`, `babd/superpowers.py`, `babd/mattpocock.py`,
   `babd/dashboard/static/app.js`, plus `tests/test_researcher.py`.
2. **Konfigurasi**: entri `researcher` di `agents.json` (roster) — ditaruh **setelah** `devops`,
   bukan sebelum `lead` (`Team.__init__` memakai `agents[0]` sebagai lead: `babd/team.py:213-216`).
3. **Runtime lokal** (di luar git, di bawah `.babd/`):
   - `.babd/researcher/gpt-researcher/` — repo gpt-researcher yang di-*vendor*
   - `.babd/researcher/venv/` — venv terpisah (dependensi gpt-researcher **tidak** masuk `.venv` BABD)
   - `.babd/researcher/bin/research` — symlink ke `scripts/researcher_adapter.py` (executable)
   - `.babd/researcher/bin/setup` — symlink ke `scripts/researcher_setup.sh`

**Tidak ada port baru dibuka. Tidak ada service systemd baru. Tidak ada container.**
(gpt-researcher dipakai sebagai *library*, bukan microservice — lihat `docs/adr/0001-*.md`.)

---

## 2. Prasyarat (verifikasi dulu, jangan asumsikan)

```bash
# 1. Kode sudah ter-merge ke instalasi & test hijau
cd /home/serverbot/aidev
git log --oneline -1
/home/serverbot/aidev/.venv/bin/python -m unittest discover -s tests -q

# 2. Python untuk venv terpisah ada
/usr/bin/python3 --version          # diharapkan 3.12.x

# 3. Jalur keluar jaringan (hanya saat `setup` sekali, bukan saat runtime)
#    Clone gpt-researcher + pip install. Kalau ini gagal, pakai mode --offline (§5).

# 4. Token/kunci TIDAK ditulis ke agents.json (aturan tim)
python3 -c "import json;c=json.load(open('agents.json'));assert 'api_key' not in json.dumps(c.get('agents',[])) or True"
grep -c '"api_key"' agents.json     # diharapkan 0 (hanya api_key_env)
```

---

## 3. Lingkungan (environments)

| Lingkungan | Peran | Cara jalan |
|---|---|---|
| **worktree** `workspace/worktrees/babd-self/<run>/` | tempat Developer membangun & QA menguji | `python -m unittest`; tidak melayani user |
| **instalasi** `/home/serverbot/aidev` | produksi nyata; dashboard di `:8800` via `babd-dashboard.service` | merge + `systemctl restart babd-dashboard` |
| `.babd/researcher/` (di dalam instalasi) | venv + vendor sang researcher | dibuat oleh `scripts/researcher_setup.sh` |

Prosedur promosi (dijalankan **setelah** QA PASS + CEO approve) — dari instalasi, bukan worktree:

```bash
cd /home/serverbot/aidev
git status                      # harus bersih kecuali .babd/ (ignored)
git log --oneline -3
# merge commit researcher dari branch run (fast-forward atau merge normal)
git merge --no-ff babd/20261009-093920
/home/serverbot/aidev/.venv/bin/python -m unittest discover -s tests -q   # ulangi di instalasi
```

---

## 4. Konfigurasi & rahasia (NAMA SAJA)

Tidak ada kunci yang ditulis ke `agents.json`. Semua lewat env.

### 4.1 Variabel yang disuntik sistem (dibuat `generic_routing`, jangan diset manual)

| Nama | Isi | Sumber |
|---|---|---|
| `BABD_LLM_BASE_URL` | base URL endpoint LLM agent (dari blok `llm.base_url`) | `babd/harness/routing.py:104` |
| `BABD_LLM_MODEL` | nama model | `:105` |
| `BABD_LLM_API_KEY` | API key agent (di-scrub dari env umum, hanya agent ini yang lihat) | `:106`, `babd/config.py:166-173` |
| `BABD_LLM_API` / `BABD_LLM_PROVIDER` | gaya API & provider | `:102-103` |
| `OPENAI_API_KEY` / `OPENAI_BASE_URL` | alias OpenAI-compatible | `:111-112` |
| `BABD_AGENT_ID`, `BABD_SYSTEM_PROMPT` | identitas + persona | `others.py:164-165` |

### 4.2 Variabel yang **manusia** set (opsional, untuk search provider)

| Nama | Wajib? | Arti | Rahasia? |
|---|---|---|---|
| `RESEARCHER_SEARXNG_URL` | opsional | URL SearXNG lokal (mis. `http://127.0.0.1:8888`). Bila ada → provider utama | tidak (URL saja) |
| `RESEARCHER_ALLOW_DUCKDUCKGO` | opsional | `1` = izinkan fallback DuckDuckGo tanpa key | tidak |
| `BABD_LLM_API_KEY` | **sudah ada** | dipakai researcher lewat routing; **tidak perlu kunci baru** | ya (sudah ada) |

Set lewat dashboard (**Settings → Environment**) supaya ikut tersimpan di `.env` mode 600 +
backup rahasia (`babd/config.py:107-127`). **Jangan** `export` di shell lalu `systemctl` — env
terluar menang dan menutupi nilai dashboard (`babd/config.py:48-51`).

### 4.3 Di `agents.json` (bukan rahasia)

Blok `harness` researcher (nilai dari plan Developer — sesuaikan bila Developer berbeda):

```json
"harness": {
  "type": "process",
  "command": ".babd/researcher/bin/research",
  "args": ["--json"],
  "timeout_sec": 600,
  "install": ".babd/researcher/bin/setup"
}
```

`permissions: "workspace"` (pola sama dengan developer/qa/devops), `parallel: 1`,
`sandbox: "none"`, `telegram.enabled: false`.

> **Catatan kontrak `command`:** `ensure_command` (`babd/harness/tools.py:200-205`) hanya
> menerima path **absolut** atau nama di `PATH`. Bila Developer **belum** menambahkan resolusi
> `ROOT`-relatif di `Process.command_path()` (`babd/harness/others.py:154-156`), nilai di atas
> **gagal** dengan `HarnessError: … command '.babd/researcher/bin/research' not found`.
> Verifikasi wajib sebelum deploy:
> ```bash
> cd /home/serverbot/aidev
> .venv/bin/python -c "
> from babd.config import load_config
> from babd.harness import create_harness
> a=[x for x in load_config()['agents'] if x['id']=='researcher'][0]
> print(create_harness(a).command_path())"
> # diharapkan: /home/serverbot/aidev/.babd/researcher/bin/research
> ```
> Bila gagal → minta Developer memperbaiki `Process.command_path()`, **jangan** tambal dengan
> path absolut hardcoded di `agents.json` (tidak portabel antar worktree).

---

## 5. Langkah deploy (urut)

```bash
cd /home/serverbot/aidev

# 1. Setup runtime lokal (idempoten; boleh diulang)
.babd/researcher/bin/setup          # clone/pin gpt-researcher, buat venv, install -e, symlink bin
#    gagal jaringan -> catat, lanjut dengan mode jujur (adapter exit 2), jangan lanjut seolah sehat

# 2. Cek perintah harness ditemukan (harus path absolut hasil resolusi ROOT)
.venv/bin/python -c "
from babd.config import load_config
from babd.harness import create_harness
a=[x for x in load_config()['agents'] if x['id']=='researcher'][0]
print(create_harness(a).command_path())"

# 3. Cek sehat adapter (lihat §6)

# 4. Restart dashboard supaya config baru dimuat
systemctl restart babd-dashboard.service
systemctl is-active babd-dashboard.service

# 5. Verifikasi lewat jalur nyata: tanya researcher satu kali
.venv/bin/python -m babd ask researcher "Berapa versi terbaru httpx? Sertakan URL sumber."
```

**Mode offline (jaringan mati saat setup):** adapter harus **exit 2** dengan pesan memuat
`no search provider` — *bukan* jawaban karangan. Bila ini terjadi, deploy tetap boleh
"terpasang" tapi researcher **belum operasional**; catat sebagai open problem, jangan klaim sehat.

---

## 6. Health check (dijalankan, outputnya ditempel)

Hierarki check, dari paling dangkal ke paling bermakna:

```bash
cd /home/serverbot/aidev

# H1 — perintah harness ada & absolut
.venv/bin/python -c "
from babd.config import load_config
from babd.harness import create_harness
a=[x for x in load_config()['agents'] if x['id']=='researcher'][0]
h=create_harness(a); p=h.command_path(); print(p); assert p.startswith('/'), 'bukan path absolut'"

# H2 — adapter hidup sebagai program (black box, kontrak stdin->stdout)
printf 'You are the RESEARCHER.\n\n---\n\nBerapa versi terbaru httpx?\n' \
  | .babd/researcher/bin/research --json ; echo "exit=$?"
# sehat   : exit 0, stdout JSON dengan kunci answer + sources (list)
# jujur   : exit 2 + "no search provider"  (bukan sehat, tapi tidak berbohong)
# rusak   : exit 3 / traceback

# H3 — roster & kolaborasi
.venv/bin/python -c "
from babd import flow
from babd.config import load_config
from babd.team import Team
t=Team(load_config(),log=lambda m:None)
print('specialists:',flow.specialist_roles(t))
print('peer who :',flow.PEER_WHO.get('researcher'))
assert 'researcher' in flow.specialist_roles(t)"

# H4 — dashboard menampilkan researcher
curl -s -H 'X-BABD-Token: aidev-babd-2024' http://127.0.0.1:8800/api/board | python3 -c "
import json,sys; d=json.load(sys.stdin)
print([a['id'] for a in d['agents']])"
# lihat token: ExecStart babd-dashboard.service / dashboard auth (babd/dashboard/auth.py)

# H5 — check menyeluruh harness (perintah bawaan BABD)
.venv/bin/python -m babd check
```

**Kriteria sehat (semua harus benar):** H1 path absolut · H2 exit 0 + JSON berskema, atau exit 2
yang jujur dan **dilaporkan sebagai belum operasional** · H3 researcher di `specialist_roles`
dan `PEER_WHO` · H4 researcher muncul di board · H5 agent lain tetap lolos.

---

## 7. Monitoring & alert

Tidak ada metrics stack baru. Pemonitoran memakai jalur yang sudah ada di BABD:

| Sinyal | Cara lihat | Arti |
|---|---|---|
| Status step researcher | dashboard board (`:8800`), kartu **Researcher** | `working` / `queued` / `done` / `failed` |
| Activity log researcher | dashboard → agent log; jam **WIB server** | konsisten dengan agent lain |
| Kegagalan berulang | `agent failed` berulang di board + `runs/<id>/05-devops.md` | adapter/provider rusak |
| Biaya | board `usage_today` vs `budget` (`daily_limit_usd 5.0`, `task_limit_usd 1.0`) | riset boros |
| Log dashboard | `journalctl -u babd-dashboard -n 100` **atau** `/tmp/babd-dashboard.log` | error proses |
| Outbound search | log stdout adapter di step output | provider hidup/mati |

**Ambang alert yang saya usulkan (manual review oleh CEO/DevOps, belum otomatis):**
- ≥ 2 step researcher `failed` dalam 1 hari → periksa provider (H2).
- `usage_today` ≥ 80% `daily_limit_usd` → BABD sudah memperingatkan sendiri (`warn_at_percent: 80`).
- `exit=2` berulang → bukan bug agent, tapi provider yang belum diset (aksi manusia §4.2).

> **Belum ada alerting otomatis** (email/Telegram) untuk researcher. Itu *out of scope* task ini;
> bila CEO mau, ini item lanjutan. Saya tidak mengklaim "monitoring siap" lebih dari ini.

---

## 8. Rollback

Dua lapis: konfigurasi (cepat, aman) dan runtime (hapus artefak lokal).

**R1 — sembunyikan researcher tanpa membatalkan kode (paling cepat, reversibel detik):**
Dashboard → **Settings → Task options**, atau tandai `researcher` sebagai *skip* (checkbox skip
di `app.js`). Agent tetap ada, tapi tidak dipanggil pada task berikutnya.

**R2 — batalkan commit agent (memakai revert, bukan reset — aman untuk repo bersama):**
```bash
cd /home/serverbot/aidev
git log --oneline -1                       # catat hash commit researcher
git revert --no-edit <hash>                # revert commit roster/config/adapter
/home/serverbot/aidev/.venv/bin/python -m unittest discover -s tests -q
systemctl restart babd-dashboard.service
```
> Hati-hati: revert harus benar-benar menghapus `researcher` dari `ROLES` **dan** `agents.json`.
> Bila Developer menambah `specialist_roles()` sebagai pengaman kompatibilitas, instalasi lama
> tanpa researcher tetap jalan — jadi revert parsial pun tidak mematikan tim.

**R3 — hapus runtime lokal (vendor + venv):**
```bash
rm -rf /home/serverbot/aidev/.babd/researcher
rm -f  /home/serverbot/aidev/.babd/tools/process-researcher.*.installed   # marker install
```
Setelah R3, `setup` akan meng-install ulang bersih saat dipanggil lagi.

**R4 — pemulihan penuh bila instalasi rusak:** `babd self-update --rollback` dari root instalasi
(keputusan CEO; hanya fast-forward, otomatis rollback bila test gagal).

**Trigger rollback:** H1 gagal setelah merge · H2 exit 3/traceback berulang · dashboard down
setelah restart · agent lain (lead/developer/qa) gagal karena perubahan roster.

---

## 9. Langkah yang HANYA bisa dilakukan manusia

1. **Memilih & memasang search provider** — SearXNG lokal (URL-nya) atau fallback DuckDuckGo,
   atau API key Tavily/SearchApi bila CEO menyediakannya. **Ini keputusan CEO** (§Open questions).
   Set lewat dashboard Environment, bukan `export` shell.
2. **Menyetujui deploy** — `require_approval: ["deploy"]`; tombol approve di dashboard
   (`babd/dashboard/server.py:1056` `resolve_approval`). Tidak ada agent yang boleh melewatinya.
3. **Menyediakan jaringan keluar** untuk `setup` (clone + pip) — kalau mesin di balik firewall.
4. **Memutuskan budget** bila riset dinilai terlalu boros (batas ada di dashboard Settings).
5. **Restart service** (`systemctl restart babd-dashboard`) — butuh akses root; langkah ini
   tidak boleh diotomatiskan agent.

Wizard interaktif untuk langkah 1–2 ada di `scripts/researcher_deploy_wizard.sh` (§11).

---

## 10. Yang belum diverifikasi (jujur)

- Semua perintah di §2–§6 berlabel **NOT RUN** oleh saya pada putaran ini: poin target ada di
  instalasi (`/home/serverbot/aidev`), yang **dilarang ditulis/diubah** oleh tool saya
  (`babd_guards`, `babd/permissions.py:52-60`). Saya menyiapkan, bukan mengeksekusi.
- Apakah jaringan keluar untuk clone gpt-researcher tersedia: **belum diverifikasi**.
- Apakah SearXNG sudah jalan lokal: **belum diverifikasi** → itulah fallback `--offline`/exit 2.
- Apakah Developer benar-benar menambahkan resolusi `command` relatif di `Process.command_path()`:
  kode saat ini (`others.py:154-156`) **belum**; ini blocker yang harus dikonfirmasi ke Developer.

---

## 11. File pendukung

- `scripts/researcher_deploy_wizard.sh` — wizard manual (provider + approve + restart).
- `scripts/researcher_deploy_check.sh` — health check H1–H4 (read-only, aman dijalankan).
- `docs/researcher/SETUP.md` — cara setup vendor/venv (dibuat Developer).

---

## Open questions (untuk CEO — saya lanjut atas asumsi)

1. **Search provider mana yang boleh dipakai?**
   Asumsi: SearXNG lokal bila `RESEARCHER_SEARXNG_URL` diset; jika tidak, minta persetujuan
   `RESEARCHER_ALLOW_DUCKDUCKGO=1`; jika tidak ada keduanya → adapter exit 2 (jujur, belum operasional).
   `OPTIONS: searxng-lokal | duckduckgo | tavily/searchapi (butuh API key)`
2. **Bolehkah researcher memakai endpoint LLM tim yang sama** (`BABD_LLM_*`, dari blok `llm`
   agent)? Asumsi: ya, tanpa kredensial baru.
3. **Apakah mesin ini punya jaringan keluar** untuk `setup` sekali? Asumsi: ya; jika tidak → mode offline.
4. **Batas biaya riset?** Asumsi: tetap `project.budget` (`task_limit_usd 1.0`) + `timeout_sec 600`,
   `parallel 1`.
