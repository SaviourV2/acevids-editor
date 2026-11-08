#!/bin/bash
# Jalankan server ACEVIDS. PORT dan HOST bisa diganti lewat environment.
set -euo pipefail
cd "$(dirname "$0")/.."
exec python3 -m uvicorn app.main:app --host "${HOST:-0.0.0.0}" --port "${PORT:-8080}" "$@"
