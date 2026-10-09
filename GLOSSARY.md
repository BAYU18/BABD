# GLOSSARY

Istilah domain BABD. Tanpa detail implementasi — hanya makna.

## Agent

**Lead (Team Lead)** — agent yang memegang rencana, prioritas dan scope sebuah task. `agents[0]`
di `agents.json`. Satu-satunya agent yang berbicara langsung dengan CEO.

**Specialist** — setiap agent selain Lead. Punya satu area kerja (design, code, test, deploy,
atau riset) dan bisa di-assign langsung maupun ditanya agent lain.

**Researcher** — specialist yang tugasnya mencari di internet dan melaporkan temuan **beserta
sumbernya**. Ia menemukan dan mengutip; ia tidak mengubah kode atau mesin.

**Peer question** — pertanyaan dari satu agent ke agent lain (baris `ASK: <agent id>`) yang
dijawab tanpa melibatkan CEO. Berlaku dua arah antar specialist.

**Roster** — daftar agent yang dikenal sebuah instalasi BABD (`agents.json`). Roster yang lebih
lama boleh tidak punya Researcher; itu bukan error.

## Penemuan (temuan riset)

**Finding** — satu temuan dari hasil riset: pernyataan jawaban disertai daftar **Source**.

**Source (sumber)** — pasangan judul + URL yang benar-benar dikembalikan mesin pencari.
Sebuah Source **tidak pernah** dikarang; finding tanpa provider yang tersedia dilaporkan
sebagai kegagalan, bukan sebagai temuan kosong yang tampak sah.

**Local** — sifat riset yang dijalankan di mesin ini (gpt-researcher yang di-vendor, LLM dari
endpoint tim sendiri), bukan layanan pihak ketiga di awan.

## Alur (flow)

**Route** — keputusan Team Lead atas bentuk pengerjaan: `answer` (Lead menjawab), `direct`
(satu specialist), atau `team` (alur penuh).

**Skip** — specialist yang sengaja tidak diikutsertakan pada sebuah task (mis. Researcher pada
task yang tidak butuh riset). Skip tidak sama dengan "agent tidak ada di roster".

**Work package** — potongan pekerjaan yang boleh berjalan paralel, tiap potongan menunjuk satu
agent dan daftar `depends_on`.

**Prep** — persiapan paralel: QA menulis test plan dan DevOps menyiapkan deploy sementara
Developer membangun.

## Kendaraan teknis

**Harness** — cara sebuah agent mengubah (system prompt, percakapan) menjadi jawaban (mis.
`direct`, `claude_local`, atau `process`).

**Process harness** — harness yang menjalankan sebuah program: prompt di stdin, jawaban di
stdout. Dipakai Researcher untuk memanggil gpt-researcher lokal.

**Adapter** — program yang berdiri di seam process harness: menerima stdin, memanggil library
lokal, mencetak stdout dengan skema yang disepakati.
