"""Konfigurasi ACEVIDS. Semua path bisa diganti lewat environment variable."""

import os
import pathlib

ROOT = pathlib.Path(__file__).resolve().parent.parent

# Folder data (upload, media, hasil render). Default: <repo>/data (di-gitignore).
DATA_DIR = pathlib.Path(os.environ.get("ACEVIDS_DATA", ROOT / "data")).resolve()
UPLOAD_DIR = DATA_DIR / "uploads"      # potongan upload yang belum selesai
MEDIA_DIR = DATA_DIR / "media"         # satu folder per media: source, proxy, thumbs, analysis
OUTPUT_DIR = DATA_DIR / "outputs"      # hasil render per project
DB_FILE = DATA_DIR / "db.json"

# Ukuran potongan (chunk) upload. 16 MB cukup untuk file puluhan GB.
CHUNK_SIZE = int(os.environ.get("ACEVIDS_CHUNK_MB", "16")) * 1024 * 1024

# Tinggi video proxy untuk preview di browser.
PROXY_HEIGHT = int(os.environ.get("ACEVIDS_PROXY_HEIGHT", "480"))

# Jumlah job (analisis / render) yang boleh jalan bersamaan.
MAX_WORKERS = int(os.environ.get("ACEVIDS_WORKERS", "2"))

# Berapa detik awal yang dicek saat "cek cepat" (0 = seluruh file).
QUICK_CHECK_SECONDS = int(os.environ.get("ACEVIDS_QUICK_CHECK_SECONDS", "60"))

# Batas jumlah thumbnail adegan (scene) yang dibuat per media.
MAX_SCENE_THUMBS = int(os.environ.get("ACEVIDS_MAX_SCENE_THUMBS", "80"))

FFMPEG = os.environ.get("ACEVIDS_FFMPEG", "ffmpeg")
FFPROBE = os.environ.get("ACEVIDS_FFPROBE", "ffprobe")

ALLOWED_EXTENSIONS = {
    ".mp4", ".mov", ".mkv", ".webm", ".avi", ".m4v", ".mts", ".m2ts", ".ts",
    ".mxf", ".wmv", ".flv", ".3gp", ".mpg", ".mpeg", ".ogv",
    ".mp3", ".wav", ".m4a", ".aac", ".flac", ".ogg", ".opus",
}


def ensure_dirs() -> None:
    for d in (DATA_DIR, UPLOAD_DIR, MEDIA_DIR, OUTPUT_DIR):
        d.mkdir(parents=True, exist_ok=True)
