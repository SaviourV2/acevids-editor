# Alur kerja ACEVIDS: upload → cek → susun → satu video

## 1. Upload besar

- **Chunked & resumable:** `POST /api/uploads/init {filename,size}` membuat file
  sparse seukuran penuh; `PUT /api/uploads/{id}/chunks/{n}` menulis pada offset
  `n × chunk_size` (streaming, tidak menahan seluruh chunk di RAM). Chunk bisa
  dikirim paralel dan diulang. `GET /api/uploads?filename&size` menemukan upload
  yang belum selesai; `POST …/complete` memverifikasi semua chunk, memindahkan
  file ke `data/media/<id>/source.<ext>`, dan menjadwalkan job cek.
- **Direct:** `PUT /api/uploads/direct?filename=…` menerima body streaming
  (cocok untuk `curl -T`).
- Ekstensi diperiksa (`config.ALLOWED_EXTENSIONS`); ruang disk dicek saat init.

## 2. Cek (job `analyze`, `app/analysis.py`)

| Tahap | Alat | Hasil |
|---|---|---|
| Metadata | `ffprobe -show_format -show_streams` | durasi, codec, resolusi, fps, VFR/HDR/rotasi, audio |
| Decode | `ffmpeg -xerror -t 60 -f null -` (penuh dengan *Cek penuh*) | `integrity.ok`, daftar error |
| Contact sheet | 12 frame via seek cepat + `tile=4x3` | `thumbs/sheet.jpg`, `poster.jpg` |
| Proxy | `scale=-2:480, libx264 veryfast crf 28, aac 96k, faststart` | `proxy.mp4` untuk `<video>` (byte-range) |
| Keheningan | `silencedetect=noise=-35dB:d=0.6` pada proxy | `silences[{start,end,duration}]` |
| Loudness | `ebur128=peak=true` | LUFS terintegrasi, LRA, true peak |
| Adegan | PySceneDetect `ContentDetector` pada proxy (fallback `scene` ffmpeg) | `scenes[]` + thumbnail per adegan |

Peringatan otomatis: HDR, VFR, rotasi, error decode, tidak ada audio.

## 2b. Transkrip (job `transcribe`, `app/transcribe.py`)

`POST /api/media/{id}/transcribe {"model":"small","language":"id"}` menjalankan
faster-whisper (CPU, int8, `word_timestamps=True`, `vad_filter=True`) pada proxy.
Audio di-decode oleh ffmpeg ke float32 16 kHz lalu dioper sebagai array.
Keluaran di folder media: `transcript.json` (bentuk herk-edit-kit:
`{"words":[{"text","start","end","type":"word"}], "audio_duration_secs", "segments"}`),
`transcript.srt`, `transcript.txt`; diunduh lewat
`GET /api/media/{id}/transcript?format=json|srt|txt`. Model diunduh sekali ke
`ACEVIDS_MODELS` (default `data/models`).

## 3. Susun (project)

`projects[].clips[] = {media_id, in, out, speed, remove_silence?, label}` dan
`settings = {preset, transition, transition_duration, remove_silence,
silence_margin, normalize, lufs, title, title_seconds}`.

- **Potong otomatis** (`POST /api/media/{id}/autocut`): komplemen keheningan
  dengan margin (default 0.2 s) dan segmen minimum 0.5 s — semantik
  `--margin` auto-editor — menghasilkan banyak klip sekaligus.
- `GET /api/projects/{id}/plan` adalah *dry run*: frame, segmen per klip,
  durasi perkiraan, peringatan (mis. transisi dipendekkan karena klip pendek).

## 4. Render (job `render`, `app/render.py`)

**Tahap 1 — perantara per klip** (`-ss IN -t DUR -i src` per segmen, lalu
`scale…pad…setsar=1,fps,format=yuv420p` + `aresample 48k stereo`, `concat`).
Sumber tanpa audio diberi `anullsrc`; klip audio saja diberi layar hitam.
Kecepatan memakai `setpts` + rantai `atempo`. Encode `libx264 crf 18`.

**Tahap 2 — gabung**
- Tanpa transisi: concat demuxer, `-c:v copy`; audio di-`loudnorm` bila
  normalisasi aktif. Judul (`drawtext`) memaksa re-encode video.
- Dengan transisi: rantai `xfade=transition=…:offset=Σdur−T` dan
  `acrossfade=d=T`, lalu `loudnorm`/`drawtext`, encode `libx264 crf 20`.

Hasil: `data/outputs/<project>/final.mp4`, diprobe dan diukur loudness-nya;
ringkasan disimpan di `project.last_render`. Progres dibaca dari
`-progress pipe:1`.

## 5. Dari sini ke alat lain

- **herk-edit-kit**: `node .claude/skills/cut-silences/scripts/cut-silences.mjs transcript.json --video source.mp4 --out-dir work`
  memakai `transcript.json` dari ACEVIDS langsung (sudah diuji).
- **ffmpeg-skill**: `python3 .claude/skills/ffmpeg-skill/scripts/check.py final.mp4 --platform youtube`
  untuk QC spesifikasi platform; `render.py --export-timeline edit.fcpxml`
  bila ingin membuka di Premiere/Resolve.
- **auto-editor**: `auto-editor source.mp4 --edit motion:0.02 --export premiere`
  untuk potongan berbasis gerak atau ekspor ke NLE.
- **OpenChatCut / OpenStoryline**: unggah sumber yang sama, pakai daftar adegan
  & keheningan dari `GET /api/media/{id}` sebagai masukan agen.
- **Remotion / business-motion-film**: render opening/lower-third jadi MP4, upload
  ke ACEVIDS, letakkan di timeline.

## Variabel lingkungan

| Nama | Default | Arti |
|---|---|---|
| `ACEVIDS_DATA` | `./data` | folder upload/media/output |
| `ACEVIDS_CHUNK_MB` | 16 | ukuran chunk upload |
| `ACEVIDS_PROXY_HEIGHT` | 480 | tinggi proxy |
| `ACEVIDS_WORKERS` | 2 | job paralel |
| `ACEVIDS_QUICK_CHECK_SECONDS` | 60 | durasi cek decode cepat (0 = seluruh file) |
| `ACEVIDS_MAX_SCENE_THUMBS` | 80 | batas thumbnail adegan |
| `ACEVIDS_MODELS` | `./data/models` | cache model Whisper |
| `ACEVIDS_WHISPER_MODEL` | `base` | model Whisper default |
