#!/usr/bin/env python3
"""Upload file video besar ke server ACEVIDS dari terminal (chunked + bisa dilanjutkan).

Pemakaian:
    python3 scripts/upload.py http://localhost:8080 /path/video.mp4 [lebih banyak file...]

Bila koneksi putus, jalankan lagi perintah yang sama: chunk yang sudah diterima
server tidak dikirim ulang. Hanya memakai pustaka standar Python.
"""

import json
import os
import sys
import time
import urllib.error
import urllib.request


def req(url: str, method: str = "GET", data: bytes = None, headers: dict = None):
    r = urllib.request.Request(url, data=data, method=method, headers=headers or {})
    with urllib.request.urlopen(r, timeout=600) as resp:
        body = resp.read()
        return json.loads(body) if body else {}


def upload(base: str, path: str) -> dict:
    size = os.path.getsize(path)
    name = os.path.basename(path)
    init = req(f"{base}/api/uploads/init", "POST",
               json.dumps({"filename": name, "size": size}).encode(),
               {"Content-Type": "application/json"})
    uid, chunk, total = init["id"], init["chunk_size"], init["total_chunks"]
    received = set(init.get("received", []))
    print(f"{name}: {size / 1e6:.1f} MB, {total} chunk x {chunk // (1024 * 1024)} MB, "
          f"{len(received)} sudah ada di server")
    t0 = time.time()
    sent = 0
    with open(path, "rb") as f:
        for i in range(total):
            if i in received:
                continue
            f.seek(i * chunk)
            data = f.read(chunk)
            for attempt in range(1, 7):
                try:
                    req(f"{base}/api/uploads/{uid}/chunks/{i}", "PUT", data,
                        {"Content-Type": "application/octet-stream"})
                    break
                except (urllib.error.URLError, urllib.error.HTTPError, OSError) as exc:
                    if attempt == 6:
                        raise
                    print(f"  chunk {i} gagal ({exc}); coba lagi dalam {attempt}s", file=sys.stderr)
                    time.sleep(attempt)
            sent += len(data)
            done = len(received) + (i + 1 - len([r for r in received if r <= i]))
            speed = sent / max(time.time() - t0, 0.01)
            pct = 100.0 * (i + 1) / total
            print(f"\r  {pct:5.1f} %  {speed / 1e6:6.1f} MB/s", end="", flush=True)
    print()
    media = req(f"{base}/api/uploads/{uid}/complete", "POST", b"", {"Content-Type": "application/json"})
    print(f"  selesai -> media {media['id']} (pengecekan berjalan di server)")
    return media


def main(argv):
    if len(argv) < 3:
        print(__doc__)
        return 2
    base = argv[1].rstrip("/")
    for p in argv[2:]:
        upload(base, p)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
