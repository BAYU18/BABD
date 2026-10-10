# PROPOSAL PENGEMBANGAN LANJUTAN — PROYEK `dotbox`

**Tanggal:** 2026-10-10
**Penulis:** Architect (paket p4) — menyintesiskan hasil paket p1 (rancangan turn-queue + skema save), p2 (aksesibilitas + telemetri), p3 (bukti eksekusi), jawaban QA, dan **verifikasi ulang baris-per-baris langsung dari workspace ini**.
**Branch:** `babd/20261010-214601`
**Tujuan:** menjawab pertanyaan CEO "apa lagi yang harus dikembangkan dari proyek `dotbox`" dengan usulan konkret, berprioritas, dan jujur soal tingkat bukti.

> **Aturan kejujuran bukti (ADR-0002) yang dipakai dokumen ini.**
> - **[TERVERIFIKASI]** — penulis **membaca langsung baris kode tersebut di workspace ini**, atau ada bukti eksekusi nyata (perintah + keluaran mentah) yang **disebutkan berkas dan barisnya**.
> - **[ASUMSI]** — masuk akal tetapi **belum** diuji/disetujui.
> - **[SITASI]** — keluaran perintah milik agen lain yang saya **baca dari berkas bukti**, bukan hasil eksekusi saya. Tetap bukti, tetapi tetap saya sebut sumbernya.
> **Tidak ada** klaim "selesai" di dokumen ini tanpa bukti. Semua usulan berstatus *usulan*, bukan *hasil*.

> **Catatan kejujuran: penulis (p4) tidak punya akses shell di langkah ini.**
> Saya **tidak menjalankan** `node --test`. Karena itu semua angka suite saya tandai **[SITASI]** dan menyebut berkas sumbernya. Yang bisa dan sudah saya lakukan sendiri adalah **membaca kode dan memeriksa nomor baris** — itulah dasar seluruh tabel §2.1.

> **Catatan revisi ke-3 (2026-10-10, oleh p4 setelah verifikasi QA revisi-2).** Tiga koreksi diterapkan:
> 1. **§2.3 & §7.6 — angka 52/52 adalah USANG, bukan "berkas fiktif".** Saya membaca sendiri `docs/bukti/node-test-polos-qa.txt:266–275`: berkas itu **ada** dan berisi `# tests 52 / # pass 52 / # fail 0 / # exit=0` (commit `3d2eebc`, pra-P1). Revisi ke-2 keliru mengikuti catatan QA ("berkas tidak pernah ada"). Yang benar: riwayat 43/43 → **52/52** → 42/14 → **56/56**; angka terkini tetap **56/56 `exit=0`**.
> 2. **§4 P2(b) — angka pasti.** Sumber `null` di `script.js:808` (versi) dan `:810–812` (kunci wajib); pesan tunggal gabungan di `:900`. Dulu ditulis ":900 area" (koreksi QA).
> 3. **§7.5 — rujukan berkas salah.** `node-test-polos-qa.txt` → `node-test-qa-polos.txt` (yang berisi 56/56).

> **Catatan revisi ke-2 (2026-10-10).** Setelah QA memverifikasi silang: (a) angka `docs/bukti/node-test-qa-polos.txt` adalah **56/56 `exit=0`** — draf sebelumnya keliru menyebut berkas "52/52" yang **tidak pernah ada**; sudah dikoreksi di §2.3, §7.6, dan ditambah blok bukti di §7.7. (b) QA mengonfirmasi lewat eksekusi bahwa `script.js:756` masih `if (!move) return;` dan `index.html:5` masih `user-scalable=no` → P0 dan P3 kini **[TERVERIFIKASI]** (kode + verifikasi pihak ketiga), bukan lagi asumsi keberadaan. (c) Nama berkas `docs/bukti/node-test-p1-terpasang.txt` (42/14) dikonfirmasi tepat; bukan tertukar.
> **→ Koreksi ke-2(a) dicabut sebagian oleh revisi ke-3 di atas:** klaim "berkas 52/52 tidak pernah ada" **salah**; klaim tersebut yang perlu dicabut, sedangkan angka terkini 56/56 tetap benar.
> - **P1 (wiring produksi turn-queue) SUDAH TERPASANG** — [TERVERIFIKASI]: `script.js:45–53` (impor + `createTurnQueue()`), `:191`, `:604`, `:641`, `:933` (`turnQueue.schedule(makeAIMove, …)`), `:734` (`turnQueue.schedule(executeAIMove, 300)`); `aiMoveTimeout` **sudah dihapus**; `index.html:118` **sudah memuat** `turn-queue.js` (sebelum `script.js` di `:120`); `resetBoardOnly` (`:1064`) dan `loadGame` (`:885`) memanggil `turnQueue.clear()`.
> - **P2 (versi skema save) SUDAH TERPASANG** — [TERVERIFIKASI]: `script.js:768` `SCHEMA_VERSION = 1`, `:769–772` `versiDikenal()`, `:776` `version: SCHEMA_VERSION` di `saveGame`, `:808` `buatKandidatState` menolak versi tak dikenal.
> - **Suite terkini = 56/56 lulus, `exit=0`** — [SITASI], `docs/bukti/p1-terpasang.txt:150–158`. Ini **menggantikan** angka 52/52 di draf lama.
> - **Nomor baris bergeser** karena kode bertambah. Nomor lama **tidak boleh dipakai lagi**: fallback AI `null` bukan `:746` melainkan **`:756`**; `saveGame()` di `makeMove` bukan `:575` melainkan **`:585`**; `hitRadius` bukan `:460` melainkan **`:470`**; `Box.edges` bukan `:142` melainkan **`:152–157`**; tulis ukuran kanvas bukan `:196–197` melainkan **`:206–207`** dan `:224–225`.
> Karena itu dokumen ini menyebut **kedua nomor** (lama → baru) supaya pembaca yang memegang brief lama tidak salah merujuk.

---

## 1. Ringkasan untuk CEO (5 baris)

1. **Kabar baik:** jalur inti `dotbox` sehat dan dua pekerjaan teknis besar **sudah mendarat**: penjadwal giliran AI tunggal (`turn-queue.js`) **sudah terpasang** di `script.js`, dan **versi skema save** sudah ada. Seluruh suite **56/56 lulus, `exit=0`** ([SITASI] `docs/bukti/p1-terpasang.txt:150–158`).
2. **Celah paling berisiko bagi pemain** kini tinggal **satu**: bila AI tidak menemukan langkah, `executeAIMove` keluar tanpa pesan → **giliran menggantung diam-diam** (`script.js:756`, dulu `:746`) [TERVERIFIKASI + dibuktikan dinamis oleh p3]. Ini **P0**, effort **S**.
3. Untuk **seluler & pembaca layar**, produk praktis masih **tertutup**: `user-scalable=no` (`index.html:5`) mematikan zoom dan **`aria-label` di `index.html` = 0** [TERVERIFIKASI].
4. Sisa utang teknis **murah tapi berharga untuk pemeliharaan**: skema `Box` ganda (`rules.js:42` vs `script.js:152–157`, field `edges` = *dead write*) dan penulisan save **setiap langkah** (`script.js:585`) [TERVERIFIKASI].
5. Yang **belum ada sama sekali**: test E2E di peramban nyata, PWA, uji perangkat HiDPI, dan walkthrough pembaca layar — semuanya **investasi jangka panjang** yang butuh keputusan CEO (§5.2).

**Saran urutan eksekusi:** **P0 → P3 → P6 → P2 → P5 → P4 → P7**. Tidak ada item yang boleh dianggap "selesai" tanpa keluaran perintah yang dilampirkan.

---

## 2. Kondisi saat ini

### 2.1 Terverifikasi — dibaca langsung dari workspace ini (2026-10-10)

| # | Temuan | Bukti (berkas:baris) | Nomor di brief lama | Catatan |
|---|---|---|---|---|
| V1 | `user-scalable=no` + `maximum-scale=1.0` mematikan zoom | `index.html:5` | sama | Dibaca langsung ulang; cocok laporan QA |
| V2 | Tombol mode gelap hanya `title`, tanpa `aria-label` | `index.html:15` | sama | Dibaca langsung ulang |
| V3 | Blok tombol replay tanpa `aria-label` | `index.html:94–97` | `:94-97` | `▶️ ⏮️ ⏭️ ❌`; baris **94–97** (koreksi QA benar) |
| V4 | `aria-label` di `index.html` = **0** (defisit sistemik) | pencarian `index.html` → 0 hasil | `:94-97` | Konsisten dengan temuan QA (repo-wide = 0) |
| V5 | `playAgainBtn` juga tanpa label | `index.html:108` | — | Tidak ada `aria-label`/`title` |
| **V6** | **P1 TERPASANG:** impor + instance penjadwal tunggal | `script.js:45–53` | `:181` | Sejak P1; meniru pola `Rules` (`:40–43`) |
| **V7** | **P1 TERPASANG:** 4 jalur penjadwalan lewat `turnQueue` | `script.js:191`, `:604`, `:641`, `:933` | `:181/:594/:631/:724` | **Bukan** `setTimeout(() => makeAIMove())` lagi |
| **V8** | **P1 TERPASANG:** satu penundaan eksekusi AI lewat penjadwal | `script.js:734` `turnQueue.schedule(executeAIMove, 300)` | `:724` | Pembungkusan `setTimeout` ganda **sudah hilang** |
| **V9** | `aiMoveTimeout` **sudah dihapus** | pencarian `aiMoveTimeout` di `script.js` → 0 hasil | `:720` | Dulu variabel mati; kini tidak ada |
| **V10** | **P1 TERPASANG:** `turnQueue.clear()` di reset & load | `script.js:1064` (`resetBoardOnly`), `:885` (`loadGame`) | tidak ada | Dulu **belum ada sama sekali** |
| **V11** | **P1 TERPASANG:** `index.html` memuat `turn-queue.js` **sebelum** `script.js` | `index.html:118` (turn-queue) vs `:120` (script) | `:117–119` | Kontrak urutan `rules.js:117` lebih dulu tetap dijaga |
| **V12** | `getBestMove()` `null` → `return` tanpa fallback/pesan/giliran ulang → **giliran menggantung** | `script.js:756` `if (!move) return;` | **`:746`** | Dibaca langsung; juga dibuktikan **dinamis** oleh p3 (bagian 3a) |
| **V13** | **P2 TERPASANG:** `SCHEMA_VERSION` + `versiDikenal()` + tulis `version` | `script.js:768`, `:769–772`, `:776` | `:756` | Save tanpa `version` → dianggap v1 (warisan) |
| **V14** | **P2 TERPASANG:** `buatKandidatState` menolak versi tak dikenal | `script.js:808` | `:785` | Pesan galat terpisah dari "struktur tak valid" |
| V15 | Skema `Box` **ganda**: `rules.js` `{ owner }`; `script.js` menulis `{ owner, edges }` | `rules.js:42` vs `script.js:152–157` | `rules.js:41` vs `script.js:142` | `edges` di kotak = *dead write* (0 pembaca, dibuktikan p3) |
| V16 | `saveGame()` dipanggil di tengah `makeMove` — tiap langkah menulis `localStorage` | `script.js:585` | **`:575`** | Dibaca langsung |
| V17 | `AudioContext` dibuat lazy dan di-`resume`; tiap `playSound` membuat oscillator baru | `script.js:74–101` | `:51-101` | Dibaca langsung |
| V18 | Hit-test pointer memakai CSS px dan **tidak pernah** menyentuh `devicePixelRatio` | `script.js:446–448`, `:460–463`, `hitRadius = 30` di `:470` | `:436-438/:450-453/:460` | Dibaca langsung |
| V19 | `canvas.width/height` ditulis sebagai CSS px langsung; **tidak ada** `ctx.scale`/`setTransform` DPR | `script.js:206–207`, `:224–225` | `:196–197/:214–215` | Dibaca langsung |
| V20 | Modul `turn-queue.js` **ada**, antarmuka kecil, single-slot | `turn-queue.js:32–90`, `:93–103` | sama | `createTurnQueue(deps?)`, `shouldScheduleAI(state)` |
| V21 | Test wiring produksi P1 **ada dan menuntut** pemasangan | `test/p1-wiring.test.js` (4 test A–D) | tidak ada | **Test ini yang menutup celah "hijau ≠ terpasang"** |
| V22 | Suite penuh **56/56 lulus, `exit=0`** | [SITASI] `docs/bukti/p1-terpasang.txt:150–158` (`1..56`, `# pass 56`, `# fail 0`, `# exit=0`) | 52/52 | Bukti terbaru; test ke-13..16 = wiring P1, ke-37..41 = save-schema |

### 2.2 Asumsi (belum terbukti — jangan diperlakukan sebagai fakta)

| # | Asumsi | Kenapa belum terbukti | Yang harus membuktikan |
|---|---|---|---|
| A1 | Menghapus `user-scalable=no` memulihkan pinch-zoom di semua peramban sasaran | Belum diuji di perangkat nyata; sebagian peramban mengabaikan atribut ini | Uji manual peramban + QA |
| A2 | Menambah `aria-label` membuat tombol terbaca pembaca layar | Belum ada uji NVDA/VoiceOver | QA (walkthrough pembaca layar) |
| A3 | ARIA live region mengumumkan giliran/skor tanpa merebut fokus | Desain murni, belum ada implementasi | Implementasi + QA |
| A4 | `prefers-reduced-motion` yang dihormati memperbaiki pengalaman pengguna sensitif gerak | Belum ada kode yang memeriksa media query ini | Implementasi + QA |
| A5 | Perbaikan DPR adalah isu **ketajaman render**, **bukan** bug hit-test aktif | Rasio bitmap:CSS saat ini 1:1 sehingga `hitRadius=30` (`:470`) tidak meleset; ini pembacaan kode, bukan uji layar Retina | Uji perangkat HiDPI |
| A6 | Memasang `turnQueue` (sudah selesai) tidak mengubah perilaku yang sudah lulus tes | **Sudah didukung bukti:** `test/p1-wiring.test.js` 4/4 hijau + suite 56/56 ([SITASI] `docs/bukti/p1-terpasang.txt`) → asumsi ini **naik status menjadi terverifikasi-lewat-test**; sisa risikonya hanya pada perangkat nyata | QA di peramban nyata |
| A7 | `version: 1` cukup untuk migrasi save lama ber-`edges` | Implementasi & test versi **ada dan hijau**, tetapi **belum ada** test khusus "save lama ber-`edges` tetap dimuat utuh" | `developer` (test migrasi) + `qa` |
| A8 | Kesiapan PWA/E2E (P7) layak dikerjakan | Belum ada manifest/service worker; ini usulan, bukan temuan cacat | Keputusan CEO (§5.2) |
| A9 | Timer "dianggap" tidak menumpuk karena suite hijau | Suite membuktikan modul & wiring, **bukan** pengalaman pemain di peramban sungguhan (tidak ada E2E) | P7 (E2E peramban) |

### 2.3 Catatan angka yang wajib dipakai penulis & QA berikutnya

- **Koreksi berantai atas angka suite (diverifikasi ulang oleh p4 pada revisi ke-3).** Riwayat yang bisa ditelusuri: **43/43** (subset baseline, `docs/bukti/output-node-test.txt`) → **52/52** (`docs/bukti/node-test-polos-qa.txt`, `:266–275`, commit `3d2eebc`; 52 test pra-P1) → **56 tes: 42 lulus / 14 gagal** (`docs/bukti/node-test-p1-terpasang.txt`, hasil **antara** saat `script.js:50` masih `require` di sandbox `vm`) → **56/56 `exit=0`** ([SITASI] `docs/bukti/node-test-qa-polos.txt:285–294` **dan** `docs/bukti/p1-terpasang.txt:150–158`). **Angka yang benar untuk dikutip hari ini adalah 56/56 `exit=0`.**
- **Peringatan tafsir berkas (dikoreksi lagi pada revisi ke-3).** Ada **dua** berkas bernama hampir sama, keduanya **ada**, dan **satu** berkas berisi hasil antara:
  - `docs/bukti/node-test-p1-terpasang.txt` → berakhir **`# tests 56 / # pass 42 / # fail 14`** (berkas INI yang isinya 42/14). 14 gagal = 3 test `bukti-eksekusi.test.js` (assert kode lama) + 11 `qa-regressions`/`script-integration` (`require is not defined`). **Jangan dikutip sebagai keadaan akhir.**
  - `docs/bukti/p1-terpasang.txt:150–158` → **`# pass 56 / # fail 0 / # exit=0`**.
  - `docs/bukti/node-test-qa-polos.txt:285–294` → **`# pass 56 / # fail 0 / exit=0`** (dijalankan QA, commit `da43ef4`).
  - `docs/bukti/node-test-polos-qa.txt:266–275` → **`# tests 52 / # pass 52 / # fail 0 / # exit=0`** (commit `3d2eebc`, **pra-P1**). Berkas ini **ada**, bukan hantu.
  - ⚠️ **Koreksi revisi ke-3 dokumen ini.** Draf revisi ke-2 (mengikuti catatan QA) menulis bahwa berkas berisi **52/52** "**tidak pernah ada**" dan menuduh angka 52/52 sebagai kekeliruan. Setelah saya baca sendiri `docs/bukti/node-test-polos-qa.txt` (`:266–275`), **klaim itu yang salah**: berkas **ada** dan isinya memang **52/52 `exit=0`** pada commit `3d2eebc` (sebelum P1/P2 mendarat). Yang benar bukan "berkasnya fiktif", melainkan: **angka 52/52 sudah USANG** — setelah P1 (`test/p1-wiring.test.js`) dan P2 (`test/save-schema.test.js`) masuk, jumlahnya menjadi **56**. **Kutip `p1-terpasang.txt` atau `node-test-qa-polos.txt` (56/56); jangan kutip `node-test-polos-qa.txt` sebagai keadaan terkini.**
  - Di `docs/bukti/VERIFIKASI-QA-REVISI-2.md:59` QA juga mencatat "nama berkas `node-test-polos-qa.txt` … tidak pernah ada" — itu **keliru** dan sebaiknya dicabut di laporan QA; saya tidak mengubah berkas milik QA.
- **Non-klaim tegas.** "56/56 hijau" berarti **modul + wiring produksi + skema save lulus test mereka**. Ia **tidak** membuktikan: (a) AI tidak pernah menggantung (V12 masih `return` telanjang), (b) aksesibilitas, (c) ketajaman HiDPI, (d) perilaku di peramban nyata.
- **Angka yang benar untuk dikutip:** "56/56 `node --test` polos lulus `exit=0` (bukti `docs/bukti/p1-terpasang.txt`); P1 & P2 **terpasang**; **P0 (fallback AI), P3, P5–P7 belum dikerjakan**."

---

## 3. Roadmap prioritas P0–P3

**Legenda.**
- **Prioritas:** **P0** (kritis, harus) · **P1** (tinggi, segera) · **P2** (sedang) · **P3** (jangka panjang/nice-to-have).
- **Dampak** dinilai dari sudut pemain.
- **Effort:** **S** ≤ ½ hari, **M** ≈ 1–2 hari, **L** > 2 hari.
- **Status:** **[TVER]** = defisit/keadaan terverifikasi (penulis baca kode) · **[SITASI]** = bukti eksekusi agen lain · **[ASM]** = asumsi/desain.

| Prio | Item | Dampak bagi pemain | Effort | Dependency | Status |
|---|---|---|---|---|---|
| **P0** | Fallback bila `getBestMove()` `null` — jangan biarkan giliran menggantung (`script.js:756`) | **Kritis**: permainan berhenti diam-diam tanpa penjelasan | **S** | penjadwal tunggal sudah ada (V6–V11); tempatkan di `executeAIMove` | **[TVER]** + **[SITASI]** (V12, p3 bagian 3a) |
| **P1** | ~~Selesaikan pemasangan turn-queue~~ → **SUDAH SELESAI**; sisa: rapikan (lihat §4 P1) | Tinggi (sudah tercapai) | **S** | — | **[TVER]** (V6–V11) + **[SITASI]** 56/56 |
| **P3** | Aksesibilitas: hapus `user-scalable=no`, sapu `aria-label`, `:focus-visible` | **Tinggi**: membuka produk untuk pembaca layar & pengguna zoom | **M** | tidak ada | **[TVER]** defisit (V1–V5); perbaikan **[ASM]** (A1–A3) |
| **P6** | Hapus skema `Box` ganda (`edges` *dead write*) | Rendah langsung, **tinggi** untuk pemeliharaan: satu definisi Box | **S** | sebaiknya sebelum P2-sisa | **[TVER]** (V15) |
| **P2** | (Sisa) test migrasi save lama ber-`edges` + pisahkan pesan galat versi | Sedang: melindungi pemain dari save rusak saat bentuk data berubah | **S** | `version` sudah ada (V13–V14); butuh keputusan bentuk Box (P6) | **[TVER]** implementasi; migrasi **[ASM]** (A7) |
| **P5** | Ketajaman HiDPI: DPR scale + guard hit-test — **satu PR** | **Sedang**: kanvas tajam di Retina; cegah bug hit-test masa depan | **M** | tidak ada | **[TVER]** defisit render (V18–V19); hit-test **[ASM]** (A5) |
| **P4** | Telemetri ringan: panel dev-overlay + hemat tulis save (`:585`) & rapatkan audio (`:74–101`) | Rendah–sedang: hemat I/O, alat diagnosa untuk QA | **M** | P5 (overlay menampilkan DPR) | **[TVER]** V16–V17; overlay **[ASM]** |
| **P7** | Kesiapan E2E di peramban + PWA (manifest, service worker) | Sedang: bisa dipasang seperti aplikasi, offline, rilis lebih aman | **L** | perlu keputusan CEO | **[ASM]** (A8, A9) |

**Urutan disarankan:** **P0 → P3 → P6 → P2 → P5 → P4 → P7.**
Alasan: P0 menghilangkan risiko pemain yang paling terlihat; P3 membuka produk untuk pengguna yang saat ini tertutup; P6 membuka jalan P2 tanpa mengubah bentuk data dua kali; sisanya investasi jangka panjang.

---

## 4. Tiap usulan: masalah → bukti baris → perubahan → test → risiko

### P0 (KRITIS) — Giliran AI menggantung bila `getBestMove()` `null`

- **Masalah.** Saat AI tidak menemukan langkah, fungsi keluar begitu saja. Pemain melihat papan diam, tanpa pesan, tanpa giliran berpindah — dari sudut pemain, aplikasi terasa rusak.
- **Bukti baris.** `script.js:756` `if (!move) return;` di dalam `executeAIMove` (dulu `:746`). Dibuktikan **dinamis** oleh p3 bagian 3a: `makeMove` dipanggil **0×**, `switchTurn` **tidak**, `endGame` **tidak**, `showToast` **tidak** ([SITASI] `docs/bukti/output-bukti-eksekusi.txt`). Kontra-bukti 3b: pada `move` valid, `makeMove` dipanggil **1×** dengan `["horizontal",0,0]` → penyebabnya memang `null`.
- **Perubahan yang diusulkan.** Ganti `return` telanjang dengan: (1) ambil langkah cadangan dari `Rules.availableMoves` (pilih acak ber-seed); (2) bila benar-benar kosong → `endGame()`; (3) beri tahu pemain via `showToast`. Tetap di dalam `executeAIMove`, memakai penjadwal tunggal yang sudah ada (`turnQueue`), **bukan** `setTimeout` baru.
- **Test yang membuktikan.** Dua test di `test/` (pola sandbox `vm` mengikuti `test/qa-regressions.test.js`): "`getBestMove` `null` → `makeMove` tetap dipanggil dengan langkah legal" dan "langkah legal kosong → `endGame` + `showToast` dipanggil". Harus **gagal** sebelum perubahan (RED) dan hijau setelahnya.
- **Risiko.** Fallback acak bisa memilih langkah sah tapi buruk; mitigasi: hanya dipakai saat AI gagal total, dan selalu lewat `Rules.availableMoves` agar aturan tidak diduplikasi.

### P1 (SELESAI — untuk catatan & sisa pembersihan)

- **Masalah (dulu).** Penjadwalan giliran AI tersebar di tiga tempat, masing-masing memasang timer sendiri, dan `makeAIMove` memasang timer kedua di dalamnya → timer bisa menumpuk (AI "bergerak dua kali") atau basi (timer lama menyala setelah papan direset).
- **Bukti baris (keadaan sekarang).** `script.js:45–53` impor & `createTurnQueue()`; empat jalur memakai `turnQueue.schedule(...)` (`:191`, `:604`, `:641`, `:933`); satu penundaan eksekusi (`:734`); `aiMoveTimeout` **0 hasil** (terhapus); `resetBoardOnly` (`:1064`) & `loadGame` (`:885`) memanggil `turnQueue.clear()`; `index.html:118` memuat `turn-queue.js` sebelum `script.js:120` [semua TERVERIFIKASI]. Modul: `turn-queue.js:32–90`, `:93–103` (single-slot, dependensi penjadwal disuntikkan).
- **Bukti eksekusi.** `test/p1-wiring.test.js` (4 test A–D) menuntut pemasangan; **RED terarsip** (4 fail, `docs/bukti/p1-terpasang.txt:20–30`) dan **GREEN terarsip** (56/56, `docs/bukti/p1-terpasang.txt:150–158`, `exit=0`) [SITASI].
- **Sisa pekerjaan (opsional, effort S).** (a) `index.html:118` menempatkan `turn-queue.js` **sesudah** `rules.js` tetapi **sebelum** `ai-engine.js`; pastikan ini disengaja dan didokumentasikan (test ke-52 hanya mengunci `rules.js` lebih dulu). (b) Perbarui komentar `turn-queue.js:20` yang masih menyebut `script.js:723` (nomor lama) → rujuk `:734`.
- **Test yang membuktikan.** Sudah ada: `node --test test/p1-wiring.test.js` (4/4) dan `node --test` (56/56).
- **Risiko.** Tidak ada risiko pemain yang terbuka; yang tersisa hanya risiko **dokumentasi** (nomor baris usang di komentar bisa menyesatkan pembaca berikutnya).

### P3 — Aksesibilitas: zoom, nama tombol, fokus terlihat

- **Masalah.** Pengguna pembaca layar tidak tahu fungsi tombol beremoji, dan pengguna low-vision tidak bisa memperbesar tampilan. Produk saat ini praktis tertutup bagi mereka.
- **Bukti baris.** `index.html:5` (`user-scalable=no`, `maximum-scale=1.0`); `index.html:15` (hanya `title`); `index.html:94–97` (`▶️ ⏮️ ⏭️ ❌`); `index.html:108` (`playAgainBtn`); dan `aria-label` di `index.html` = **0** [TERVERIFIKASI, dicek ulang]. QA mengonfirmasi `grep -rn "aria-label"` **seluruh repo = 0 hasil** → defisit sistemik, bukan lima tombol.
- **Perubahan yang diusulkan.**
  - (a) `index.html:5` → `<meta name="viewport" content="width=device-width, initial-scale=1.0">` (hapus `maximum-scale=1.0` & `user-scalable=no`; WCAG 2.2 SC 1.4.4/1.4.10).
  - (b) Sapu `aria-label` seluruh repo: `#darkModeToggle` → "Ganti mode gelap"; `#replayPlayPause` → "Putar atau jeda replay"; `#replayPrev` → "Langkah replay ke belakang"; `#replayNext` → "Langkah replay ke depan"; `#replayClose` → "Tutup replay"; `#playAgainBtn` → "Main lagi".
  - (c) Tambah `:focus-visible` yang terlihat untuk semua kontrol.
  - (d) Lanjutan (asumsi): live region `#liveStatus` (`role="status"`, `aria-live="polite"`) berisi **teks**, bukan emoji, mis. "Giliran biru. Skor 3–2."; dan hormati `prefers-reduced-motion` untuk animasi replay.
  - Rancangan penuh: `docs/superpowers/specs/2026-10-10-p2-aksesibilitas-dan-telemetri-design.md`.
- **Test yang membuktikan.** Test statis `node --test` yang membaca `index.html`: assert tidak ada `user-scalable=no`, dan setiap `.icon-btn`/`.btn-replay` punya `aria-label` tak kosong. Sinyal keluaran: jumlah `aria-label` di `index.html` **> 0**. Ditambah walkthrough pembaca layar oleh QA (belum ada, [ASM] A2).
- **Risiko.** (1) `title` **bukan** pengganti `aria-label`. (2) Menghapus pembatas zoom dapat mengubah tata letak layar sempit → perlu pemeriksaan visual. (3) Jangan memberi `aria-label` pada tombol yang sudah punya teks visibel (mis. `.btn-control`) — berisiko melanggar WCAG 2.5.3 "Label in Name".

### P6 — Hapus skema `Box` ganda (`edges` *dead write*)

- **Masalah.** Ada dua definisi "Box": satu menghasilkan `{ owner }`, satu lagi menulis `{ owner, edges }`. Field `edges` **tidak pernah dibaca**, jadi ia menipu pembaca kode menjadi percaya kotak menyimpan sisi-sisinya.
- **Bukti baris.** `rules.js:42` → `{ owner: null }`; `script.js:152–157` → `{ owner: null, edges: { top: null, bottom: null, left: null, right: null } }` (dulu `:142`). p3 membuktikan **0 pembaca** `box.edges` → *dead write* ([SITASI] `docs/bukti/output-bukti-eksekusi.txt` bagian 2b).
- **Perubahan yang diusulkan.** Buang `edges` dari inisialisasi Box di `script.js:152–157` (dan setiap penulisan ulang Box lain bila ada) sehingga Box hanya `{ owner }`, sejalan dengan `Rules.createBoard`. Save lama ber-`edges` **tetap diterima** tetapi tidak disimpan kembali.
- **Test yang membuktikan.** Test yang memverifikasi `gameState.boxes` hasil inisialisasi **tidak** punya `edges`, dan test migrasi: save lama ber-`edges` tetap dimuat dan papan akhirnya identik.
- **Risiko.** Save lama (sudah terlanjur ber-`edges`) harus tetap bisa dimuat — karena itu urutannya **P6 sebelum P2-sisa**.

### P2 — (Sisa) migrasi & pengujian versi skema save

- **Masalah.** Bentuk data bisa berubah (P6 akan mengubahnya); tanpa penjagaan versi, save lama bisa dimuat dengan asumsi bentuk baru.
- **Bukti baris (sudah terpasang).** `script.js:768` `const SCHEMA_VERSION = 1;`; `:769–772` `versiDikenal()` (save tanpa `version` → true/warisan; selain itu harus `Number.isInteger` dan `=== SCHEMA_VERSION`); `:776` `version: SCHEMA_VERSION` ditulis `saveGame`; `:808` `buatKandidatState` memanggil `versiDikenal(saveData.version)` → `return null` bila tak dikenal [TERVERIFIKASI]. Test save-schema (5 test) **hijau** ([SITASI] `docs/bukti/p1-terpasang.txt:110–119`, test ke-37..41).
- **Perubahan yang diusulkan (sisa).** (a) Tambah **test migrasi** untuk save lama ber-`edges` (lihat P6) supaya A7 terbukti. (b) Pisahkan pesan galat "versi tak dikenal" dari "struktur tak valid": hari ini sumber `null`-nya ada di dua tempat (`script.js:808` untuk versi, `:810–812` untuk kunci wajib) tetapi `console.error` hanya mencetak satu pesan gabungan di `script.js:900` (`'Save ditolak: struktur data tidak valid'`), sehingga kedua kasus tak bisa didiagnosis terpisah (koreksi QA: dulu ditulis ":900 area").
- **Test yang membuktikan.** Yang sudah ada: `node --test test/save-schema.test.js` (5/5 hijau — termasuk "save tanpa version (warisan) diterima", "version tak dikenal ditolak", "version bukan integer ditolak"). Yang **belum**: **test migrasi save lama ber-`edges`**.
- **Risiko.** Menolak versi tak dikenal bisa menutup pintu ke save masa depan; mitigasi: pesan galat yang membedakan kedua kasus.

### P5 — Ketajaman HiDPI (DPR scale + guard hit-test) — **satu item, satu PR**

- **Masalah.** Di layar HiDPI, kanvas tidak pernah di-render lebih tajam dari 1× karena `canvas.width` ditulis sebagai CSS px langsung → tampak kabur.
- **Bukti baris.** `script.js:206–207` (`canvas.width = size`), `:224–225` (idem pada resize) — tulis CSS px ke atribut bitmap, **tanpa** `ctx.scale`/`setTransform`; hit-test `:446–448`, `:460–463` (CSS px); `hitRadius = 30` di `:470` [TERVERIFIKASI, dulu `:196-197/:214-215/:436-438/:450-453/:460`]. `grep dpr` = 0 hasil (konfirmasi researcher/developer).
- **Perubahan yang diusulkan.** `canvas.width = size*dpr`; `canvas.style.width = size + 'px'`; `ctx.setTransform(dpr,0,0,dpr,0,0)` **sebelum** `calculatePositions()`; plus konversi balik koordinat pointer bila diperlukan.
- **Status yang benar — jangan ditulis sebagai bug hit-test aktif.** `hitRadius = 30` (`:470`) **saat ini tidak meleset** (rasio bitmap:CSS = 1:1). Tapi ini **rapuh**: begitu bitmap di-×DPR setengah jalan (tanpa scale balik), hit-test langsung rusak. Karena itu guard-nya masuk **satu PR** dengan perbaikan DPR — bukan item terpisah, bukan klaim cacat aktif.
- **Test yang membuktikan.** Test dengan `devicePixelRatio` tiruan (mis. 2): ukuran bitmap = CSS × DPR, `getTransform()` menunjukkan skala DPR, dan pemetaan koordinat pointer tetap menghasilkan indeks garis yang sama. Uji layar Retina asli belum ada ([ASM] A5).
- **Risiko.** Bila hanya satu bagian dikerjakan (bitmap di-×DPR tanpa scale balik), hit-test **langsung rusak** — justru memperburuk. Karena itu **wajib satu PR**.

### P4 — Telemetri ringan: panel dev-overlay + hemat I/O

- **Masalah.** (a) Saat bug terjadi di peramban, tim tidak punya satu tempat melihat FPS, `devicePixelRatio`, ukuran kanvas, giliran, dan galat terakhir. (b) `saveGame()` dipanggil di tengah `makeMove` → tiap langkah menulis `localStorage` (I/O sinkron, bisa memicu jank di seluler). (c) Audio membuat oscillator baru tiap efek.
- **Bukti baris.** `script.js:585` (`saveGame()` di jalur `makeMove`, dulu `:575`); `script.js:74–101` (AudioContext lazy + `resume`; tiap `playSound` `createOscillator`).
- **Perubahan yang diusulkan.** (a) Overlay status hanya-baca, aktif lewat `?dev=1`, tidak tampil di mode normal. (b) Batasi tulis save: tulis di akhir giliran (mis. di `updateUI`) alih-alih di tengah `makeMove`, atau *coalesce* dengan `requestIdleCallback`. (c) Rapatkan audio: pakai ulang satu `AudioContext` (sudah ada) dan batasi jumlah oscillator aktif.
- **Test yang membuktikan.** Untuk (b): test yang menghitung pemanggilan `localStorage.setItem` per langkah **dan** memastikan save akhir selalu merefleksikan state akhir. Untuk (a): test yang memastikan overlay tidak aktif saat `?dev=1` tidak ada.
- **Risiko.** Menunda tulis save bisa kehilangan data bila tab ditutup mendadak; mitigasi: selalu tulis saat giliran berakhir + `beforeunload`. Overlay berisiko bocor ke produksi bila salah gate.

### P7 — Kesiapan E2E di peramban + PWA

- **Masalah.** Tidak ada tes yang menjalankan aplikasi di peramban sungguhan, dan aplikasi tidak bisa dipasang/di-offline-kan. Seluruh suite kini `node --test` + sandbox `vm`, sehingga input pointer/touch nyata **tidak tercakup**.
- **Bukti baris.** Tidak ada berkas manifest/service worker di repo; `index.html:117–120` adalah satu-satunya jalur muat. Ini **usulan**, bukan temuan cacat ([ASM] A8, A9).
- **Perubahan yang diusulkan.** (a) Harness E2E peramban (mis. Playwright): muat `index.html`, mainkan satu permainan kecil, pastikan tidak ada galat konsol — sekaligus menutup satu-satunya sisa risiko pemain P0/P1. (b) PWA minimal: `manifest.webmanifest`, ikon, service worker *cache-first* untuk aset lokal.
- **Test yang membuktikan.** Skrip E2E hijau di CI + pemeriksaan Lighthouse manual. Belum ada satu pun sekarang.
- **Risiko.** Menambah toolchain peramban memperbesar waktu CI & dependensi; proyek ini sengaja tanpa *build step* → PWA harus dibuat tanpa bundler.

---

## 5. Keputusan yang sudah diambil + yang masih terbuka

### 5.1 Keputusan yang sudah diambil (Ruling 1–4)

**Ruling 1 (bentuk Box → P6).** Bentuk kanonik `Box` adalah `{ owner }` (mengikuti `rules.js:42`). `edges` di `script.js:152–157` akan dibuang. Save lama ber-`edges` tetap dimuat.

**Ruling 2 (P5 tidak dipecah).** P5 tetap **satu item**: "Perbaikan Ketajaman HiDPI (DPR scale + guard hit-test)", **tanpa** klaim bug hit-test aktif. Memecahnya menjadi P5a/P5b akan menciptakan kesan dua cacat padahal hit-test saat ini benar. Satu PR, satu gerbang test.

**Ruling 3 (P2 diselesaikan setelah P6).** Sisa pekerjaan P2 (test migrasi + pemisahan pesan galat) dikerjakan **setelah** P6 agar tidak ada dua perubahan bentuk data dalam satu langkah. P2 menerima save lama sebagai v1 — implementasi `versiDikenal` (`script.js:769–772`) sudah sesuai.

**Ruling 4 (bahasa & bukti).** Dokumen, komentar kode, dan pesan laporan dalam **Bahasa Indonesia**; hanya nama teknis (fungsi/file/perintah) tetap bahasa Inggris. Setiap klaim "terverifikasi" wajib menyertakan `berkas:baris` atau keluaran perintah mentah. Mengikuti ADR-0002 dan koreksi lintas-paket.

**Ruling 5 (BARU — P1 & P2 dinyatakan terpasang, draf lama dikoreksi).** Berdasarkan verifikasi baris langsung (V6–V14) dan bukti suite terbaru ([SITASI] `docs/bukti/p1-terpasang.txt:150–158`, 56/56 `exit=0`), P1 (wiring `turn-queue`) dan P2 (versi skema save) **dinyatakan sudah terpasang di `script.js`/`index.html`**, dan **seluruh klaim draf lama yang menyatakan keduanya "belum terpasang" adalah SALAH** dan tidak boleh dikutip lagi. Prioritas kritis berpindah ke **P0 (fallback AI)**.

### 5.2 Masih terbuka — perlu keputusan CEO

1. **Cakupan rilis.** Rilis berikutnya fokus **perbaikan pemain** (P0+P3, cepat) atau **kesiapan produk** (P7 PWA/E2E, lebih lama)?
   - Opsi: (a) Perbaikan pemain dulu (P0→P3→P6→P2) — cepat terasa; (b) Kesiapan produk dulu (P7 + P3); (c) Bertahap: P0 sebagai hotfix tunggal dulu, lalu sisanya.
2. **Prioritas aksesibilitas.** Jadikan WCAG AA target formal ("tanpa pelanggaran AA pada rilis berikutnya"), atau cukup perbaikan terarah (zoom + label tombol)?
3. **PWA: sekarang atau nanti.** Service worker berarti memperkenalkan strategi cache yang harus dirawat. Sekarang, atau tunggu ada pengguna nyata?
4. **Anggaran toolchain.** Boleh menambah dependensi uji (Playwright) padahal proyek kini nol dependensi?

---

## 6. Yang masih kurang / terhambat

- **Akses shell.** Paket p4 (penulis) tidak dapat menjalankan perintah. Semua angka eksekusi di §7 adalah **[SITASI]** dari berkas bukti `developer`/`qa`, bukan hasil penulis.
- **P0 belum dikerjakan (risiko pemain utama).** `script.js:756` masih `if (!move) return;` → giliran bisa menggantung tanpa pesan [TERVERIFIKASI].
- **Belum ada test migrasi save lama ber-`edges`.** Implementasi versi ada & hijau, tetapi A7 belum terbukti.
- **Test E2E peramban belum ada satu pun** → jalur input pointer/touch nyata dan perilaku timer di peramban sungguhan belum tercakup CI mana pun ([ASM] A9).
- **Uji perangkat HiDPI nyata** dan **walkthrough pembaca layar** belum ada.
- **Nomor baris di draf lama & komentar `turn-queue.js:20` usang.** Perlu pembaruan agar pembaca berikutnya tidak tersesat (bagian dari sisa P1).

---

## 7. Lampiran perintah & output nyata

> **Semua blok di §7 adalah [SITASI] dari berkas bukti agen lain.** Penulis **tidak** menjalankan perintah. Sumber tiap blok disebutkan.

### 7.1 Suite penuh terkini — **56/56 lulus, `exit=0`** ([SITASI] `docs/bukti/p1-terpasang.txt:150–158`)

```
$ node --test        # worktree 20261010-214601 (setelah P1 terpasang)
1..56
# tests 56
# suites 0
# pass 56
# fail 0
# cancelled 0
# skipped 0
# todo 0
# exit=0
```

Di dalamnya: test ke-13..16 = wiring P1 (A–D) **ok**; test ke-37..41 = save-schema (P2) **ok**; test ke-53..56 = perilaku `turn-queue` **ok**.

### 7.2 Bukti P1 terpasang ([SITASI] `docs/bukti/p1-terpasang.txt:7–18`)

```
$ grep -n "turnQueue.schedule(makeAIMove" script.js
191:   if (shouldScheduleAI(gameState)) turnQueue.schedule(makeAIMove, 500);
604:   if (shouldScheduleAI(gameState)) turnQueue.schedule(makeAIMove, 400);
641:   if (shouldScheduleAI(gameState)) turnQueue.schedule(makeAIMove, 400);
933:   if (shouldScheduleAI(gameState)) turnQueue.schedule(makeAIMove, 400);
$ grep -n "aiMoveTimeout" script.js          # 0 hasil = dihapus
$ grep -n "makeAIMove()" script.js | grep setTimeout   # 0 hasil
$ grep -n "turn-queue" index.html
118:   <script src="turn-queue.js"></script>
```

Penulis **memverifikasi ulang** baris-baris ini langsung di workspace (`script.js:191/:604/:641/:933/:734`, `index.html:118`) — semuanya cocok.

### 7.3 Bukti RED lalu GREEN untuk wiring P1 ([SITASI] `docs/bukti/p1-terpasang.txt:20–30`)

```
$ node --test test/p1-wiring.test.js     # dengan script.js+index.html LAMA (pra-P1)
not ok 1 - A: giliran AI dijadwalkan lewat turnQueue produksi, bukan setTimeout lepas
not ok 2 - B: script.js tidak lagi memakai setTimeout(() => makeAIMove) atau aiMoveTimeout
not ok 3 - C: index.html memuat turn-queue.js sebelum script.js
not ok 4 - D: resetBoardOnly() membatalkan giliran AI tertunda
# tests 4
# pass 0
# fail 4
```

### 7.4 Bukti eksekusi temuan — 7/7 bukti kuat ([SITASI] `docs/bukti/output-bukti-eksekusi.txt`)

```
$ node scripts/bukti-eksekusi.js --strict        # exit=0
BAGIAN 2 — Bentuk Box
[BUKTI-KUAT] 2a. Rules.createBoard(3) -> {"owner":null}
[BUKTI-KUAT] 2b. script.js -> {"owner":null,"edges":{...}} ; pembaca Box.edges: 0 -> dead write
BAGIAN 3 — getBestMove null => giliran menggantung
[BUKTI-KUAT] 3a. makeMove dipanggil 0x, switchTurn tidak, endGame tidak, showToast tidak
[BUKTI-KUAT] 3b. Kontra-bukti: move valid -> makeMove dipanggil 1x ["horizontal",0,0]
RINGKASAN: Total bagian 7 | bukti kuat 7 | gagal 0
```

> **Catatan pembeda waktu.** `docs/bukti/output-bukti-eksekusi.txt` merekam keadaan **pra-P1**. Test 6/7/8 di `docs/bukti/node-test-p1-terpasang.txt` masih **gagal** karena mengassert kode lama; setelah P1 terpasang, `test/bukti-eksekusi.test.js` diperbarui dan suite menjadi 56/56. Jadi angka 7/7 p3 tetap bukti sah untuk **temuan**, bukan untuk keadaan kode sekarang.

### 7.5 Perintah yang **harus dijalankan** penanggung jawab berikutnya

```
# Keadaan sekarang (harus HIJAU, exit=0 — sumber docs/bukti/p1-terpasang.txt):
node --test

# Wiring P1 (harus 4/4 HIJAU):
node --test test/p1-wiring.test.js

# Skema save P2 (harus 5/5 HIJAU):
node --test test/save-schema.test.js

# Modul turn-queue (harus 4/4 HIJAU):
node --test test/turn-queue.test.js
```

**Ekspektasi jujur.** Keempat perintah di atas **sudah dijalankan** dan **hijau** menurut berkas bukti ([SITASI] `docs/bukti/p1-terpasang.txt`, `docs/bukti/node-test-qa-polos.txt`). Yang **belum ada** dan wajib ditambahkan: **test P0** (fallback ketika `getBestMove` `null`) dan **test migrasi save lama ber-`edges`** (P6/P2). Keduanya harus ditulis **gagal dulu (RED)**, lalu dibuat hijau.

### 7.6 Berkas spesifikasi, bukti, dan modul terkait

- `docs/superpowers/specs/2026-10-10-p1-turn-queue-dan-skema-save-design.md` — rancangan P1/P2.
- `docs/superpowers/specs/2026-10-10-p2-aksesibilitas-dan-telemetri-design.md` — rancangan P3/P4.
- `turn-queue.js` — modul P1 (**ada & terpasang**).
- `test/p1-wiring.test.js` (4 test, menuntut wiring), `test/turn-queue.test.js` (4 test), `test/save-schema.test.js` (5 test) — semua **hijau** per §7.1.
- `docs/bukti/p1-terpasang.txt` — **bukti terkini** (56/56 `exit=0`) + RED wiring.
- `docs/bukti/node-test-qa-polos.txt` — **verifikasi silang QA** (56/56 `exit=0`, commit `da43ef4`, blok di `:285–294`) → angka yang sah untuk dikutip.
- `docs/bukti/node-test-polos-qa.txt` — **historis, USANG**: 52/52 `exit=0` (`:266–275`, commit `3d2eebc`, pra-P1/P2). Berkas ini **ada**; jangan dikutip sebagai keadaan terkini (rujuk koreksi §2.3).
- `docs/bukti/node-test-p1-terpasang.txt` — hasil **antara** (**56 tes: 42 lulus / 14 gagal**, `require is not defined`) → **jangan dikutip sebagai keadaan akhir**.
- `docs/bukti/output-node-test.txt` (43/43 subset baseline), `docs/bukti/output-bukti-eksekusi.txt` (7/7), `docs/bukti/grep-p1-belum-terpasang.txt` — bukti historis.
- `docs/adr/0001-seam-aturan-murni.md`, `docs/adr/0002-jangan-janjikan-minimax.md` — keputusan arsitektur.

### 7.7 Bukti verifikasi silang QA — 56/56 `exit=0`, P0 & P3 masih terbuka ([SITASI] `docs/bukti/node-test-qa-polos.txt:285–294`, commit `da43ef4`)

```
$ node --test        # worktree 20261010-214601 (setelah P1 & P2 terpasang)
1..56
# tests 56
# suites 0
# pass 56
# fail 0
# cancelled 0
# skipped 0
# todo 0
exit=0
```

QA juga mengonfirmasi dua keadaan kode yang menjadi dasar P0 dan P3 masih **terbuka** (bukan asumsi):

| Bukti | Lokasi | Isi saat ini |
|---|---|---|
| P0 | `script.js:756` | `if (!move) return;` (baris 754=`getBestMove`; 756 tanpa fallback) |
| P3 | `index.html:5` | `content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no"` |

> **Catatan kejujuran.** Penulis (p4) **tidak** menjalankan `node --test`; blok di atas adalah **[SITASI]** dari berkas bukti QA. Yang penulis lakukan sendiri adalah **membaca ulang baris-baris kode** (§2.1 V1–V22) dan **memeriksa isi berkas bukti** untuk memastikan angka yang dikutip cocok dengan nama berkasnya (koreksi 52/52 → 56/56 di §2.3 lahir dari pemeriksaan ini).

### 7.8 Rujukan praktik aksesibilitas & DPR (dipakai paket p2; tanggal akses: 2026-10-10)

- MDN Web Docs. *Window: devicePixelRatio property.* https://developer.mozilla.org/en-US/docs/Web/API/Window/devicePixelRatio
- MDN Web Docs. *prefers-reduced-motion.* https://developer.mozilla.org/en-US/docs/Web/CSS/@media/prefers-reduced-motion
- MDN Web Docs. *Canvas API tutorial: Optimizing canvas.* https://developer.mozilla.org/en-US/docs/Web/API/Canvas_API/Tutorial/Optimizing_canvas
- W3C. *WCAG 2.2 Quick Reference* (SC 1.4.4, 1.4.10, 2.2.2, 2.3.3, 2.5.3). https://www.w3.org/WAI/WCAG22/quickref/
- W3C. *WAI-ARIA Authoring Practices: Alert and status patterns.* https://www.w3.org/WAI/ARIA/apg/patterns/alert/
- W3C. *WAI-ARIA Authoring Practices: Accessible names and descriptions.* https://www.w3.org/WAI/ARIA/apg/practices/names-and-descriptions/
- WebAIM. *Accessibility of canvas.* https://webaim.org/articles/accessibility-of-canvas/

---

## Skills applied:
- brainstorming: Menyatakan ulang pemahaman (tujuan CEO = proposal pengembangan yang jujur) dan menyajikan kembali klasifikasi bukti — memisahkan tegas **[TERVERIFIKASI]** (V1–V22, tiap baris dibaca ulang di workspace), **[SITASI]** (keluaran agen lain, sumber disebut), dan **[ASUMSI]** (A1–A9), lalu menaruh empat keputusan yang hanya boleh dijawab CEO di §5.2 alih-alih memutuskan sendiri.
- writing-plans: Menyusun roadmap P0–P3 dengan kolom dampak bagi pemain / effort S-M-L / dependency / status verifikasi, dan tiap usulan sebagai urutan masalah → bukti baris → perubahan → test yang membuktikan → risiko, sehingga penanggung jawab berikutnya punya langkah yang dapat diperiksa tanpa menebak (termasuk perintah persis di §7.5).
- domain-modeling: Memperbaiki model domain yang bertabrakan — istilah **Box** punya dua definisi (`rules.js:42` vs `script.js:152–157`) dan saya tetapkan bentuk kanonik `{ owner }` (Ruling 1); istilah "giliran menggantung", "penjadwal tunggal (turn queue)", dan "versi skema" dipakai konsisten dengan GLOSSARY dan ADR-0002, plus memperkenalkan pembeda **[SITASI]** agar "bukti" tidak tercampur dengan "hasil orang lain yang dikutip".
- codebase-design: Menilai `turn-queue.js` sebagai modul dalam — antarmuka kecil (`createTurnQueue(deps?)`, `shouldScheduleAI(state)`) menyembunyikan perilaku single-slot penting, dengan dependensi penjadwal **disuntikkan** ("accept dependencies, don't create them") dan satu **seam** yang dipakai pemanggil (`script.js`) maupun test; saya juga mencatat `script.js:756` sebagai titik keputusan (`if (!move) return;`) yang belum punya jalur keluar dan bahwa `test/p1-wiring.test.js` adalah bentuk "menguji lewat interface" yang membuat "hijau" bermakna.
- grilling: Menekan titik yang paling mungkin membuat dokumen ini menyesatkan — (1) menemukan dan mengoreksi klaim **SALAH** draf lama bahwa "P1 wiring belum terpasang" (padahal `script.js:45–53/:191/:604/:641/:933/:734` dan `index.html:118` sudah memakainya), (2) memutakhirkan angka suite menjadi **56/56 `exit=0`** setelah memverifikasi `docs/bukti/node-test-qa-polos.txt:285–294` berakhir `# pass 56 / # fail 0 / exit=0`, (3) **mencabut klaim revisi-2 yang juga keliru** — "berkas 52/52 tidak pernah ada" — setelah membaca sendiri `docs/bukti/node-test-polos-qa.txt:266–275` (`# tests 52 / # pass 52 / # exit=0`, commit `3d2eebc`): berkasnya **ada**, yang salah adalah *mengutipnya sebagai keadaan terkini*; jadi statusnya **usang**, bukan **fiktif**, dan koreksi ke arah sebaliknya pun saya tolak, (4) membedakan **empat** berkas bukti (`p1-terpasang.txt` 56/0, `node-test-qa-polos.txt` 56/0, `node-test-polos-qa.txt` **52/0 (usang)**, `node-test-p1-terpasang.txt` **56 tes: 42/14**) agar tidak tertukar, (5) memperbaiki seluruh nomor baris yang bergeser (`:746`→`:756`, `:575`→`:585`, `:460`→`:470`, `:142`→`:152–157`) dan menajamkan sitasi `:808`/`:810–812`/`:900`, dan (6) tetap menolak menyimpulkan lebih dari yang dibuktikan (aksesibilitas sebagai perilaku, HiDPI, E2E tetap [ASM]/belum) — sekaligus menaikkan status **keberadaan** P0 (`script.js:756`) dan P3 (`index.html:5`) menjadi terverifikasi setelah QA mengonfirmasinya lewat eksekusi, tanpa mengklaim perbaikannya sudah ada.

**Verifikasi penulis (p4) pada revisi ke-3 — apa yang saya lakukan sendiri, apa yang tidak.**
- **Dilakukan sendiri (revisi ke-3):** membaca ulang **langsung** `script.js:750–790` (P0 `:756`; `SCHEMA_VERSION` `:768`; `versiDikenal()` `:769–772`; `version: SCHEMA_VERSION` `:776`), `script.js:795–820` (`:808` cek versi, `:810–812` cek kunci), `script.js:895–905` (`:900` pesan gabungan), dan `index.html:1–122` (`:5` `user-scalable=no`, `:15` tombol mode gelap, `:94–97` blok replay, `:108` `playAgainBtn`, `:117–120` urutan `<script>`); `search_files "aria-label"` pada `index.html` → **0 hasil**. Membaca **isi mentah** berkas bukti dan membandingkannya dengan nama berkasnya: `node-test-qa-polos.txt:285–294` = 56/56; `p1-terpasang.txt:150–158` = 56/56; `node-test-polos-qa.txt:266–275` = **52/52 (ADA, pra-P1)**; `node-test-p1-terpasang.txt:1` = commit `3d2eebc`.
- **Dari sini lahir:** penghapusan angka 52/52 sebagai "angka benar untuk dikutip" (diganti status **usang**), pencabutan separuh klaim revisi-2 "berkas tidak pernah ada", koreksi berkas di §7.5, dan penajaman sitasi `:808`/`:810–812`/`:900` di §4 P2(b).
- **Tidak dilakukan:** menjalankan `node --test`, `grep`, atau peramban. Langkah ini tidak punya akses shell. Karena itu seluruh angka eksekusi tetap **[SITASI]**, dan warna hijau/merah suite final wajib dikonfirmasi QA/dev yang menjalankannya.
- **Yang wajib ada tetapi belum ada:** test P0 (fallback saat `getBestMove` `null`) dan test migrasi save lama ber-`edges` (P6/P2). Keduanya harus RED dulu, lalu GREEN.

ASK: qa
QUESTION: Dua hal kecil untuk ditutup QA, mohon dikonfirmasi lewat pembacaan berkas (bukan opini): (1) Saya menemukan `docs/bukti/node-test-polos-qa.txt` **ADA** dengan isi 52/52 `exit=0` di `:266–275` (commit `3d2eebc`, pra-P1/P2) — sedangkan catatan Anda di `docs/bukti/VERIFIKASI-QA-REVISI-2.md:59` menyebut berkas itu "tidak pernah ada". Betulkah berkas itu ada, dan maukah Anda mencabut baris `:59` di laporan Anda? (2) Saya sudah memperbaiki §4 P2(b) menjadi angka pasti — sumber `null` di `script.js:808` (versi) dan `:810–812` (kunci wajib), pesan gabungan di `:900`; apakah perbaikan itu sudah sesuai dan tidak ada lagi sitasi yang perlu ditambal?
OPTIONS: a) Proposal sudah akurat, lanjut ke CEO | b) Ada sitasi/angka salah lagi — sebutkan berkas:baris agar saya perbaiki | c) Perlu test P0/migrasi ditulis dulu sebelum proposal final
