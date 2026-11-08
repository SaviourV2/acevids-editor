# Hasil pelajaran 9 repo rujukan

Dipelajari pada 7 Nov 2026 dari clone terbaru masing-masing repo. Untuk tiap repo:
apa itu, lisensi, cara pasang, kekuatan/kelemahan, dan bagaimana ACEVIDS memakainya.

---

## 1. kajisho5/ffmpeg-skill — "beri agen koding sebuah editor video"

- **Apa:** Agent Skill (SKILL.md) + **42 alat Python stdlib** yang membungkus
  ffmpeg/ffprobe: `probe`, `cut` (lossless/smart), `join` (xfade), `silence`,
  `fit` (aspek/durasi), `caption` (SRT/karaoke), `overlay`, `graphics`,
  `color` (HDR→SDR, LUT), `audio`, `loudness`, `sync`, `multicam`, `export`
  (preset platform), `check` (QC), `look` (contact sheet), `render` (project.json
  deklaratif, bisa ekspor FCPXML), `batch`, dll. Ada MCP server dari kontrak yang
  sama. Versi 3.2.3, MIT.
- **Pasang:** `npx ffmpeg-skill` (menyalin ke `~/.claude/skills`), atau pakai
  salinan di `.claude/skills/ffmpeg-skill` repo ini. Butuh FFmpeg 6.1+ dan Python 3.10+.
- **Pola yang diambil:** *probe dulu → edit lossless bila bisa → dry-run →
  check → verify → look.* Project format `render.py` (clips in/out, transition,
  silence, captions, loudness, export) menjadi acuan model project ACEVIDS.
- **Catatan:** Dirancang sebagai "tangan" (eksekusi), bukan "otak" (keputusan).
  Transkripsi opsional lewat faster-whisper/parakeet.

## 2. nateherkai/herk-edit-kit — kit edit talking-head berbasis HyperFrames

- **Apa:** 15 skill untuk Codex/Claude Code: `edit-video` (pipeline utama),
  `cut-silences` (Agent 1, transkrip kata → EDL → ffmpeg), `cut-mistakes`
  (Agent 2, stutter/retake, review-gated), `video-storytelling`,
  `short-form-edit` (reel 9:16 dengan validator caption/footage), `motion-showreel`,
  `style-library` (406 kartu motion graphics), `hyperframes*` (render HTML+GSAP).
  MIT. Repo 790 MB karena contoh video.
- **Pasang:** `git clone … && npm ci && npm run setup`; butuh Node 22+, ffmpeg,
  Chrome/Chromium. Transkripsi default ElevenLabs Scribe (API key), bisa Whisper.
- **Diambil ke ACEVIDS:** 5 skill editing (tanpa HyperFrames/style-library)
  di `.claude/skills/`, plus `third_party/herk-edit-kit/` (playbook, script
  transkripsi/EDL/beat-sync). Script-nya murni Node stdlib.
- **Catatan:** Skill-nya mengharapkan **transkrip tingkat kata** (JSON `words[]`).
  Tanpa transkrip, pakai deteksi keheningan ACEVIDS / auto-editor.

## 3. 0xsline/OpenChatCut — editor video agen-native, local-first

- **Apa:** Alternatif ChatCut open source (AGPL-3.0): Electron + React 19 +
  Remotion 4, timeline multitrack nyata, transkrip tingkat kata, caption,
  motion graphics, efek WebGL, LUT, ekspor MP4/FCPXML. Agen (built-in, Codex,
  Claude Code) mengedit lewat **MCP** (`http://localhost:5199/api/external-mcp/mcp`).
- **Pasang:** Node ≥ 24.22 (`.nvmrc`), `npm install`, `npm run dev`; ada edisi
  desktop (Pro). Skill agen: `npx skills add 0xsline/OpenChatCut --skill openchatcut`.
- **Mengapa tidak di-vendor:** AGPL dan sangat besar (155 MB, butuh GUI). ACEVIDS
  bisa menjadi *staging* material: hasil cek (adegan, keheningan) dipakai agen
  saat menyusun timeline di OpenChatCut.

## 4. remotion-dev/skills — skill resmi Remotion

- **Apa:** 13 skill (`remotion-best-practices` sebagai router, `-create`,
  `-markup`, `-render`, `-captions`, `-maps`, `-multimedia`, `-studio`, …) untuk
  membuat video programatik dengan React. Versi 4.0.541.
- **Pasang:** `npx skills add remotion-dev/skills` (menulis ke `.claude/skills`).
  Tidak di-vendor karena repo tidak menyertakan berkas LICENSE terpisah
  (ikut lisensi Remotion: gratis untuk individu/≤3 orang, perusahaan perlu lisensi).
- **Pemakaian:** judul, lower-third, motion graphics yang di-render jadi klip
  (`npx remotion render`) lalu diunggah ke ACEVIDS sebagai media biasa.

## 5. WyattBlue/auto-editor — potong otomatis bagian mati

- **Apa:** CLI (sekarang ditulis Nim, dirilis biner; versi 29.3.1) yang menandai
  tiap momen *aktif/tidak aktif* lewat `--edit audio:threshold` / `motion` /
  `blackdetect`, lalu `cut`/`speed`/`zoom`. `--margin 0.2s` menjaga tempo.
  Ekspor ke Premiere/Resolve/FCP/ShotCut. Unlicense (public domain).
- **Pasang:** `pip install auto-editor` (wheel mengunduh biner dari GitHub
  Releases) — sudah ada di `requirements.txt`. Skill: `npx skills add WyattBlue/auto-editor`
  atau salinan di `.claude/skills/auto-editor*`.
- **Diambil:** konsep *margin* + *min segment* diimplementasikan natif di
  `app/render.py::keep_segments` (tanpa dependensi) untuk "Potong otomatis" dan
  opsi "buang keheningan"; auto-editor CLI tetap tersedia untuk kasus lanjutan
  (motion, blackdetect, ekspor timeline).

## 6. FireRedTeam/FireRed-OpenStoryline — agen cerita untuk vlog/iklan

- **Apa:** Agen LangChain + MCP (Apache-2.0): memahami klip (VLM), memecah shot
  (TransNetV2), rough cut ASR (FunASR), menyusun naskah & voiceover, memilih BGM
  beat-sync, merender dengan moviepy. Web UI + `agent_fastapi.py`. Butuh API LLM/VLM
  (OpenAI-compatible) dan model lokal (torch, sentence-transformers, faiss).
- **Pasang:** Python ≥3.11, `requirements.txt` berat (torch/torchaudio),
  `download.sh` untuk bobot model; `config.toml` isi `[llm]`/`[vlm]`.
- **Diambil:** skill `openstoryline-install` & `openstoryline-use` di-vendor.
  Tidak dijalankan di server ACEVIDS (butuh GPU/LLM); dokumen ini mencatat cara
  mengirim media hasil cek ke sana.

## 7. echris6/motion-video-kit — iklan motion untuk bisnis nyata

- **Apa:** Satu skill `business-motion-film` (MIT): grammar motion dari 28 film
  launch, loop kritik independen "Gauntlet", quality bar terukur (frozen time,
  loudness, kontras), aturan audio, pola Three.js, template lab komponen,
  script ukur (`frozen-time`, `loudness`, `contact-sheet`, `backtime-music`).
- **Pasang:** `cp -r business-motion-film .claude/skills/` — sudah dilakukan.
- **Pemakaian:** untuk klip iklan/opening yang di-render (HyperFrames/Remotion)
  lalu masuk timeline ACEVIDS; script loudness-nya memakai `ebur128` sama
  seperti pengukuran di server ini.

## 8. mifi/editly — NLE deklaratif Node.js

- **Apa:** Buat video dari spec JSON5 (klip, gambar, judul, transisi GL,
  musik, ducking) secara streaming; versi 0.15.0-rc.1, MIT.
- **Pasang:** `npm i -g editly`; di Linux butuh `headless-gl` (libgl, xvfb) dan
  `canvas` — rapuh di container tanpa GPU, jadi **tidak dipasang** di setup.
- **Diambil:** model spec klip (`cutFrom`/`cutTo`, `transition`, `audioFilePath`)
  mirip dengan project ACEVIDS; render ACEVIDS memakai `xfade` ffmpeg sebagai
  pengganti transisi GL.

## 9. Breakthrough/PySceneDetect — deteksi potongan adegan

- **Apa:** Pustaka + CLI `scenedetect` (BSD-3): `ContentDetector` (potongan
  cepat), `AdaptiveDetector` (kamera bergerak), `ThresholdDetector` (fade).
  Perintah `split-video`, `save-images`, `list-scenes`. Versi 0.7.2.
- **Pasang:** `pip install scenedetect opencv-python-headless` — ada di
  `requirements.txt`.
- **Dipakai langsung:** `app/ffmpeg_tools.py::detect_scenes` memanggil
  `detect(proxy, ContentDetector(threshold=27))` pada proxy 480p (lebih cepat,
  timing sama), fallback ke filter `select='gt(scene,0.4)'` ffmpeg bila tidak terpasang.

---

## Peta gabungan: siapa mengerjakan apa

| Kebutuhan | Alat |
|---|---|
| Upload besar, cek, proxy, timeline, render satu file | **ACEVIDS app** |
| Operasi ffmpeg presisi oleh agen (cut lossless, caption, LUT, QC) | ffmpeg-skill |
| Potong keheningan/gerak otomatis, ekspor ke NLE | auto-editor (+ `keep_segments` natif) |
| Deteksi adegan | PySceneDetect |
| Edit talking-head dari transkrip (silence → mistakes → story) | herk-edit-kit skills |
| Motion graphics / judul / lower third | Remotion skills, business-motion-film |
| Editor GUI agen-native dengan timeline nyata | OpenChatCut (MCP) |
| Agen "buatkan vlog dari folder klip" dengan naskah & VO | FireRed-OpenStoryline |
| Render deklaratif Node dengan transisi GL | editly (opsional) |
