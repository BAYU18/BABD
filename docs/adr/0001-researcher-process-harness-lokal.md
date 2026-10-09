# 0001 — Researcher dijalankan sebagai process-harness lokal, bukan microservice

Status: diusulkan · Tanggal: 2026-10-09 · Penulis: Architect

## Konteks

CEO meminta agent keenam `researcher` yang memakai repo `assafelovic/gpt-researcher` dan
**berjalan lokal**. gpt-researcher adalah library Python yang butuh LLM dan sebuah search
provider. BABD sudah punya harness `process` (`babd/harness/others.py:123-169`) yang
menjalankan program apa pun: prompt di stdin, jawaban di stdout, LLM settings diteruskan
lewat env oleh `generic_routing()` (`babd/harness/routing.py:98-113`).

## Keputusan

Researcher memakai `harness.type = "process"` yang menjalankan adapter lokal; adapter memanggil
gpt-researcher sebagai library yang di-vendor di `.babd/researcher/`, dengan venv terpisah.
Command di `agents.json` disimpan relatif dan di-resolusi terhadap `ROOT` oleh
`Process.command_path()`.

## Alternatif yang ditolak

- **Agent BABD biasa dengan skill web research yang diperkuat.** Ditolak: CEO eksplisit meminta
  repo gpt-researcher, bukan sekadar agent yang bisa browsing.
- **gpt-researcher sebagai microservice HTTP (FastAPI).** Ditolak: menambah proses yang harus
  dijaga hidup (port, health check, restart) untuk manfaat yang sama; gpt-researcher memang
  dipakai sebagai library. Kegagalan jadi kegagalan *step* lewat harness, bukan kegagalan
  sistem diam-diam.

## Konsekuensi

- Tidak ada port baru yang dibuka; tidak ada service yang bisa "mati diam-diam".
- Riset dibatasi `timeout_sec: 600` dan `parallel: 1` supaya tidak mengunci kapasitas.
- Kegagalan provider pencarian jadi exit code 2 dari adapter → `HarnessError` dengan pesan
  asli di laporan, bukan jawaban palsu.
- **Sulit dibalik** karena pilihan ini menembus `agents.json` (roster + skill pack + dashboard):
  berpindah ke microservice berarti mengubah mode kegagalan dan file konfigurasi yang sama.
  Inilah alasan ADR ini dibuat.
- Menambah entri `researcher` ke `ROLES` (`babd/flow.py:42`) menyentuh validasi flow, routing,
  dan deskripsi plan; kompatibilitas ke belakang dijaga oleh `specialist_roles(team)`.
