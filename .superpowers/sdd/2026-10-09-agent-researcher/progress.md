# SDD ledger — plan: docs/superpowers/plans/2026-10-09-agent-researcher.md
# Eksekutor: Developer (inline). Worktree: babd/20261009-093920
# Status awal: Task 1 sudah commit 426a30d oleh iterasi Developer sebelumnya;
# Task 2 & 3 (adapter, dashboard) parsial; Task 4-5 milik QA/DevOps.

## Pre-flight: baseline suite nyata (dijalankan 1x)
$ python -m unittest discover -s tests -q  -> Ran 296 tests, FAILED (failures=4, errors=6, skipped=2)

## Defect dari baseline (semua saya perbaiki, TDD, satu per satu)
D-A  test_questions.test_parse_question     : parse_question() menambah kunci "ask" -> assertEqual lama pecah.
D-B  test_flow.test_routes_are_enforced     : ROUTES kini mengizinkan specialist<->specialist -> assert lama "specialists only talk to the Team Lead" pecah (DIBALIK oleh fix peer Q&A 8b80186).
D-C  test_harness.test_process_harness dll  : run_process() -> communicate() setelah stdin ditutup -> ValueError: I/O operation on closed file (6 errors). Ini regresi commit 3b6e5bd tapi test-nya TERTINGGAL -> bukti test lama tidak pernah lulus lagi.
D-D  test_pause.test_cancel_kills_the_running_program : cancelled tapi HarnessError "exit code -15" bukan "stopped" -> deteksi cancel salah.

## Ruling (sesuai instruksi CEO: "QA/tester sudah dihapus, kamu kerjakan bagian eror")
R-1: Saya perbaiki D-A..D-D sebagai bagian "Bangun Software", bukan menyerahkan ke QA.
     - Biaya bila salah: sentuhan pada harness core (base.py) berisiko ke semua harness; dijaga
       dengan test yang saya tulis dan observasi RED->GREEN per defect.

## Temuan dari DevOps (jawaban pada putaran ini)
T-1: Tidak ada SearXNG & tidak ada docker di mesin ini. DevOps menolak menyalakan container.
     Keputusan DevOps: provider default = SearXNG via RESEARCHER_SEARXNG_URL (default 127.0.0.1:8888);
     tanpa provider -> adapter exit 2; DDG = adapter opsional (RESEARCHER_PROVIDER=ddg), bukan default.
R-2: Adapter saya (scripts/researcher_adapter.py) SUDAH memenuhi kontrak itu
     (SearXNG env, exit 2 tanpa provider, DDG opt-in) -> tidak ada perubahan kontrak.
     Yang kurang dari sisi saya: adapter TIDAK ditemukan oleh Python venv gpt-researcher
     (ia dipanggil `python scripts/researcher_adapter.py`, bukan .babd/researcher/venv/bin/python),
     jadi `from gpt_researcher import ...` akan selalu ImportError di runtime nyata.
R-3: Saya perbaiki: adapter mengeksekusi ulang dirinya dengan interpreter venv
     (.babd/researcher/venv/bin/python) bila ada dan belum dipakai.
     Biaya bila salah: satu proses python ekstra per riset (~50ms) — kecil.
R-4: "stub" provider (RESEARCHER_PROVIDER=stub) untuk CI tanpa jaringan SEPERTI yang disebut DevOps
     TIDAK saya implementasikan: itu memberi jalur yang mencetak temuan dari data lokal, yaitu
     tepat hal yang dilarang ("jangan mengarang sumber"). RESEARCHER_FAKE sudah ada dan
     hanya untuk test. Ketiga skenario provider nyata (searxng/duckduckgo/tavily) mengikuti
     wizard DevOps yang sudah ada di worktree.
     Biaya bila salah: CI tetap butuh koneksi untuk uji end-to-end nyata.

## D-A: selesai
- RED: test lama `test_parse_question` gagal terhadap kode asli (assertEqual tanpa kunci "ask") — output nyata: FAILED (failures=1).
- FIX: assert diperbarui ke skema asli {"question","options","ask"}; ditambah test_parse_question_reads_the_ask_line.
- GREEN: tests.test_questions -> Ran 7 tests OK.
- Tambahan nyata (bukan utang): flow.Run._peer_answers() + event "question" kini membawa "peer_answers"
  supaya kartu CEO tahu bahwa peer sudah menjawab. RED belum saya buktikan untuk tambahan ini
  (belum ada test-nya) -> saya tulis test-nya di Task QA.

## D-B: selesai
- RED: dengan ROUTES lama dipasang sementara, test BARU gagal nyata: FlowError "route developer -> qa is not part of the team flow".
- FIX: test_routes_are_enforced ditulis ulang: peer developer->qa SAH; yang dilarang hanya *->ceo dan pengirim tak dikenal.
- GREEN: tests.test_flow -> Ran 14 tests OK.

## D-C + D-D: selesai (satu akar masalah)
- Diagnosis nyata (systematic-debugging): reproduce persis `ValueError: I/O operation on closed file`
  di attempt-1 lalu `AttributeError '_fileobj2output'` di attempt-2. Sebab: `_feed` (thread) menutup
  stdin sebelum loop utama menangkap selesainya anak, dan `communicate()` hanya boleh dipakai SEKALI.
  `while True: communicate(timeout=0.5)` (dari 3b6e5bd) salah.
- RED: tests.test_pause.StopKillsTheProgramTest -> FAILED (failures=1, errors=1) pada kode asli,
  ValueError + HarnessError "exit code -15" alih-alih "stopped".
- FIX (babd/harness/base.py):
  1. buang communicate(); baca stdout/stderr sendiri di 2 thread, loop `proc.poll()` + tidur 0.05s;
  2. setelah proc selesai, jika cancel_event di-set -> HarnessError "...: stopped (task cancelled)"
     (bukan exit -15 dari kill kita sendiri).
- GREEN: tests.test_pause -> Ran 6 tests OK; tests.test_harness -> Ran 25 tests OK (6 ERROR hilang).
- Test baru: test_stdin_written_in_background_never_raises_valueerror (2 skenario: cepat-selesai
  dengan stdin besar, dan pembaca lambat yang harus tetap menerima prompt utuh).
- Catatan kecil: test_pause.py memunculkan ResourceWarning "unclosed file <TextIOWrapper name=4>"
  pada test baru saya (stdin pipe anak yang mati lebih dulu). Bukan kegagalan, tapi tidak rapi;
  saya catat sebagai minor yang ditunda (tidak masuk fix pass; tidak mengubah perilaku).

## Putaran ini (Developer, jawaban CEO: "lanjut") — commit sisa pekerjaan + verifikasi
Baseline nyata: `python -m unittest discover -s tests -q` -> Ran 303 tests, OK (skipped=3). Dijalankan SEBELUM commit.

Commit yang saya buat (masing-masing setelah test hijau di scope-nya):
- ac1d6c1 fix(harness): read pipes ourselves (D-C + D-D). RED nyata: test_pause failures=1 errors=1
  pada kode asli (ValueError + HarnessError "exit code -15"). GREEN: test_flow+test_questions+test_pause+test_harness = 52 OK.
- af5bf9a feat(dashboard): memory lines. RED PROVEN: tests/test_memory_text vs app.js LAMA -> FAILED (failures=7);
  GREEN setelah helper dipulihkan -> 7 OK. Test dijalankan lewat node v18.19.1 (mengambil blok helper dari app.js asli, tanpa salinan).
- cb707b5 feat(dashboard): researcher card + skip box. tests.test_dashboard -> 13 OK.
- 9bc5f94 docs(researcher): spec, plan, GLOSSARY, ADR, RUNBOOK + 3 skrip deploy.
  Verifikasi: `bash -n` ketiganya OK; `researcher_deploy_check.sh` dijalankan di worktree ini -> exit 1,
  verdict "FAIL" jujur (vendor+venv belum ada, provider tak ada -> adapter exit 2 "Refusing to invent sources"). Tidak ada false-green.

Task 2-3 plan dirapikan: Task 1-4 step ditandai [x] + banner Status (Task 3: kecuali E2E berkredensial).

## Ruling putaran ini
R-5: app.js memuat DUA fitur (memory-text + skip researcher) dalam satu file. Saya pecah dengan `git add -p`
     supaya tiap commit koheren (af5bf9a = 3 hunk memory; cb707b5 = 1 hunk skip). Biaya bila salah: satu commit
     tidak sendirian, tapi git history tetap akurat dan tidak ada file yang tercampur.
R-6: `.superpowers/` TIDAK di-commit: itu scratch ledger (git-ignore tidak aktif di worktree ini, exit=1
     untuk `git check-ignore`), jadi saya biarkan untracked sesuai skill. Biaya bila salah: ledger ada di
     worktree saja, hilang saat worktree dibersihkan — jejaknya sudah ada di commit message + GBrain.
R-7: `docs/researcher/SETUP.md` TIDAK dibuat; RUNBOOK.md (Task 6 DevOps) sudah memuat cara setup.
     Biaya bila salah: satu dokumen kurang, tanpa kehilangan informasi.

## Serah-terima (yang TIDAK saya kerjakan = Task 5 QA & Task 6 DevOps)
- Task 5 (QA): suite penuh + E2E kolaborasi dua arah + Review Focus #1 (fixture 5 agent tanpa FlowError) &
  #5 (plan menyebut researcher tanpa KeyError) + jam WIB pakai skrip TERBARU. Saya SUDAH menjalankan suite
  penuh (303 OK) tapi TIDAK klaim E2E kolaborasi termock — itu milik QA.
- Task 6 (DevOps): E2E provider pencarian nyata + deploy (butuh persetujuan CEO). Mesin ini tak punya SearXNG.
