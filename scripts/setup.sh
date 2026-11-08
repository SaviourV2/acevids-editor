#!/bin/bash
# Pasang semua yang dibutuhkan ACEVIDS di Ubuntu/Debian (dipakai juga oleh setup
# script environment cloud). Idempoten.
set -euo pipefail
cd "$(dirname "$0")/.."

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

PIP_FLAGS=""
python3 -c "import sys; sys.exit(0 if sys.prefix != sys.base_prefix else 1)" || PIP_FLAGS="--break-system-packages"
pip3 install $PIP_FLAGS -q -r requirements.txt

echo "ffmpeg : $(ffmpeg -version | head -1)"
echo "sox    : $(sox --version | head -1)"
python3 -c "import fastapi, scenedetect, cv2; print('python : fastapi', fastapi.__version__, '/ scenedetect', scenedetect.__version__, '/ cv2', cv2.__version__)"
echo "auto-editor : $(auto-editor --version 2>/dev/null | tail -1 || echo 'tidak terpasang')"
echo "Selesai. Jalankan: bash scripts/run.sh"
