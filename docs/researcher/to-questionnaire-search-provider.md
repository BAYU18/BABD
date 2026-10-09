# Questionnaire — Keputusan sumber pencarian untuk agent "researcher"

**Purpose:** agent "researcher" sudah bisa mencari, tapi cara mencari resminya belum dipilih.
Keputusan ini menentukan apakah hasil risetnya bisa dipercaya. Selama belum dipilih, agent ada
tetapi berhenti sendiri (gagal jujur, tidak mengarang sumber).

**From:** Team Lead BABD, **To:** CEO (pemegang akun dan keputusan biaya),
**How your answers will be used:** jawaban Anda ditulis ke konfigurasi resmi BABD (bukan ke
dalam kode), lalu QA menguji ulang dan DevOps men-deploy setelah Anda menyetujui.

## Context

Agent "researcher" bekerja lokal dan mencari di internet lewat sebuah mesin pencari. Saat ini
mesin yang tersedia tanpa akun dan tanpa biaya adalah pencarian umum (DuckDuckGo). Mesin itu
kadang memberi hasil yang tidak nyambung dengan pertanyaan, jadi jawabannya bisa tampak benar
padahal sumbernya salah. Pilihan yang lebih stabil butuh sedikit pekerjaan pemasangan
(SearXNG lokal) atau akun berbayar (Tavily). Mesin ini belum punya Docker, jadi SearXNG lokal
tidak bisa dipasang di sini tanpa bantuan Anda.

## How to answer

Kami hanya butuh satu putaran. Isi sebisanya; "saya tidak tahu" adalah jawaban yang berguna -
lebih baik ditandai daripada dilewati. Tidak ada istilah teknis yang wajib Anda pahami.

## Sumber pencarian

### Bolehkah agent memakai pencarian umum gratis sebagai cara mencari resminya?

_Why this matters: ini pilihan termurah dan sudah aktif; risikonya adalah sumber kadang tidak relevan, jadi jawaban agent kurang bisa diandalkan._

> ya, pakai gratis / tidak, saya mau yang lebih stabil / lain: ____

### Apakah di mesin ini boleh dipasang alat pencarian lokal tambahan (SearXNG)?

_Why this matters: hasilnya paling stabil dan tanpa biaya, tapi butuh satu kali pemasangan oleh Anda._

> ya, saya izinkan / tidak perlu / lain: ____

### Apakah Anda menyediakan akun pencarian berbayar untuk hasil paling stabil?

_Why this matters: ini yang paling dapat dipercaya, tapi menimbulkan biaya bulanan._

> ya, saya siapkan / tidak / lain: ____

### Kalau nanti alat gratis gagal mencari, apa yang harus agent lakukan?

_Why this matters: menentukan apakah agent berhenti dengan pesan jujur, atau melaporkan hasil seadanya._

> berhenti dan bilang gagal / lanjut dengan peringatan jelas / lain: ____

## Batas dan izin

### Berapa lama maksimal satu pencarian boleh berjalan?

_Why this matters: terlalu lama menahan pekerjaan tim lain; terlalu cepat membuat hasil terpotong._

> ____ menit (usul kami: 10)

### Bolehkah agent memakai layanan kecerdasan yang sudah tim ini pakai sekarang?

_Why this matters: kalau ya, tidak perlu akun dan biaya baru._

> ya / tidak, saya buatkan terpisah / lain: ____

## Anything else?

Ada hal lain yang sebaiknya kami tahu soal cara tim ini mencari informasi?

> 
