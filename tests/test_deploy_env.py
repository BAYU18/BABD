"""Kontrak `docs/researcher/DEPLOY.env.example` vs variabel yang BENAR-BENAR dibaca adapter.

Latar (QA round 1, blocker B-5): dua fix Developer dan berkas deploy DevOps hidup tanpa tes
permanen. Berkas contoh env adalah kontrak operasional — kalau seorang DevOps menghapus/mengganti
nama variabel di sana, deploy "terlihat benar" tapi researcher jatuh ke mode exit 2 tanpa sebab
yang jelas. Test ini mengikat berkas itu ke pembacaan env nyata di `scripts/researcher_adapter.py`,
sehingga perubahan yang memutus kontrak menjadi MERAH, bukan diam-diam.

Yang diuji adalah perilaku/contract yang bisa difalsifikasi:
  E-1  setiap variabel yang di-*set* oleh contoh env punya KEY=VALUE yang valid (bukan prosa);
  E-2  contoh env memuat tepat satu provider aktif dan konsisten dengan kode (`RESEARCHER_PROVIDER`);
  E-3  `RESEARCHER_FAKE` hanya muncul di komentar (tidak boleh aktif di produksi);
  E-4  berkas ada DAN terlacak git (kalau untracked ia hilang saat worktree dibersihkan).

Run: python -m unittest tests.test_deploy_env -v
"""
import os
import re
import subprocess
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
ENV_EXAMPLE = os.path.join(ROOT, "docs", "researcher", "DEPLOY.env.example")
ADAPTER = os.path.join(ROOT, "scripts", "researcher_adapter.py")

KEY_RE = re.compile(r"^[A-Z_][A-Z0-9_]*=")


def active_lines(path):
    """Baris non-komentar, non-kosong (yang benar-benar berlaku bila file di-source)."""
    out = []
    with open(path, encoding="utf-8") as f:
        for raw in f:
            line = raw.strip()
            if not line or line.startswith("#"):
                continue
            out.append(line)
    return out


def env_keys(path):
    keys = {}
    for line in active_lines(path):
        key, _, value = line.partition("=")
        keys[key.strip()] = value.strip()
    return keys


class DeployEnvContractTest(unittest.TestCase):

    def setUp(self):
        self.assertTrue(os.path.isfile(ENV_EXAMPLE),
                        f"contoh env deploy hilang: {ENV_EXAMPLE}")

    def test_e1_every_active_line_is_a_valid_key_value(self):
        """Tanpa ini, baris prosa yang lolos ke produksi menjadi env var sampah."""
        for line in active_lines(ENV_EXAMPLE):
            self.assertRegex(line, KEY_RE, f"baris aktif bukan KEY=VALUE: {line!r}")

    def test_e2_one_active_provider_consistent_with_the_code(self):
        """Contoh env harus menyebut provider persis seperti yang dikenali adapter."""
        keys = env_keys(ENV_EXAMPLE)
        self.assertIn("RESEARCHER_PROVIDER", keys, "contoh env harus menetapkan provider aktif")
        provider = keys["RESEARCHER_PROVIDER"].lower()
        with open(ADAPTER, encoding="utf-8") as f:
            src = f.read()
        known = set(re.findall(r'"(\w+)":\s*\(', src))  # RESEARCHER_PROVIDER -> akun kind
        self.assertIn(provider, known, f"provider '{provider}' tidak dikenal adapter: {sorted(known)}")
        # Provider duckduckgo WAJIB disertai flag izinnya, kalau tidak adapter tetap exit 2.
        if provider == "duckduckgo":
            self.assertEqual(keys.get("RESEARCHER_ALLOW_DUCKDUCKGO"), "1",
                             "provider duckduckgo butuh RESEARCHER_ALLOW_DUCKDUCKGO=1")
        if provider == "searxng":
            self.assertIn("RESEARCHER_SEARXNG_URL", keys,
                          "provider searxng butuh RESEARCHER_SEARXNG_URL")

    def test_e3_fake_mode_is_never_active_in_the_example(self):
        """Hasil sintetis tidak boleh jadi default produksi."""
        self.assertNotIn("RESEARCHER_FAKE", env_keys(ENV_EXAMPLE),
                         "RESEARCHER_FAKE hanya boleh di komentar, tidak aktif")

    def test_e4_the_example_is_tracked_by_git(self):
        """Berkas untracked = dokumen terbaca hilang saat worktree dibersihkan (QA B-5)."""
        rc = subprocess.run(["git", "ls-files", "--error-unmatch",
                             "docs/researcher/DEPLOY.env.example"],
                            cwd=ROOT, capture_output=True, text=True)
        self.assertEqual(rc.returncode, 0,
                         "docs/researcher/DEPLOY.env.example belum di-commit; ia akan hilang")


if __name__ == "__main__":
    unittest.main()
