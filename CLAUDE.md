# ACEVIDS

Repo trial editor video. Server upload/cek/render ada di `app/` (FastAPI),
dokumentasi di `docs/`, skill agen di `.claude/skills/` (lihat `.claude/skills/README.md`).

- Jalankan server: `bash scripts/run.sh` (port 8080). Uji: `python3 tests/smoke.py`.
- Jangan pernah menulis ke `data/` secara manual; itu folder runtime yang di-gitignore.
- Perubahan pada pipeline render harus lulus `tests/smoke.py` sebelum di-commit.
- Berkas di `.claude/skills/*` selain `acevids-editor` adalah vendor dari repo lain
  (lihat `THIRD_PARTY_NOTICES.md`); perbarui dengan menyalin ulang, bukan mengedit.
