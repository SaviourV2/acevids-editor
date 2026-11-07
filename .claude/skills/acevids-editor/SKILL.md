---
name: acevids-editor
description: Jalankan dan pakai server ACEVIDS (upload video besar, cek media, susun klip, render satu video) lewat HTTP API-nya. Gunakan saat user ingin mengunggah/mengecek video, memotong keheningan, memilih adegan, menggabungkan beberapa video jadi satu, atau mengotomatiskan alur ini dari Claude Code.
---

# ACEVIDS editor

Server FastAPI di `app/` (jalankan `bash scripts/run.sh`, default port 8080).
Semua operasi tersedia sebagai JSON API; UI di `/` hanya pembungkusnya.

## Alur standar

1. **Upload**: `python3 scripts/upload.py http://localhost:8080 FILE` (chunked,
   bisa dilanjutkan) atau `curl -T FILE "http://localhost:8080/api/uploads/direct?filename=FILE"`.
   Respons berisi `media.id`; analisis langsung berjalan.
2. **Tunggu cek**: `GET /api/media/{id}` sampai `status == "ready"`
   (`job.progress`/`job.message` saat berjalan). Hasil: `probe`, `analysis.silences`,
   `analysis.scenes.scenes[]`, `analysis.loudness`, `analysis.integrity`, `analysis.warnings`.
   `POST /api/media/{id}/analyze {"deep": true}` mengecek decode seluruh file.
3. **Susun**: `POST /api/projects {"name", "clips":[{"media_id","in","out","speed"}], "settings":{…}}`.
   `POST /api/media/{id}/autocut {"margin":0.2,"min_segment":0.5}` memberi
   `clips[]` tanpa keheningan (gaya auto-editor) yang bisa langsung dipakai.
   Settings: `preset` (youtube|hd720|reels|square|source), `transition`
   (none|fade|fadeblack|dissolve|wipeleft|wiperight|slideleft|slideright|circleopen),
   `transition_duration`, `remove_silence`, `silence_margin`, `normalize`, `lufs`,
   `title`, `title_seconds`.
4. **Rencana**: `GET /api/projects/{id}/plan` — dry run: frame, segmen, durasi, peringatan.
   Selalu tunjukkan ini ke user sebelum render panjang.
5. **Render**: `POST /api/projects/{id}/render` → job; poll `GET /api/projects/{id}`
   sampai `last_render.status == "done"` (atau `GET /api/jobs/{job_id}`).
   Hasil: `last_render.output_path`, `duration`, `video`, `loudness`;
   unduh di `GET /api/projects/{id}/output`.

## Transkrip

`POST /api/media/{id}/transcribe {"model":"small","language":"id"}` (bahasa `auto`
untuk deteksi) → poll `GET /api/media/{id}` sampai `transcript.status == "done"`.
Unduh `GET /api/media/{id}/transcript?format=json|srt|txt`. JSON-nya tingkat kata
dan langsung diterima skill `cut-silences`/`cut-mistakes`. Model pertama kali
diunduh dari huggingface.co; bila jaringan dibatasi, host `huggingface.co` dan
`us.aws.cdn.hf.co` harus diizinkan.

## Laporan ke user

Laporkan angka dari `last_render` (durasi, resolusi, fps, LUFS, keheningan yang
dibuang) dan peringatan dari `plan.warnings`/`analysis.warnings`. Jangan
mengklaim kualitas visual tanpa melihat frame: gunakan
`python3 .claude/skills/ffmpeg-skill/scripts/look.py OUTPUT --tiles 3x2` lalu lihat PNG-nya.

## Kapan memakai alat lain

- Cut lossless, caption, LUT, QC platform: skill **ffmpeg-skill**.
- Potong berdasarkan gerak/black frame atau ekspor ke Premiere/Resolve: **auto-editor**.
- Edit talking-head dengan transkrip kata: **cut-silences → cut-mistakes → edit-video**.
- Motion graphics: **remotion-*** (`npx skills add remotion-dev/skills`) atau **business-motion-film**.

## Uji

`python3 tests/smoke.py` membuat klip sintetis, menjalankan server di port acak,
upload, cek, render dua kali (xfade + concat copy) dan memverifikasi hasil.
