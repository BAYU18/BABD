# Setup Project Kardel untuk Tim BABD

## Ringkasan
Tim BABD sudah dikonfigurasi untuk bekerja di repo **BAYU18/kardel**
(Solana Sniper Bot, Node.js).

## Akses Git (Deploy Key)
- **Deploy key kardel**: `~/.ssh/id_ed25519_github_account.pub`
  - Fingerprint: `SHA256:BjQsDbaHtp2PP8fD6y5OaaWbvf4b6cUFV0R/utu5uYs` (babd-github-account@serverbot)
  - Di-add sebagai Deploy Key di repo BAYU18/kardel
- **SSH config** (`~/.ssh/config`):
  - Host `github-kardel` -> key `id_ed25519_github_account` (khusus kardel)
  - Host `github.com` -> key `id_ed25519_github_account` (default)
  - Host `github` -> key `id_ed25519_babd_deploy` (khusus BABD)
- **Repo URL kardel**: `git@github-kardel:BAYU18/kardel.git`

## Konfigurasi Project (agents.json)
```json
{
  "id": "kardel",
  "name": "Kardel (Solana Sniper Bot)",
  "repo": "git@github-kardel:BAYU18/kardel.git",
  "branch": "main",
  "merge": "on_approval",
  "push": false,
  "test_command": "bash -c \"shopt -s globstar; node --test tests/**/*.test.js\""
}
```
- `default_project` = `kardel`

## Runtime
- **Node.js 20.20.2** (diinstall via NodeSource; sebelumnya Node 18 -> 48 test gagal karena ERR_REQUIRE_ESM)
- **npm 10.8.2**

## Cara Kerja
1. BABD clone repo ke `workspace/projects/kardel/`
2. Setiap task dapat worktree terisolasi: `workspace/worktrees/kardel/<run-id>/`
3. Agent bekerja di worktree, tidak mengganggu main checkout
4. Setelah selesai: commit di branch `babd/<run-id>`
5. Merge ke `main` hanya jika QA pass + deploy di-approve CEO

## Menjalankan Task
```bash
cd /home/serverbot/aidev
.venv/bin/babd run "<goal>" --project kardel
```

## Status Test
- **816/820 pass** dengan Node 20 + database ter-migrate
- 4 fail sisa: terkait ML/Python opsional (joblib/xgboost tidak terpasang)
  - `predict_momentum: HAS_ML=False` (butuh Python model)
  - `train_momentum: t is not defined` (butuh Python ML, 3 test)

## Catatan Penting
- `.env` di worktree perlu dibuat dari `.env.example` + `npm run migrate` (sudah dilakukan di project dir)
- Deploy key kardel READ-ONLY/WRITE tergantung setting Anda di GitHub. Untuk push, pastikan deploy key = read-write.
