#!/bin/bash
# Pasang semua yang dibutuhkan ACEVIDS di Ubuntu/Debian atau macOS (Homebrew).
# Dipakai juga oleh setup script environment cloud. Idempoten.
set -euo pipefail
cd "$(dirname "$0")/.."

if [ "$(uname -s)" = "Darwin" ]; then
  # macOS: pakai Homebrew (https://brew.sh)
  if ! command -v brew >/dev/null; then
    echo "Homebrew belum ada. Pasang dulu: /bin/bash -c \"\$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)\"" >&2
    exit 1
  fi
  command -v ffmpeg >/dev/null || brew install ffmpeg
  command -v sox >/dev/null || brew install sox
else
  if ! command -v ffmpeg >/dev/null; then
    sudo_cmd=""; [ "$(id -u)" -ne 0 ] && sudo_cmd="sudo"
    $sudo_cmd apt-get update -q
    $sudo_cmd apt-get install -y -q --no-install-recommends ffmpeg
  fi
  if ! command -v sox >/dev/null; then
    sudo_cmd=""; [ "$(id -u)" -ne 0 ] && sudo_cmd="sudo"
    $sudo_cmd apt-get update -q
    $sudo_cmd apt-get install -y -q --no-install-recommends sox libsox-fmt-mp3
  fi
fi

# Di luar virtualenv (mis. Python Homebrew/sistem) pip butuh --break-system-packages.
PIP_FLAGS=""
python3 -c "import sys; sys.exit(0 if sys.prefix != sys.base_prefix else 1)" || PIP_FLAGS="--break-system-packages"
python3 -m pip install $PIP_FLAGS -q -r requirements.txt

echo "ffmpeg : $(ffmpeg -version | head -1)"
echo "sox    : $(sox --version | head -1)"
python3 -c "import fastapi, scenedetect, cv2; print('python : fastapi', fastapi.__version__, '/ scenedetect', scenedetect.__version__, '/ cv2', cv2.__version__)"
echo "auto-editor : $(auto-editor --version 2>/dev/null | tail -1 || echo 'tidak terpasang')"
echo "Selesai. Jalankan: bash scripts/run.sh"
