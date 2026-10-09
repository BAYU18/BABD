# Rencana Implementasi: Teks Live Run Dashboard BABD Lebih Informatif

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Baris langkah GBrain di live run dashboard menampilkan aksi manusiawi, kata kunci asli (bukan `a or b or c`), isi temuan, dan jumlah yang jelas.

**Architecture:** Perbaikan presentasi murni di klien + satu titik server-side. Satu helper murni
`memoryHeadline(m)` di `app.js` menjadi satu-satunya sumber kebenaran teks memory, dipakai di 3
titik render; `agentlog.py` memformat ulang teksnya. Backend (`gbrain.py`, `flow.py`, `team.py`)
tidak disentuh.

**Tech Stack:** JavaScript vanilla (`babd/dashboard/static/app.js`), Python `unittest` (repo memakai
`python -m unittest discover -s tests`).

**Spec:** `docs/superpowers/specs/2026-10-09-live-run-memory-text-design.md`

## Global Constraints

- Bahasa output baris memory: **Indonesia** ("Membaca memori tim", "catatan", "halaman", "kata kunci", "temuan").
- Semua nilai dinamis di HTML **wajib** lewat `esc()` (`app.js:25`). Tidak ada `innerHTML` dari data run.
- Tidak menyentuh `babd/gbrain.py`, `babd/flow.py`, `babd/team.py`.
- Tidak menambah field baru pada event `memory`; `items` sudah tersedia (`team.py:136-138`).
- Tidak menambah dependency / toolchain JS baru ke repo.
- Batas kata kunci yang ditampilkan: **6** (+ `…`); batas temuan di baris `↳`: **3** (tooltip tetap semua).
- Pisah kata kunci pada `/\s+or\s+/i`, buang kosong, `trim`.
- Angka non-numerik (`undefined`, `null`, `"x"`) diperlakukan `0`; jangan pernah cetak `NaN`.

## Review Focus

- Query berisi `" or "` sebagai pemisah kata kunci → harus dipecah (`"a or b or c"` → 3 kata kunci).
- Query **tanpa** `" or "` (mis. `"researcher"`) → tetap 1 kata kunci utuh, tidak dipecah salah.
- `facts = 0` dan `pages = 0` → pesan "Tidak ada memori terkait — kamu yang pertama", bukan `0 catatan`.
- `items` kosong/`undefined` (event `write`, atau data lama) → tooltip aman, tidak mencetak `undefined`.
- Query berisi tag HTML (`<img src=x onerror=...>`) → ter-escape di keempat titik render.

---

### Task 1: Helper murni teks memory di `app.js` + test

**Files:**
- Modify: `babd/dashboard/static/app.js` (sisipkan blok helper tepat sebelum `function memoryItem(m)`, sekitar baris 558)
- Test: `tests/test_memory_text.py` (baru)

**Interfaces:**
- Consumes: tidak ada (task pertama).
- Produces:
  - `memoryKeywords(query: string) -> string[]` — pecah pada `/\s+or\s+/i`, buang kosong, `trim`, maks 6 (index ke-6 → `"…"`).
  - `memoryCountLine(facts: number, pages: number) -> string` — `"3 catatan, 1 halaman"`; `(0,0)` → `""`.
  - `memoryHeadline(m: object) -> {label: string, count: string, keywords: string[], detail: string[], empty: boolean}`

- [ ] **Step 1: Tulis test yang gagal**

Buat `tests/test_memory_text.py` dengan pola repo (unittest, `sys.path.insert` ke root):

```python
"""Teks baris memory live run: helper murni di app.js + ketiga titik render memakainya.

Helper JS diuji lewat `node` bila tersedia (repo tidak punya harness JS);
assertion teks pada app.js selalu berjalan.

Run: python -m unittest discover -s tests
"""
import json
import os
import re
import shutil
import subprocess
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

APP_JS = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                      "babd", "dashboard", "static", "app.js")
NODE = shutil.which("node")


def app_js():
    with open(APP_JS) as f:
        return f.read()


def helper_block():
    src = app_js()
    m = re.search(r"// ---- memory text helpers.*?// ---- end memory text helpers ----", src, re.S)
    assert m, "blok helper memory tidak ditemukan di app.js"
    return m.group(0)


def js_eval(cases):
    """Jalankan helper blok di node, kembalikan list hasil per kasus."""
    script = helper_block() + "\nconst cases = " + json.dumps(cases) + ";\n" + \
        "console.log(JSON.stringify(cases.map((c) => eval(c))));"
    out = subprocess.run([NODE, "--input-type=module", "-e", script],
                         capture_output=True, text=True, check=True)
    return json.loads(out.stdout.strip().splitlines()[-1])


@unittest.skipUnless(NODE, "node tidak ada: helper JS tidak diuji langsung")
class MemoryHelperTest(unittest.TestCase):
    def test_keywords_split_on_or(self):
        got = js_eval([
            "memoryKeywords('a or b or c')",
            "memoryKeywords('')",
            "memoryKeywords('researcher')",
            "memoryKeywords('cats or dogs')",
        ])
        self.assertEqual(got, [["a", "b", "c"], [], ["researcher"], ["cats", "dogs"]])

    def test_keywords_capped_at_six(self):
        got = js_eval(["memoryKeywords('a or b or c or d or e or f or g or h').join(',')"])[0]
        self.assertTrue(got.startswith("a,b,c,d,e,f"), got)
        self.assertTrue(got.endswith("…"), got)

    def test_count_line_singular_plural(self):
        got = js_eval([
            "memoryCountLine(3, 1)",
            "memoryCountLine(1, 0)",
            "memoryCountLine(0, 0)",
            "memoryCountLine(undefined, 'x')",
        ])
        self.assertEqual(got, ["3 catatan, 1 halaman", "1 catatan, 0 halaman", "", "0 catatan, 0 halaman"])

    def test_headline_read_empty_and_write(self):
        got = js_eval([
            "JSON.stringify(memoryHeadline({op:'read',facts:3,pages:1,query:'a or b',items:['f1','p1']}))",
            "JSON.stringify(memoryHeadline({op:'read',facts:0,pages:0,query:'x',items:[]}))",
            "JSON.stringify(memoryHeadline({op:'write',page:'some/slug'}))",
            "JSON.stringify(memoryHeadline({op:'read',facts:2,pages:0,query:'q'}))['detail'].length",
        ])
        first = json.loads(got[0])
        self.assertEqual(first["label"], "Membaca memori tim")
        self.assertEqual(first["count"], "3 catatan, 1 halaman")
        self.assertEqual(first["keywords"], ["a", "b"])
        self.assertEqual(first["detail"], ["f1", "p1"])
        self.assertFalse(first["empty"])
        self.assertTrue(json.loads(got[1])["empty"])
        self.assertEqual(json.loads(got[2])["label"], "Menyimpan ke memori tim")
        self.assertEqual(got[3], 0)  # items hilang -> detail array kosong, bukan undefined


class RenderSitesTest(unittest.TestCase):
    """Ketiga titik render di app.js memakai helper, bukan 'fact(s)' / query mentah."""

    def test_memory_item_uses_helper(self):
        src = app_js()
        self.assertIn("memoryHeadline(", src)
        self.assertNotRegex(src, r"read gbrain · \$\{m\.facts\} fact\(s\)")
        self.assertNotRegex(src, r"\$\{m\.facts\} fact\(s\)")

    def test_event_lines_use_helper(self):
        src = app_js()
        self.assertNotIn("read gbrain", src)
        self.assertIn("Membaca memori tim", src)
        self.assertIn("Menyimpan ke memori tim", src)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Jalankan test, pastikan GAGAL**

Run: `python -m unittest tests.test_memory_text -v` (dari root worktree)
Expected: FAIL / ERROR — `blok helper memory tidak ditemukan di app.js` (blok belum ada).

- [ ] **Step 3: Implementasi blok helper di `app.js`**

Sisipkan tepat sebelum `function memoryItem(m) {` (sekitar baris 558):

```js
// ---- memory text helpers (pure; tested by tests/test_memory_text.py) ----
const MEM_KEYWORDS_MAX = 6;
const MEM_ITEMS_SHOWN = 3;

function memoryNum(v) {
  const n = Number(v);
  return Number.isFinite(n) && n > 0 ? Math.floor(n) : 0;
}

function memoryKeywords(query) {
  const parts = String(query ?? "").split(/\s+or\s+/i).map((w) => w.trim()).filter(Boolean);
  if (parts.length <= MEM_KEYWORDS_MAX) return parts;
  return [...parts.slice(0, MEM_KEYWORDS_MAX), "…"];
}

function memoryCountLine(facts, pages) {
  const f = memoryNum(facts), p = memoryNum(pages);
  if (!f && !p) return "";
  const cat = (n, word) => `${n} ${word}`;
  return `${cat(f, "catatan")}, ${cat(p, "halaman")}`;
}

function memoryHeadline(m) {
  const read = m.op === "read";
  const detail = (read ? m.items || [] : m.fact ? [m.fact] : []).map(String);
  const facts = read ? memoryNum(m.facts) : 0;
  const pages = read ? memoryNum(m.pages) : 0;
  return {
    label: read ? "Membaca memori tim" : "Menyimpan ke memori tim",
    count: read ? memoryCountLine(facts, pages) : "",
    keywords: read ? memoryKeywords(m.query) : [],
    detail,
    empty: read && !facts && !pages,
  };
}
// ---- end memory text helpers ----
```

Catatan implementasi: `memoryHeadline` **tidak** menyentuh DOM dan tidak memanggil `esc()` — escaping
tetap tugas pemanggil, sesuai pola `app.js` yang sudah ada.

- [ ] **Step 4: Jalankan test, pastikan helper PASS**

Run: `python -m unittest tests.test_memory_text.MemoryHelperTest -v`
Expected: PASS untuk `MemoryHelperTest` (atau SKIP dengan alasan "node tidak ada" — catat mana yang terjadi).
`RenderSitesTest` **masih FAIL** — itu benar, dikerjakan di Task 2.

- [ ] **Step 5: Commit**

```bash
git add babd/dashboard/static/app.js tests/test_memory_text.py
git commit -m "feat(dashboard): helper murni teks memory + test"
```

---

### Task 2: Pakai helper di tiga titik render `app.js`

**Files:**
- Modify: `babd/dashboard/static/app.js:558-566` (`memoryItem`), `app.js:1698` (activity feed `memory`), `app.js:1718` (live event `run` → `memory`)
- Test: `tests/test_memory_text.py` (kelas `RenderSitesTest` dari Task 1, sudah ada)
- Modify (CSS, bila perlu): `babd/dashboard/static/app.css:167-174`

**Interfaces:**
- Consumes: `memoryHeadline(m)` dari Task 1.
- Produces: tidak ada API baru; hanya string yang dirender.

- [ ] **Step 1: Jalankan test render, pastikan GAGAL**

Run: `python -m unittest tests.test_memory_text.RenderSitesTest -v`
Expected: FAIL — `'read gbrain' unexpectedly found in app.js` (titik render masih memakai teks lama).

- [ ] **Step 2: Ganti `memoryItem` (`app.js:558-566`)**

```js
function memoryItem(m) {
  const h = memoryHeadline(m);
  const head = `<span class="mem-dot"></span>
    <span class="who" style="--c:${colorOf(m.agent)}">${esc(nameOf(m.agent))}</span>
    <span class="mem-act">${esc(h.label)}</span>`;
  const bits = [];
  if (h.count) bits.push(`<span class="kind">${esc(h.count)}</span>`);
  if (h.keywords.length) bits.push(`<span class="mem-kw">kata kunci: ${esc(h.keywords.join(", "))}</span>`);
  const empty = h.empty ? ` <span class="mem-empty">Tidak ada memori terkait — kamu yang pertama</span>` : "";
  const found = !h.empty && h.detail.length
    ? `<span class="mem-found">↳ ${h.detail.length} temuan: ${esc(h.detail.slice(0, MEM_ITEMS_SHOWN).map((d) => `"${d}"`).join(", "))}${h.detail.length > MEM_ITEMS_SHOWN ? " …" : ""}</span>`
    : "";
  return `<li class="mem ${m.op}" title="${esc(h.detail.join("\n"))}">${head}
    <span class="mem-mid">${bits.join(" · ")}${empty}${found}</span>
    <span class="msg-time">${fmtTime(m.at)}</span></li>`;
}
```

- [ ] **Step 3: Ganti activity feed (`app.js:1698`)**

Ganti baris `logLine("gbrain", ...)` menjadi:

```js
es.addEventListener("memory", (e) => { const m = JSON.parse(e.data); flashMemory(m.agent, m.op); logLine("gbrain", memoryLogText(nameOf(m.agent), m)); });
```

- [ ] **Step 4: Ganti live event log (`app.js:1718`)**

Ganti baris `if (d.event === "memory") logLine("gbrain", ...)` menjadi:

```js
if (d.event === "memory") logLine("gbrain", memoryLogText(nameOf(d.data.agent), d.data));
```

- [ ] **Step 5: Tambah `memoryLogText(who, m)` di blok helper (satu baris teks untuk log)**

Sisipkan tepat **sebelum** `// ---- end memory text helpers ----`:

```js
function memoryLogText(who, m) {
  const h = memoryHeadline(m);
  if (h.empty) return `${who} · ${h.label} · tidak ada memori terkait · kata kunci: ${h.keywords.join(", ")}`;
  const kw = h.keywords.length ? ` · kata kunci: ${h.keywords.join(", ")}` : "";
  return `${who} · ${h.label}${h.count ? ` · ${h.count}` : ""}${kw}`;
}
```

- [ ] **Step 6: (Bila perlu) tambah CSS**

Tambahkan setelah `.mem .who` (`app.css:169`), **hanya** bila baris `↳` membungkus jelek:

```css
.mem .mem-act { font-weight: 700; }
.mem .mem-kw { font-family: var(--mono); font-size: 10.5px; color: var(--dim); }
.mem .mem-empty { font-style: italic; }
.mem .mem-found { flex-basis: 100%; color: var(--dim); font-size: 11px; }
```

- [ ] **Step 7: Jalankan seluruh test memory-text, pastikan PASS**

Run: `python -m unittest tests.test_memory_text -v`
Expected: PASS (atau `MemoryHelperTest` SKIP bila `node` tidak ada; `RenderSitesTest` wajib PASS).

- [ ] **Step 8: Jalankan suite penuh**

Run: `python -m unittest discover -s tests`
Expected: PASS semua (nol regresi pada `test_gbrain.py`, `test_dashboard.py`, `test_agentlog.py`).

- [ ] **Step 9: Commit**

```bash
git add babd/dashboard/static/app.js babd/dashboard/static/app.css tests/test_memory_text.py
git commit -m "feat(dashboard): baris memory live run dalam bahasa manusia"
```

---

### Task 3: Teks `agentlog.py` + regresi & escaping (QA)

**Files:**
- Modify: `babd/agentlog.py:74-78` (`entries_for("memory", …)`)
- Test: `tests/test_agentlog.py` (tambah method di kelas `AgentLogTest`)

**Interfaces:**
- Consumes: bentuk `text` dari Task 2 (Bahasa Indonesia, tanpa `or`).
- Produces: `entries_for("memory", …)` tetap mengembalikan `(agent_id, {"type": "memory", "text", "detail"})`.

- [ ] **Step 1: Tulis test yang gagal di `tests/test_agentlog.py`**

```python
    def test_memory_text_read_and_write(self):
        read = agentlog.entries_for("memory", {"agent": "qa", "op": "read", "facts": 3, "pages": 1,
                                              "query": "tambah or agent or repo", "items": ["f1", "slug1"]})
        self.assertEqual(read[0][0], "qa")
        self.assertEqual(read[0][1]["type"], "memory")
        text = read[0][1]["text"]
        self.assertIn("3 catatan", text)
        self.assertIn("1 halaman", text)
        self.assertIn("tambah, agent, repo", text)
        self.assertNotIn(" or ", text)
        self.assertEqual(read[0][1]["detail"], "f1\nslug1")
        none = agentlog.entries_for("memory", {"agent": "qa", "op": "read", "facts": 0, "pages": 0,
                                              "query": "x", "items": []})[0][1]["text"]
        self.assertIn("tidak ada", none)
        wrote = agentlog.entries_for("memory", {"agent": "qa", "op": "write", "page": "a/b",
                                               "fact": "ringkas"})[0][1]
        self.assertIn("a/b", wrote["text"])
        self.assertEqual(wrote["detail"], "ringkas")
```

- [ ] **Step 2: Jalankan, pastikan GAGAL**

Run: `python -m unittest tests.test_agentlog.AgentLogTest.test_memory_text_read_and_write -v`
Expected: FAIL — `'read GBrain: 3 fact(s), 1 page(s)'` tidak memuat `3 catatan`.

- [ ] **Step 3: Implementasi di `babd/agentlog.py:74-78`**

```python
    elif kind == "memory" and d.get("agent"):
        if d.get("op") == "read":
            facts, pages = int(d.get("facts") or 0), int(d.get("pages") or 0)
            kws = [w.strip() for w in re.split(r"\s+or\s+", str(d.get("query") or ""), flags=re.I) if w.strip()][:6]
            kw = f" · kata kunci: {', '.join(kws)}" if kws else ""
            if facts or pages:
                text = f"Baca memori tim: {facts} catatan, {pages} halaman{kw}"
            else:
                text = f"Baca memori tim: tidak ada yang cocok{kw}"
        else:
            text = f"Simpan ke memori tim: {d.get('page')}"
        out.append((d["agent"], {"type": "memory", "text": text,
                                 "detail": "\n".join(str(x) for x in d.get("items") or []) or d.get("fact")}))
```

Tambah `import re` di header `babd/agentlog.py` bila belum ada (saat ini hanya `json`, `os`, `threading`).

- [ ] **Step 4: Jalankan, pastikan PASS**

Run: `python -m unittest tests.test_agentlog -v`
Expected: PASS — termasuk `test_a_task_fills_every_agents_log` (tidak regresi; ia hanya memeriksa
teks `step`/`message`, bukan `memory`).

- [ ] **Step 5: Jalankan suite penuh (wajib sebelum klaim PASS)**

Run: `python -m unittest discover -s tests`
Expected: PASS semua. Bila ada yang merah, laporkan output nyata dan kembalikan ke Developer.

- [ ] **Step 6: Uji escaping XSS manual (bukti nyata, bukan asumsi)**

Jalankan dengan `node` bila ada:

```bash
python - <<'PY'
import json, re, shutil, subprocess
src = open("babd/dashboard/static/app.js").read()
block = re.search(r"// ---- memory text helpers.*?// ---- end memory text helpers ----", src, re.S).group(0)
cases = "['memoryKeywords(\"<img src=x onerror=alert(1)> or b\")']"
script = block + "\nconsole.log(JSON.stringify(" + cases + "))"
print(subprocess.run([shutil.which("node"), "--input-type=module", "-e", script], capture_output=True, text=True).stdout)
PY
```

Expected: tag HTML tetap utuh sebagai **teks** di dalam array (helper tidak merusaknya) dan
`esc()` di ketiga titik render yang meng-escape saat dirender. Bila `node` tidak ada, laporkan
sebagai **NOT RUN** dan sebutkan bahwa `esc()` sudah dipakai di semua interpolasi.

- [ ] **Step 7: Commit**

```bash
git add babd/agentlog.py tests/test_agentlog.py
git commit -m "feat(agentlog): teks memory Bahasa Indonesia + test"
```

---

## Self-review (dijalankan sendiri oleh Architect)

**1. Cakupan spec:** D1 (tanpa backend) → tidak ada task menyentuh `gbrain/flow/team` ✔.
D2 (helper) → Task 1 + Task 3 ✔. D3 (dua bagian + tooltip) → Task 2 step 2 ✔.
D4 (jalur test nyata) → Task 1 Step 1 + catatan `skipUnless` ✔. D5 (Indonesia) → Global Constraints ✔.

**2. Skenario langkah:** setiap step bisa dikerjakan tanpa menebak nama/signature; body kode
diberikan hanya karena nilainya dipatok spec (PASS/FAIL string, batas 6/3). Tidak ada "TBD".

**3. Konsistensi tipe:** `memoryHeadline` dipakai dengan nama field yang sama
(`label/count/keywords/detail/empty`) di Task 1 test, Task 2 render, dan `memoryLogText` ✔.
`MEM_ITEMS_SHOWN`/`MEM_KEYWORDS_MAX` didefinisikan sekali di Task 1, dipakai Task 2 ✔.

**4. Review Focus:** 5 baris, masing-masing punya test pemiliknya — `" or "` (T1), kata kunci
tunggal (T1 `test_keywords_split_on_or`), nol temuan (T1 `test_count_line_singular_plural` +
`test_headline_read_empty_and_write`, T3 `test_memory_text_read_and_write`), `items` kosong
(T1 `test_headline_read_empty_and_write` baris `detail.length == 0`, T3 detail fallback
``d.get("fact")``), XSS (T3 Step 6 + `esc()` di semua interpolasi).

**5. Proporsi:** rencana ≈ 1,3× panjang spec; blok kode adalah signature/aturan nilai yang spec
patok, bukan transkrip program. Layak.

## Risiko untuk agen berikutnya

- **Test helper JS bergantung `node`.** Bila `node` tidak ada, `MemoryHelperTest` SKIP dan hanya
  assertion teks yang menguji. Jangan pernah melaporkan PASS untuk kasus yang SKIP.
- **`RenderSitesTest.test_event_lines_use_helper` meng-assert `"read gbrain"` tidak ada di seluruh
  `app.js`.** Bila ada teks lain kebetulan memuat string itu di masa depan, test akan merah — itu
  disengaja agar masalah yang sama tidak muncul kembali.
- **Task 3 mengubah `agentlog.py`**, file yang dipakai jalur dashboard/Telegram/CLI. Perubahan hanya
  pada string `text`; bentuk dict tidak berubah, jadi konsumen (`app.js` agent-log panel) aman.
- Semua hasil test di rencana ini **NOT RUN** oleh Architect.
