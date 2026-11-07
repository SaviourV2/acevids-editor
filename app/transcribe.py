"""Transkripsi lokal dengan faster-whisper (CPU, int8) -> transkrip tingkat kata + SRT.

Keluaran JSON memakai bentuk yang dipahami skill herk-edit-kit (`cut-silences`,
`cut-mistakes`): {"words": [{"text","start","end","type":"word"}], "audio_duration_secs"}.
Model diunduh sekali ke ACEVIDS_MODELS (default data/models) dari huggingface.co.
"""

import json
import os
import subprocess
from pathlib import Path
from typing import Dict, List, Optional

from . import config
from .jobs import JobHandle
from .store import Store

MODELS_DIR = Path(os.environ.get("ACEVIDS_MODELS", config.DATA_DIR / "models"))
DEFAULT_MODEL = os.environ.get("ACEVIDS_WHISPER_MODEL", "base")
ALLOWED_MODELS = {"tiny", "base", "small", "medium", "large-v3", "large-v3-turbo",
                  "distil-large-v3", "turbo"}


def load_audio(path, sample_rate: int = 16000):
    """Decode audio apa pun ke float32 mono 16 kHz lewat ffmpeg (tidak bergantung versi PyAV)."""
    import numpy as np

    cmd = [config.FFMPEG, "-hide_banner", "-nostdin", "-loglevel", "error", "-i", str(path),
           "-vn", "-map", "0:a:0", "-ac", "1", "-ar", str(sample_rate), "-f", "f32le", "-"]
    proc = subprocess.run(cmd, capture_output=True)
    if proc.returncode != 0:
        raise RuntimeError("ffmpeg gagal men-decode audio: " + proc.stderr.decode(errors="replace")[-500:])
    return np.frombuffer(proc.stdout, dtype=np.float32)


def whisper_available() -> bool:
    try:
        import faster_whisper  # noqa: F401
        return True
    except ImportError:
        return False


def _srt_time(t: float) -> str:
    ms = int(round(t * 1000))
    h, ms = divmod(ms, 3_600_000)
    m, ms = divmod(ms, 60_000)
    s, ms = divmod(ms, 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def write_srt(segments: List[Dict], path: Path) -> None:
    lines = []
    for i, seg in enumerate(segments, 1):
        lines.append(f"{i}\n{_srt_time(seg['start'])} --> {_srt_time(seg['end'])}\n{seg['text'].strip()}\n")
    path.write_text("\n".join(lines), encoding="utf-8")


def transcribe_media(store: Store, media_id: str, model_name: str = DEFAULT_MODEL,
                     language: Optional[str] = None):
    if model_name not in ALLOWED_MODELS:
        raise ValueError(f"model tidak dikenal: {model_name}")

    def job(handle: JobHandle) -> Dict:
        from faster_whisper import WhisperModel  # import lambat, hanya saat dipakai

        media = store.get("media", media_id)
        if media is None:
            raise RuntimeError("media tidak ditemukan")
        if not (media.get("probe") or {}).get("has_audio"):
            raise RuntimeError("media tidak punya audio")
        duration = float(media.get("duration") or 0.0)
        # Proxy (AAC 96k) cukup untuk ASR dan jauh lebih kecil dari sumber.
        audio = media.get("proxy_path") if media.get("proxy_path") and Path(media["proxy_path"]).exists() \
            else media["source_path"]
        mdir = config.MEDIA_DIR / media_id
        MODELS_DIR.mkdir(parents=True, exist_ok=True)
        store.update("media", media_id, transcript={"status": "running", "model": model_name})

        handle.set_progress(0.02, f"Memuat model Whisper '{model_name}' (unduh bila belum ada)", force=True)
        # hf_xet butuh host CDN tambahan; jalur LFS klasik cukup dengan huggingface.co + cdn-nya.
        os.environ.setdefault("HF_HUB_DISABLE_XET", "1")
        model = WhisperModel(model_name, device="cpu", compute_type="int8",
                             download_root=str(MODELS_DIR), cpu_threads=max(1, (os.cpu_count() or 2) - 1))
        handle.set_progress(0.08, "Mentranskripsi", force=True)
        samples = load_audio(audio)
        seg_iter, info = model.transcribe(samples, language=language, word_timestamps=True,
                                          vad_filter=True, beam_size=5)
        words: List[Dict] = []
        segments: List[Dict] = []
        for seg in seg_iter:
            segments.append({"start": round(seg.start, 3), "end": round(seg.end, 3), "text": seg.text.strip()})
            for w in seg.words or []:
                words.append({"text": w.word.strip(), "start": round(w.start, 3), "end": round(w.end, 3),
                              "type": "word", "probability": round(w.probability, 3)})
            if duration:
                handle.set_progress(0.08 + 0.88 * min(1.0, seg.end / duration),
                                    f"Mentranskripsi {seg.end:.0f}/{duration:.0f} s")
        transcript = {
            "language": info.language, "language_probability": round(info.language_probability, 3),
            "model": model_name, "engine": f"faster-whisper", "audio_duration_secs": duration,
            "words": words, "segments": segments,
        }
        json_path = mdir / "transcript.json"
        srt_path = mdir / "transcript.srt"
        json_path.write_text(json.dumps(transcript, ensure_ascii=False, indent=1), encoding="utf-8")
        write_srt(segments, srt_path)
        txt_path = mdir / "transcript.txt"
        txt_path.write_text("\n".join(s["text"] for s in segments) + "\n", encoding="utf-8")
        summary = {
            "status": "done", "model": model_name, "language": info.language,
            "words": len(words), "segments": len(segments),
            "json_path": str(json_path), "srt_path": str(srt_path), "txt_path": str(txt_path),
            "preview": segments[:200],
        }
        store.update("media", media_id, transcript=summary)
        handle.set_progress(1.0, "Selesai", force=True)
        return {k: summary[k] for k in ("language", "words", "segments", "model")}

    return job
