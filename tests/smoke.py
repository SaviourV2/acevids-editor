#!/usr/bin/env python3
"""Uji ujung-ke-ujung ACEVIDS tanpa dependensi tambahan.

1. Membuat 3 klip sintetis dengan ffmpeg (satu tanpa audio).
2. Menjalankan server uvicorn pada port acak dengan folder data sementara.
3. Upload chunked (chunk kecil supaya banyak potongan), menunggu analisis.
4. Membuat project 3 klip (transisi fade, buang keheningan, judul, normalisasi)
   lalu render dan memverifikasi hasil dengan ffprobe.

Jalankan:  python3 tests/smoke.py
"""

import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "scripts"))
from upload import upload  # noqa: E402


def req(url, method="GET", data=None):
    body = json.dumps(data).encode() if data is not None else None
    r = urllib.request.Request(url, data=body, method=method, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(r, timeout=120) as resp:
        raw = resp.read()
        return json.loads(raw) if raw else {}


def make_clips(d):
    cmds = [
        ["-f", "lavfi", "-i", "testsrc2=size=640x360:rate=25:duration=12", "-f", "lavfi", "-i", "sine=frequency=440:duration=12",
         "-filter_complex", "[1:a]volume='if(lt(mod(t,4),2),1,0)':eval=frame[a]", "-map", "0:v", "-map", "[a]",
         "-c:v", "libx264", "-preset", "veryfast", "-c:a", "aac", os.path.join(d, "a.mp4")],
        ["-f", "lavfi", "-i", "smptebars=size=1280x720:rate=30:duration=6", "-f", "lavfi", "-i", "anoisesrc=d=6:c=pink:a=0.3",
         "-c:v", "libx264", "-preset", "veryfast", "-c:a", "aac", os.path.join(d, "b.mp4")],
        ["-f", "lavfi", "-i", "color=c=blue:size=320x240:rate=25:duration=4", "-c:v", "libx264", "-preset", "veryfast",
         os.path.join(d, "noaudio.mp4")],
    ]
    for c in cmds:
        subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y"] + c, check=True)


def free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


def wait_for(fn, timeout, what):
    t0 = time.time()
    while time.time() - t0 < timeout:
        r = fn()
        if r:
            return r
        time.sleep(1)
    raise SystemExit(f"timeout menunggu {what}")


def main():
    tmp = tempfile.mkdtemp(prefix="acevids-smoke-")
    clips = os.path.join(tmp, "clips")
    os.makedirs(clips)
    make_clips(clips)
    port = free_port()
    base = f"http://127.0.0.1:{port}"
    env = dict(os.environ, ACEVIDS_DATA=os.path.join(tmp, "data"), ACEVIDS_CHUNK_MB="1",
               ACEVIDS_QUICK_CHECK_SECONDS="5")
    server = subprocess.Popen([sys.executable, "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1",
                               "--port", str(port), "--log-level", "warning"], cwd=ROOT, env=env)
    try:
        wait_for(lambda: _ok(base), 30, "server")
        print("server OK:", req(f"{base}/api/health")["ffmpeg"])
        ids = []
        for n in ("a.mp4", "b.mp4", "noaudio.mp4"):
            ids.append(upload(base, os.path.join(clips, n))["id"])
        # upload langsung (curl-style)
        with open(os.path.join(clips, "b.mp4"), "rb") as f:
            r = urllib.request.Request(f"{base}/api/uploads/direct?filename=b-direct.mp4", data=f.read(), method="PUT")
            direct = json.loads(urllib.request.urlopen(r).read())
        ids.append(direct["id"])

        def all_ready():
            ms = {m["id"]: m for m in req(f"{base}/api/media")}
            bad = [m for m in ms.values() if m["status"] == "failed"]
            if bad:
                raise SystemExit("analisis gagal: " + json.dumps(bad[0].get("error")))
            return all(ms[i]["status"] == "ready" for i in ids) and ms
        media = wait_for(all_ready, 300, "analisis media")
        a = media[ids[0]]
        print("a.mp4:", a["probe"]["video"]["width"], "x", a["probe"]["video"]["height"],
              "| keheningan:", len(a["analysis"]["silences"]), "| adegan:", len(a["analysis"]["scenes"]["scenes"]),
              "| engine:", a["analysis"]["scenes"]["engine"], "| loudness:", a["analysis"]["loudness"])
        assert len(a["analysis"]["silences"]) >= 2, "keheningan pada a.mp4 seharusnya terdeteksi"
        assert a["analysis"]["integrity"]["ok"], "cek decode seharusnya OK"
        assert os.path.exists(a["proxy_path"]), "proxy harus ada"
        assert media[ids[2]]["probe"]["has_audio"] is False

        auto = req(f"{base}/api/media/{ids[0]}/autocut", "POST", {"margin": 0.1})
        print("autocut a.mp4:", len(auto["clips"]), "klip, buang", auto["removed_seconds"], "s")
        assert len(auto["clips"]) >= 2

        prj = req(f"{base}/api/projects", "POST", {"name": "Smoke", "clips": [
            {"media_id": ids[0], "in": 0, "out": 8, "label": "a"},
            {"media_id": ids[1], "in": 1, "out": 5, "label": "b", "speed": 1.5},
            {"media_id": ids[2], "label": "noaudio"},
        ], "settings": {"preset": "hd720", "transition": "fade", "transition_duration": 0.5,
                        "remove_silence": True, "silence_margin": 0.1, "normalize": True, "lufs": -16,
                        "title": "Smoke: test 100%", "title_seconds": 2}})
        plan = req(f"{base}/api/projects/{prj['id']}/plan")
        print("plan:", plan["frame"], "durasi ±", plan["estimated_duration"], "s, warnings:", plan["warnings"])
        assert len(plan["items"][0]["segments"]) >= 2, "klip a harus terpecah oleh penghapusan keheningan"
        job = req(f"{base}/api/projects/{prj['id']}/render", "POST")

        def rendered(job_id):
            p = req(f"{base}/api/projects/{prj['id']}")
            lr = p.get("last_render") or {}
            if lr.get("status") == "failed":
                raise SystemExit("render gagal: " + lr.get("error", "?"))
            if p.get("job"):
                print(f"  render {p['job']['progress'] * 100:5.1f} % {p['job']['message']}")
            return lr if lr.get("status") == "done" and lr.get("job_id") == job_id else None
        lr = wait_for(lambda: rendered(job["id"]), 600, "render")
        print("hasil:", lr["duration"], "s", lr["video"]["width"], "x", lr["video"]["height"], lr["video"]["fps"], "fps",
              "| loudness:", lr["loudness"], "| keheningan dibuang:", lr["removed_silence"])
        assert lr["video"]["width"] == 1280 and lr["video"]["height"] == 720
        assert abs(lr["duration"] - plan["estimated_duration"]) < 1.0, "durasi hasil jauh dari rencana"
        assert -18.5 < lr["loudness"]["integrated_lufs"] < -13.5, "loudness tidak dinormalisasi"
        out = urllib.request.urlopen(f"{base}/api/projects/{prj['id']}/output").read()
        assert len(out) == lr["size"]

        # transkripsi (opsional: butuh faster-whisper + model terunduh / akses huggingface.co)
        if os.environ.get("ACEVIDS_SMOKE_WHISPER") == "1":
            speech = os.path.join(clips, "speech.mp4")
            if shutil.which("espeak-ng"):
                subprocess.run(["espeak-ng", "-v", "id", "-s", "140", "-w", os.path.join(clips, "speech.wav"),
                                "Halo semua. Ini adalah uji coba transkripsi ACEVIDS."], check=True)
                subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-f", "lavfi", "-i",
                                "testsrc2=size=320x240:rate=25", "-i", os.path.join(clips, "speech.wav"), "-shortest",
                                "-c:v", "libx264", "-preset", "veryfast", "-c:a", "aac", speech], check=True)
            else:
                speech = os.path.join(clips, "a.mp4")  # tanpa espeak: cukup uji jalurnya
            sid = upload(base, speech)["id"]
            wait_for(lambda: req(f"{base}/api/media/{sid}")["status"] == "ready", 300, "analisis speech")
            req(f"{base}/api/media/{sid}/transcribe", "POST", {"model": os.environ.get("ACEVIDS_WHISPER_MODEL", "base"), "language": "id"})

            def transcribed():
                m = req(f"{base}/api/media/{sid}")
                tr = m.get("transcript") or {}
                if tr.get("status") == "failed":
                    raise SystemExit("transkripsi gagal: " + str(tr.get("error")))
                return tr if tr.get("status") == "done" else None
            tr = wait_for(transcribed, 900, "transkripsi")
            srt = urllib.request.urlopen(f"{base}/api/media/{sid}/transcript?format=srt").read().decode()
            print("transkrip:", tr["model"], tr["language"], tr["words"], "kata |", srt.splitlines()[2] if len(srt.splitlines()) > 2 else srt)
            assert tr["words"] > 0 and "-->" in srt

        # render kedua tanpa transisi (jalur concat + copy video)
        req(f"{base}/api/projects/{prj['id']}", "PUT", {"settings": {"transition": "none", "title": "", "normalize": False}})
        job2 = req(f"{base}/api/projects/{prj['id']}/render", "POST")
        lr2 = wait_for(lambda: rendered(job2["id"]), 600, "render ke-2")
        print("hasil 2 (concat copy):", lr2["duration"], "s")
        assert abs(lr2["duration"] - sum(i["duration"] for i in plan["items"])) < 1.0
        print("\nSMOKE TEST LULUS")
    finally:
        server.terminate()
        try:
            server.wait(10)
        except subprocess.TimeoutExpired:
            server.kill()
        shutil.rmtree(tmp, ignore_errors=True)


def _ok(base):
    try:
        return req(f"{base}/api/health")["ok"]
    except Exception:  # noqa: BLE001
        return False


if __name__ == "__main__":
    main()
