# Panduan: upload file dan edit video dengan ACEVIDS

## 1. Pasang dan jalankan

Butuh Python 3.10+, ffmpeg, dan koneksi ke huggingface.co (hanya untuk unduh
model Whisper pertama kali).

### macOS (MacBook)

1. Buka **Terminal** (Spotlight → ketik Terminal).
2. Pasang Homebrew bila belum ada:
   ```bash
   /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
   ```
3. Pasang alat dasar:
   ```bash
   brew install git python ffmpeg sox
   ```
4. Clone repo, buat virtualenv, jalankan setup:
   ```bash
   git clone https://github.com/SaviourV2/acevids-editor
   cd acevids-editor
   python3 -m venv .venv && source .venv/bin/activate
   bash scripts/setup.sh
   bash scripts/run.sh
   ```
5. Buka http://localhost:8080 di Safari/Chrome. Hentikan server dengan Ctrl+C.
   Lain kali cukup `cd acevids-editor && source .venv/bin/activate && bash scripts/run.sh`.

Apple Silicon (M1–M4) dan Intel sama-sama didukung; faster-whisper memakai CPU.
Bila macOS memblokir biner `auto-editor` ("tidak dapat diverifikasi"), jalankan
`xattr -d com.apple.quarantine "$(which auto-editor)"` sekali.

### Linux (Ubuntu/Debian)

```bash
git clone https://github.com/SaviourV2/acevids-editor
cd acevids-editor
bash scripts/setup.sh      # ffmpeg, sox, fastapi, scenedetect, faster-whisper, auto-editor
bash scripts/run.sh        # server di http://localhost:8080
```

Ganti port/host bila perlu: `PORT=9000 HOST=127.0.0.1 bash scripts/run.sh`.
Semua data (upload, proxy, hasil) masuk ke folder `data/`; pindahkan dengan
`ACEVIDS_DATA=/disk/besar/acevids`.

> Server tidak punya login. Jalankan di jaringan lokal atau di balik reverse
> proxy dengan autentikasi bila dibuka ke internet.

## 2. Upload video besar

**Lewat browser** (`http://localhost:8080`, panel kiri "1. Media"):
tarik file ke kotak upload atau klik untuk memilih. Bisa banyak file sekaligus.
File dipotong per 16 MB, tiga potongan dikirim bersamaan. Kalau koneksi putus,
pilih ulang file yang sama: potongan yang sudah diterima tidak dikirim lagi.

**Lewat terminal** (untuk file puluhan GB atau dari server lain):

```bash
python3 scripts/upload.py http://localhost:8080 /path/video1.mp4 /path/video2.mov
```

Juga bisa dilanjutkan bila putus: jalankan ulang perintah yang sama.
Satu permintaan tanpa chunk (cocok untuk skrip):

```bash
curl -T video.mp4 "http://localhost:8080/api/uploads/direct?filename=video.mp4"
```

Format yang diterima: mp4, mov, mkv, webm, avi, m4v, mts, m2ts, ts, mxf, wmv,
flv, 3gp, mpg, ogv, serta audio mp3, wav, m4a, aac, flac, ogg, opus.

## 3. Cek otomatis

Begitu upload selesai, status media berubah "antre" → "mengecek" → "siap".
Untuk file 1 jam 1080p, proses ini beberapa menit (pembuatan proxy yang paling
lama). Klik media di panel kiri untuk melihat:

- **Decode OK / bermasalah**: 60 detik pertama dicek; tombol **Cek penuh**
  men-decode seluruh file untuk memastikan tidak ada bagian rusak.
- **Metadata**: durasi, ukuran, codec, resolusi, fps, pixel format, audio,
  loudness (LUFS). Peringatan muncul bila sumber HDR, VFR, atau punya rotasi.
- **Contact sheet**: 12 frame sepanjang video.
- **Adegan**: thumbnail tiap potongan adegan (PySceneDetect). Klik thumbnail
  untuk mengisi IN/OUT; tombol **+** langsung memasukkan adegan ke timeline.
- **Keheningan**: daftar jeda hening; klik untuk melompat ke posisi itu.

Pemutar video memakai proxy 480p, jadi scrubbing tetap ringan walau sumber 4K.

## 4. Transkrip (opsional)

Di blok **Transkrip (Whisper lokal)** pilih model dan bahasa lalu klik
**Transkrip**. Untuk bahasa Indonesia pakai model `small`; `base` lebih cepat
tetapi kurang rapi. Model pertama kali diunduh (base 140 MB, small 460 MB).
Hasil: klik kalimat untuk melompat, unduh **SRT** (subtitle), **TXT**, atau
**JSON kata** (dipakai skill `cut-silences` / `cut-mistakes`).

Dari terminal:

```bash
curl -X POST http://localhost:8080/api/media/MEDIA_ID/transcribe \
  -H 'Content-Type: application/json' -d '{"model":"small","language":"id"}'
curl -o transkrip.srt "http://localhost:8080/api/media/MEDIA_ID/transcript?format=srt"
```

## 5. Susun timeline

Panel kanan "3. Susun & render". Satu project = satu video hasil.

1. Pilih media di kiri, putar, tekan **IN = posisi** dan **OUT = posisi** pada
   detik yang diinginkan (atau ketik angkanya), lalu **+ Tambah ke timeline**.
   **+ Seluruh file** memasukkan klip utuh.
2. Ulangi untuk media lain. Klip dari file berbeda boleh dicampur.
3. **⚡ Potong otomatis**: memecah rentang IN–OUT menjadi beberapa klip tanpa
   bagian hening (gaya auto-editor). Atur **Margin keheningan** dulu bila perlu
   (0.2 s = pas untuk bicara; perbesar kalau potongan terasa terburu-buru).
4. Di daftar klip: ubah urutan dengan ↑ ↓, hapus dengan ✕, edit IN/OUT, dan
   atur kecepatan (×1.5 untuk mempercepat, ×0.5 slow motion).

## 6. Pengaturan output

| Pengaturan | Pilihan |
|---|---|
| Format | YouTube 1920×1080, HD 1280×720, Reels/Shorts 1080×1920, Persegi, Ikut klip pertama |
| Transisi | Potong langsung, Fade, Fade lewat hitam, Dissolve, Wipe, Slide, Circle |
| Durasi transisi | 0.1–3 detik |
| Buang keheningan di dalam tiap klip | hapus jeda hening tanpa memecah klip |
| Normalisasi loudness | target LUFS (−14 untuk YouTube/Reels, −16 podcast) |
| Judul di awal | teks di tengah layar selama N detik |

Klip dengan rasio berbeda otomatis di-letterbox (pad hitam) ke format yang
dipilih. Klip tanpa audio diberi audio sunyi; audio tanpa gambar jadi layar hitam.

## 7. Render dan unduh

Klik **Lihat rencana** untuk melihat frame, jumlah segmen per klip, perkiraan
durasi, dan peringatan sebelum render panjang. Lalu **▶ Render jadi satu video**.
Progres tampil per klip; tombol **Batal** menghentikan. Setelah selesai:
ringkasan (durasi, resolusi, fps, ukuran, LUFS), pemutar hasil, dan
**⬇ Unduh video**. File juga ada di `data/outputs/<project>/final.mp4`.

Perkiraan waktu di CPU 4 core: sekitar 1–2× durasi video untuk 1080p; render
tanpa transisi dan tanpa judul lebih cepat karena video hanya disalin saat digabung.

## 8. Alur yang disarankan untuk rekaman bicara (talking-head)

1. Upload rekaman mentah, tunggu "siap".
2. Transkrip dengan model `small`, bahasa Indonesia.
3. **Potong otomatis** dengan margin 0.2–0.3 s untuk membuang jeda.
4. Tambahkan intro/outro atau B-roll sebagai klip lain, pilih transisi Fade 0.3 s.
5. Format YouTube, normalisasi −14 LUFS, render.
6. Unduh SRT dari transkrip untuk diunggah sebagai subtitle di YouTube.

## 9. Memakai dari Claude Code

Buka repo ini di Claude Code dan minta, misalnya: "upload video di
/path/rekaman.mp4, buang keheningan, render ke Reels". Skill `acevids-editor`
tahu API-nya; skill `ffmpeg-skill`, `auto-editor`, `cut-silences`,
`cut-mistakes`, dan lainnya tersedia untuk langkah lanjutan.

## 10. Masalah umum

- **Upload gagal "ruang disk tidak cukup"**: kosongkan `data/uploads` atau
  arahkan `ACEVIDS_DATA` ke disk lain.
- **Status "gagal" setelah upload**: lihat pesan error di panel tengah; biasanya
  file bukan media yang valid. Tombol **Cek penuh** mengulang pengecekan.
- **Transkripsi gagal memuat model**: pastikan huggingface.co dan
  us.aws.cdn.hf.co bisa diakses, atau salin folder `data/models` dari mesin lain.
- **Render gagal**: pesan ffmpeg tampil di panel kanan; `GET /api/jobs` berisi
  log lengkapnya. Sumber HDR sebaiknya dikonversi dulu dengan
  `python3 .claude/skills/ffmpeg-skill/scripts/color.py in.mov --to-sdr`.
- **Server dimulai ulang saat job berjalan**: job ditandai gagal; ulangi dari UI.
