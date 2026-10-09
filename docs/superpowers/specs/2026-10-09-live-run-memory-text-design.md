# Desain: Teks Live Run Dashboard BABD Lebih Informatif

**Tanggal:** 2026-10-09
**Penulis:** Architect
**Status:** Menunggu review CEO (lewat Team Lead)
**Goal CEO:** "ini contoh text di live run di dashboard babd — QA / Tester · read gbrain · 3 fact(s), 1 page(s) · tambah or kan or agent or baru or bernama or researcher or gunakan or repo — buatkan agar lebih informatif untuk saya sebagai user"

---

## 1. Pemahaman (intended outcome)

CEO melihat baris langkah GBrain di dashboard dan tidak bisa menjawab tiga pertanyaan dasar:
**apa yang sedang dilakukan agen, apa yang dicari, dan apa yang ditemukan.**

**Success criteria:** setiap baris memory (baca/tulis GBrain) menjawab dalam Bahasa Indonesia:

1. **Siapa** — nama agen (sudah ada, tidak berubah).
2. **Sedang apa** — aksi manusiawi ("Membaca memori tim"), bukan `read gbrain`.
3. **Dengan kata kunci apa** — kata kunci asli, dipisah koma (`tambah, agent, researcher, repo`),
   **bukan** string internal `tambah or kan or agent or baru or ...`.
4. **Ketemu apa** — isi temuan (judul fact + slug halaman) di baris kedua & tooltip.
5. **Berapa** — jumlah yang manusiawi ("3 catatan, 1 halaman"), dan pesan jelas bila nol temuan.

---

## 2. Problem statement (temuan kode nyata, sudah saya baca)

| Yang CEO lihat | Sumber nyata di repo | Akar masalah |
|---|---|---|
| `read gbrain · 3 fact(s), 1 page(s)` | `babd/dashboard/static/app.js:558-566` (`memoryItem`) | Label teknis Inggris + `fact(s)`/`page(s)` |
| `tambah or kan or agent or baru or ...` | `m.query` yang di-render di `app.js:560` | String internal dari `babd/gbrain.py:349` (`" or ".join(words)`) bocor mentah ke UI |
| Baris yang sama di **activity feed** | `app.js:1698` (`es.addEventListener("memory")`) | Permasalahan sama, tempat kedua |
| Baris yang sama di **live event log** | `app.js:1718` (event `run`) | Permasalahan sama, tempat ketiga |
| Baris yang sama di **Agent logs** (JSONL) | `babd/agentlog.py:74-78` | Permasalahan sama, tempat keempat (server-side) |

**Temuan kunci (paling penting untuk desain):** data yang dibutuhkan CEO **sudah ada dan lengkap**
tapi **belum dipakai**.

- `babd/team.py:136-138` mengirim event read berisi:
  `{"agent", "op":"read", "query", "facts", "pages", "at", "items":[5 fact] + [5 slug]}`.
- `items` itu = isi temuan (fact + slug halaman). Di `app.js:562` `items` **hanya** dipakai sebagai
  `title` (tooltip), sedangkan `query` mentah ditampilkan sebagai teks terlihat.
- Jadi perbaikan ini **murni presentasi**: tidak ada field baru, tidak ada perubahan backend.

**Risiko bila saya salah menebak:** bila `items` ternyata tidak cukup (mis. CEO ingin durasi per
langkah memory), itu perubahan `flow.py`/`team.py` — **di luar scope desain ini**, dan saya tandai
sebagai open question.

---

## 3. Keputusan desain

### D1 — Perbaikan presentasi saja, tanpa perubahan backend

Tidak menyentuh `gbrain.py` (`recall`/`keywords`): query `or`-joined **memang yang dipakai** gbrain
untuk mencari. Yang salah bukan query-nya, tapi **menampilkan query internal ke CEO**.
Tidak menyentuh `flow.py`. Tidak menyentuh `team.py`.

**Konsekuensi:** tidak ada risiko regresi pada alur run/GBrain.

### D2 — Satu formatter murni sebagai satu-satunya sumber kebenaran teks

Empat tempat render (3 di `app.js`, 1 di `agentlog.py`) memformat teks memory secara terpisah —
itulah sebabnya masalah yang sama muncul 4 kali. Desain ini menaruh **satu seam** dengan niat:
fungsi murni, tanpa DOM, tanpa I/O.

Di `app.js` (di dekat `memoryItem`), tiga fungsi murni:

- `memoryKeywords(query) -> string[]`
  Memecah pada `/\s+or\s+/i`, buang elemen kosong, `trim`, maksimum 6 kata (sisanya → `"…"`).
  - `memoryKeywords("a or b or c")` → `["a","b","c"]`
  - `memoryKeywords("")` → `[]`
  - `memoryKeywords("researcher")` → `["researcher"]`  (**bukan** dipecah)
- `memoryCountLine(facts, pages) -> string` — angka manusiawi, tunggal/jamak benar.
  - `memoryCountLine(3, 1)` → `"3 catatan, 1 halaman"`
  - `memoryCountLine(1, 0)` → `"1 catatan, 0 halaman"`
  - `memoryCountLine(0, 0)` → `""` (baris jumlah disembunyikan; pesan kosong dipakai)
  - Nilai non-angka / `undefined` → diperlakukan `0` (jangan pernah cetak `NaN`)
- `memoryHeadline(m) -> {label, detail, count, keywords, empty}`
  - `m.op === "read"` → `label = "Membaca memori tim"`, `count = memoryCountLine(...)`,
    `keywords = memoryKeywords(m.query)`, `detail = (m.items || [])`.
  - selain itu (`write`) → `label = "Menyimpan ke memori tim"`, `keywords = []`,
    `count = ""`, `detail = m.fact ? [m.fact] : []`.
  - `empty = m.op === "read" && factsNum === 0 && pagesNum === 0`.

Di `babd/agentlog.py:74-78`, teks yang sama dibuat ulang tanpa `or`:

- `read` → `"Baca memori tim: 3 catatan, 1 halaman · kata kunci: tambah, agent, researcher, repo"`
  (bila nol → `"Baca memori tim: tidak ada yang cocok · kata kunci: …"`)
- `write` → `"Simpan ke memori tim: <slug>"`
- `detail` tetap `items` (tidak berubah bentuk).

### D3 — Tampilan dua bagian + tooltip penuh isi

Baris ringkas (selalu) + isi temuan (tooltip selalu, baris `↳` hanya untuk 3 temuan pertama).

```
Sebelum:
  QA / Tester  read gbrain · 3 fact(s), 1 page(s)  tambah or kan or agent or baru or …

Sesudah:
  🟪 QA / Tester  Membaca memori tim · 3 catatan, 1 halaman · kata kunci: tambah, agent, researcher, repo
                  ↳ 3 temuan: "QA (test_plan) for 'tambah kan agent…'", "devops/researcher-runbook", …
```

Aturan konkret:

- Kata kunci ditampilkan dipisah `, ` (naik jadi koma, **bukan** ` or `), maks 6 + `…`.
- Baris kedua `↳ N temuan: …` hanya bila ada `items` dan hanya 3 item pertama;
  `title` (tooltip) tetap memuat **semua** item (5 fact + 5 slug), seperti perilaku lama.
- Op `write` → `💾 Menyimpan ke memori tim · <slug>`.
- Bila `facts = 0` dan `pages = 0` → `🧠 Tidak ada memori terkait — kamu yang pertama`
  (mencerminkan `format_memory` di `gbrain.py:384`).
- **Semua nilai dinamis lewat `esc()`** (helper `esc` sudah ada di `app.js:25`); tidak ada
  `innerHTML` dari data.

### D4 — Helper murni diuji lewat jalur yang nyata berjalan di repo

Repo ini **tidak punya** harness JS (tidak ada `node`/`jsdom`/`package.json`, sudah saya cek).
Menambah toolchain JS = perubahan besar & di luar scope. Karena itu desain ini mengambil pola yang
**sudah dipakai repo**: `app.js` dibaca sebagai **teks** oleh test Python dan helper-nya diekstrak.

Kontrak yang saya tetapkan untuk Developer (agar test benar-benar bisa lulus, bukan NOT RUN):

- `app.js` menaruh helper murni di satu blok yang ditandai komentar:

  ```js
  // ---- memory text helpers (pure; tested by tests/test_memory_text.py) ----
  function memoryKeywords(query) { ... }
  function memoryCountLine(facts, pages) { ... }
  function memoryHeadline(m) { ... }
  // ---- end memory text helpers ----
  ```

- `tests/test_memory_text.py` mengekstrak blok itu dari `app.js`, lalu mengeksekusinya via
  `subprocess` `node --input-type=module -e ...` **hanya bila `node` ada**; bila `node` tidak ada,
  test jatuh ke jalur Python: menyerahkan blok JS + kasus uji ke `python -m json.tool`? **Tidak.**
  Keputusan akhir: test **wajib** dijalankan bila `node` tersedia, dan **skip dengan pesan jelas**
  (bukan PASS diam-diam) bila tidak, memakai `unittest.skipUnless(shutil.which("node"), ...)`.
  Sumber kebenaran untuk perilaku teks **tetap di Python**: `tests/test_memory_text.py` juga
  meng-assert bahwa ketiga titik render memakai `memoryHeadline(` dan tidak lagi memuat literal
  ``` ` fact(s), ` ``` / ``` ` or ` ``` pada cabang `read`.

> **Catatan penting untuk QA (risiko yang saya sadari):** bila `node` tidak ada di mesin QA, test
> JS di-skip dan yang tersisa hanya assertion teks Python. Itu **lebih lemah** dari yang saya mau,
> tapi jujur. QA harus melaporkan secara eksplisit: "node ada/tidak ada" + hasil nyata.

### D5 — Bahasa Indonesia untuk baris memory

Permintaan CEO berbahasa Indonesia. Sisanya dashboard masih Inggris; desain ini **hanya** mengubah
baris memory (read/write GBrain), tidak menerjemahkan seluruh UI (YAGNI). Dikembalikan ke Inggris
bila CEO minta — itu keputusan kecil, bukan arsitektur.

---

## 4. Batas modul (codebase-design)

| Modul | Interface | Implementation | Depth |
|---|---|---|---|
| `memoryHeadline(m)` + 2 helper (`app.js`) | 1 objek hasil + 2 fungsi kecil | semua aturan pemformatan (kata kunci, jamak, kosong, slug, batas 6/3) | **dalam**: 4 call-site + test hanya perlu tahu `{label, count, keywords, detail, empty}` |
| `agentlog.entries_for("memory", …)` | signature lama, hanya string `text` berubah | pemformatan Indonesia + nol-temuan | tetap **dalam**, call site `app.js` tidak berubah |
| `recall()`/`keywords()` (`gbrain.py`) | **tidak berubah** | **tidak berubah** | — |

**Seam:** satu tempat (`memoryHeadline`) untuk semua keputusan teks memory di klien.
**Deletion test:** bila helper dihapus, aturan pemformatan muncul kembali di 3 tempat `app.js`
— itu bukti helper ini earned its keep.

---

## 5. Glossary (tambahan domain-modeling)

Karena "fact(s)"/"page(s)"/"query" adalah istilah yang membingungkan CEO, saya usulkan definisi tegas:

| Istilah | Definisi | Padanan UI (Indonesia) |
|---|---|---|
| **catatan (fact)** | satu kalimat hasil kerja tim yang disimpan di GBrain di bawah sebuah entity | "catatan" |
| **halaman (page)** | dokumen GBrain (mis. `babd/runs/<id>/11-developer-result`) hasil kerja satu task | "halaman" |
| **kata kunci (query)** | kata-kata distinctive dari teks task yang dipakai GBrain untuk mencari; **internal**, digabung `" or "` | "kata kunci" |
| **temuan (item)** | isi yang benar-benar kembali dari pencarian: potongan `fact` atau `slug` halaman | "temuan" |

Saya **tidak** membuat `GLOSSARY.md` terpisah untuk ini: istilahnya lokal pada fitur tampilan
dashboard dan spec ini sudah memuatnya. Bila CEO/QA ingin, mudah diangkat nanti (YAGNI).

---

## 6. Alternatif yang dipertimbangkan (dan kenapa tidak dipilih)

1. **Mengubah `gbrain.py` agar `query` yang dikirim ke event bukan `a or b or c`** (mis. kirim
   `words` sebagai list).
   ➡️ **Ditolak.** Menyentuh inti GBrain (risiko regresi besar) demi masalah tampilan; juga akan
   mengubah test `tests/test_gbrain.py` yang sudah hijau serta konsumen lain (`format_memory`).
   Deviasi tidak diambil.
2. **Menambah field `seconds`/durasi ke event memory** agar baris memory punya durasi.
   ➡️ **Ditolak (YAGNI).** Durasi sudah tampil di baris `step`. Menambah field = menyentuh
   `team.py`/`flow.py`. Open question untuk CEO.
3. **Menambah toolchain JS (node/jsdom) untuk menguji `app.js`.**
   ➡️ **Ditolak.** Perubahan besar ke repo untuk satu perbaikan teks; melanggar "change the smallest
   thing". Dipakai pola ekstraksi + `node` bila tersedia.
4. **Merender daftar temuan sebagai baris penuh (5 fact + 5 slug) di timeline.**
   ➡️ **Ditolak sebagian.** Membanjiri timeline live run. Dipilih: 3 temuan pertama di `↳`,
   sisanya di tooltip.

---

## 7. Yang bukan bagian tugas ini (Out of scope)

- `babd/gbrain.py` — `recall`, `keywords`, `format_memory`: tidak disentuh.
- `babd/flow.py`, `babd/team.py`: tidak disentuh.
- Bentuk JSON `agentlog` (field `type`/`detail`) : tidak berubah, hanya `text`.
- Halaman "Memory search" lain di `app.js:1975` (`${r.facts.length} fact(s), ${r.results.length} page(s)`):
  **di luar scope** — itu panel pencarian manual, bukan live run. Dicatat sebagai open question.
- Terjemahan seluruh UI dashboard ke Indonesia.

---

## 8. Open questions (untuk CEO, lewat Team Lead)

Semua dijawab dengan asumsi saya dan **tidak menunggu**:

- **Q1 — Bahasa.** Baris memory berbahasa Indonesia, UI lain Inggris.
  ➡️ **Asumsi: Indonesia hanya untuk baris memory.**
- **Q2 — Kedalaman.** Cukup satu baris, atau plus isi temuan?
  ➡️ **Asumsi: ringkas + `↳` 3 temuan + tooltip penuh** (data `items` sudah ada, nol biaya backend).
- **Q3 — Istilah jumlah.** "catatan/halaman" atau tetap "fact(s)/page(s)"?
  ➡️ **Asumsi: "catatan/halaman"** di UI; "fact" tetap di istilah internal/agent log teknis.
- **Q4 — Durasi per langkah memory.** Perlu, atau cukup di baris `step`?
  ➡️ **Asumsi: cukup di baris `step`** (tidak menambah field ke `team.py`).
- **Q5 — Panel "Memory search" (`app.js:1975`).** Ikut dirapikan juga?
  ➡️ **Asumsi: tidak** (di luar goal "live run"), dicatat bila CEO mau lanjutkan di run berikutnya.

---

## 9. Risiko

| Risiko | Dampak | Mitigasi |
|---|---|---|
| `node` tidak tersedia untuk test helper JS | Test perilaku teks JS lemah (skip) | Assertion teks Python tetap wajib; QA melaporkan status `node` eksplisit |
| Query berisi `" or "` sebagai kata biasa | Pemecahan salah | Pecah pada `/\s+or\s+/i` **dan** sertakan test `memoryKeywords("cats or dogs")` → `["cats","dogs"]` (sesuai kontrak gbrain, memang pemisah) |
| `items` kosong/`undefined` pada event `write` | Tooltip mencetak `undefined` | `memoryHeadline` selalu mengembalikan `detail` sebagai array |
| `facts`/`pages` = 0 | Tampil "0 fact(s), 0 page(s)" | Pesan "Tidak ada memori terkait — kamu yang pertama" |
| Kata kunci sangat panjang | Merusak layout | Batas 6 kata + `…`; CSS `.mem` sudah `flex-wrap: wrap` |
| Nilai `facts`/`pages` non-angka (data lama) | Cetak `NaN` | Koersi aman di `memoryCountLine` |
| `agentlog.py` teks berubah | Test lama `test_agentlog.py`/`test_dashboard.py` merah | Tim QA menambah test baru dan memverifikasi suite penuh |

**Semua hasil test di dokumen ini berlabel NOT RUN** — saya Architect, tidak menjalankannya sendiri.
