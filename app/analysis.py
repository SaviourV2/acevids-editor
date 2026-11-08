"""Job "cek media": probe, cek decode, contact sheet, proxy, keheningan, adegan, loudness.

Hasil disimpan pada record media (store "media") dan file di folder media.
"""

from pathlib import Path
from typing import Dict, List

from . import config, ffmpeg_tools as ff
from .jobs import JobHandle
from .store import Store


def media_dir(media_id: str) -> Path:
    return config.MEDIA_DIR / media_id


def _step(handle: JobHandle, base: float, weight: float, label: str):
    def cb(frac: float) -> None:
        handle.set_progress(base + weight * frac, label)
    return cb


def analyze_media(store: Store, media_id: str, deep: bool = False):
    """Fungsi job. `deep=True` men-decode seluruh file saat cek integritas."""

    def job(handle: JobHandle) -> Dict:
        media = store.get("media", media_id)
        if media is None:
            raise RuntimeError("media tidak ditemukan")
        src = Path(media["source_path"])
        mdir = media_dir(media_id)
        thumbs = mdir / "thumbs"
        thumbs.mkdir(parents=True, exist_ok=True)
        store.update("media", media_id, status="analyzing", error=None)

        warnings: List[str] = []

        # 1. probe ------------------------------------------------------
        handle.set_progress(0.0, "Membaca metadata (ffprobe)", force=True)
        info = ff.probe(src)
        duration = float(info.get("duration") or 0.0)
        store.update("media", media_id, probe=info, duration=duration)
        if not info["has_video"] and not info["has_audio"]:
            raise RuntimeError("File tidak berisi stream video maupun audio")
        v = info.get("video") or {}
        if v.get("hdr_suspected"):
            warnings.append("Sumber tampak HDR (PQ/HLG); hasil render SDR bisa terlihat pudar.")
        if v.get("vfr_suspected"):
            warnings.append("Frame rate variabel terdeteksi; render akan dikonversi ke CFR.")
        if v.get("rotation"):
            warnings.append(f"Video punya metadata rotasi {v['rotation']}°; ffmpeg memutarnya otomatis.")

        # 2. cek decode -------------------------------------------------
        quick = None if deep else (config.QUICK_CHECK_SECONDS or None)
        label = "Cek decode seluruh file" if deep or not quick else f"Cek decode {quick} detik pertama"
        handle.set_progress(0.05, label, force=True)
        integrity = ff.integrity_check(src, seconds=quick, duration=duration,
                                       progress=_step(handle, 0.05, 0.10, label))
        if not integrity["ok"]:
            warnings.append(f"ffmpeg melaporkan {integrity['error_count']} error saat decode.")

        # 3. contact sheet ----------------------------------------------
        sheet_times: List[float] = []
        if info["has_video"]:
            handle.set_progress(0.15, "Membuat contact sheet", force=True)
            sheet_times = ff.contact_sheet(src, duration, thumbs / "sheet.jpg")
            ff.grab_frame(src, min(duration * 0.1, 5.0), thumbs / "poster.jpg", width=480)

        # 4. proxy ------------------------------------------------------
        proxy = mdir / "proxy.mp4"
        if info["has_video"]:
            handle.set_progress(0.20, "Membuat proxy preview", force=True)
            ff.make_proxy(src, proxy, duration, info["has_audio"], config.PROXY_HEIGHT,
                          progress=_step(handle, 0.20, 0.40, "Membuat proxy preview"))
        else:
            # Audio saja: proxy = file audio AAC ringan.
            handle.set_progress(0.20, "Membuat proxy audio", force=True)
            proxy = mdir / "proxy.m4a"
            ff.run_with_progress(["-y", "-i", str(src), "-vn", "-c:a", "aac", "-b:a", "128k",
                                  "-movflags", "+faststart", str(proxy)], duration,
                                 _step(handle, 0.20, 0.40, "Membuat proxy audio"))
        store.update("media", media_id, proxy_path=str(proxy))

        # 5. keheningan --------------------------------------------------
        silences: List[Dict] = []
        loudness: Dict = {}
        if info["has_audio"]:
            handle.set_progress(0.60, "Mendeteksi keheningan", force=True)
            silences = ff.detect_silence(proxy if proxy.exists() else src, duration=duration,
                                         progress=_step(handle, 0.60, 0.10, "Mendeteksi keheningan"))
            handle.set_progress(0.70, "Mengukur loudness", force=True)
            loudness = ff.measure_loudness(src, duration=duration,
                                           progress=_step(handle, 0.70, 0.08, "Mengukur loudness"))
        else:
            warnings.append("Tidak ada audio: deteksi keheningan dan loudness dilewati.")

        # 6. adegan -----------------------------------------------------
        scene_info: Dict = {"engine": None, "scenes": []}
        if info["has_video"]:
            handle.set_progress(0.78, "Mendeteksi adegan", force=True)
            scene_info = ff.detect_scenes(proxy, duration,
                                          progress=_step(handle, 0.78, 0.15, "Mendeteksi adegan"))
            scenes = scene_info["scenes"]
            # thumbnail tiap adegan (dibatasi)
            step = max(1, -(-len(scenes) // config.MAX_SCENE_THUMBS))
            for i, sc in enumerate(scenes):
                if i % step == 0:
                    p = thumbs / f"scene_{i:04d}.jpg"
                    mid = sc["start"] + (sc["end"] - sc["start"]) * 0.3
                    if ff.grab_frame(proxy, mid, p, width=240):
                        sc["thumb"] = p.name
                sc["index"] = i
                sc["duration"] = round(sc["end"] - sc["start"], 3)
            handle.set_progress(0.95, "Menyimpan hasil", force=True)

        silent_total = round(sum(s["duration"] for s in silences), 3)
        analysis = {
            "integrity": integrity,
            "sheet_times": sheet_times,
            "silences": silences,
            "silence_total": silent_total,
            "silence_params": {"noise_db": -35, "min_duration": 0.6},
            "loudness": loudness,
            "scenes": scene_info,
            "warnings": warnings,
            "deep": deep,
        }
        store.update("media", media_id, analysis=analysis, status="ready")
        return {"duration": duration, "scenes": len(scene_info["scenes"]),
                "silences": len(silences), "warnings": warnings}

    return job
