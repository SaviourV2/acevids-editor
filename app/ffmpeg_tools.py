"""Pembungkus ffmpeg/ffprobe yang dipakai ACEVIDS.

Semua perintah dijalankan tanpa shell (list argumen), jadi nama file aneh aman.
Progres dibaca dari `-progress pipe:1`.
"""

import json
import re
import subprocess
import threading
from pathlib import Path
from typing import Callable, Dict, List, Optional, Sequence

from . import config

ProgressCb = Optional[Callable[[float], None]]


class FFmpegError(RuntimeError):
    pass


# ---------------------------------------------------------------------------
# Utilitas
# ---------------------------------------------------------------------------

def _tail(text: str, n: int = 25) -> str:
    lines = [l for l in text.strip().splitlines() if l.strip()]
    return "\n".join(lines[-n:])


def run(cmd: Sequence[str], timeout: Optional[int] = None) -> subprocess.CompletedProcess:
    proc = subprocess.run(list(cmd), capture_output=True, text=True, timeout=timeout,
                          errors="replace")
    if proc.returncode != 0:
        raise FFmpegError(f"{cmd[0]} gagal (exit {proc.returncode}):\n{_tail(proc.stderr)}")
    return proc


def parse_rate(value: Optional[str]) -> Optional[float]:
    if not value:
        return None
    if "/" in value:
        num, den = value.split("/", 1)
        try:
            den_f = float(den)
            return round(float(num) / den_f, 3) if den_f else None
        except ValueError:
            return None
    try:
        return round(float(value), 3)
    except ValueError:
        return None


def run_with_progress(cmd: Sequence[str], total_seconds: Optional[float],
                      progress: ProgressCb = None, timeout: Optional[int] = None) -> str:
    """Jalankan ffmpeg dengan -progress pipe:1 dan laporkan fraksi 0..1."""
    full = [config.FFMPEG, "-hide_banner", "-nostdin", "-nostats", "-progress", "pipe:1",
            "-loglevel", "error"] + list(cmd)
    proc = subprocess.Popen(full, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                            errors="replace")
    stderr_chunks: List[str] = []

    def drain_err() -> None:
        assert proc.stderr is not None
        for line in proc.stderr:
            stderr_chunks.append(line)

    t = threading.Thread(target=drain_err, daemon=True)
    t.start()
    assert proc.stdout is not None
    for line in proc.stdout:
        line = line.strip()
        if progress is None or not total_seconds or total_seconds <= 0:
            continue
        if line.startswith("out_time_us=") or line.startswith("out_time_ms="):
            try:
                us = int(line.split("=", 1)[1])
            except ValueError:
                continue
            # ffmpeg 6 melaporkan microsecond di kedua kunci tersebut.
            progress(min(1.0, (us / 1_000_000) / total_seconds))
    proc.wait(timeout=timeout)
    t.join(timeout=5)
    err = "".join(stderr_chunks)
    if proc.returncode != 0:
        raise FFmpegError(f"ffmpeg gagal (exit {proc.returncode}):\n{_tail(err)}")
    if progress is not None:
        progress(1.0)
    return err


# ---------------------------------------------------------------------------
# Probe
# ---------------------------------------------------------------------------

def probe(path: Path) -> Dict:
    proc = run([config.FFPROBE, "-v", "error", "-print_format", "json", "-show_format",
                "-show_streams", str(path)])
    raw = json.loads(proc.stdout or "{}")
    fmt = raw.get("format", {})
    streams = raw.get("streams", [])
    video = next((s for s in streams if s.get("codec_type") == "video"
                  and s.get("disposition", {}).get("attached_pic", 0) != 1), None)
    audio = next((s for s in streams if s.get("codec_type") == "audio"), None)

    def f(v, default=None):
        try:
            return float(v)
        except (TypeError, ValueError):
            return default

    out: Dict = {
        "format_name": fmt.get("format_name"),
        "duration": f(fmt.get("duration"), 0.0) or (f(video.get("duration")) if video else 0.0) or 0.0,
        "size": int(f(fmt.get("size"), 0) or 0),
        "bit_rate": int(f(fmt.get("bit_rate"), 0) or 0),
        "stream_count": len(streams),
        "has_video": video is not None,
        "has_audio": audio is not None,
        "video": None,
        "audio": None,
        "subtitle_streams": sum(1 for s in streams if s.get("codec_type") == "subtitle"),
        "audio_streams": sum(1 for s in streams if s.get("codec_type") == "audio"),
    }
    if video:
        fps = parse_rate(video.get("avg_frame_rate")) or parse_rate(video.get("r_frame_rate"))
        rfps = parse_rate(video.get("r_frame_rate"))
        out["video"] = {
            "codec": video.get("codec_name"),
            "profile": video.get("profile"),
            "width": video.get("width"),
            "height": video.get("height"),
            "fps": fps,
            "r_frame_rate": rfps,
            "vfr_suspected": bool(fps and rfps and abs(fps - rfps) > 0.5),
            "pix_fmt": video.get("pix_fmt"),
            "color_transfer": video.get("color_transfer"),
            "color_primaries": video.get("color_primaries"),
            "hdr_suspected": video.get("color_transfer") in ("smpte2084", "arib-std-b67"),
            "bit_rate": int(f(video.get("bit_rate"), 0) or 0),
            "nb_frames": int(f(video.get("nb_frames"), 0) or 0),
            "rotation": _rotation(video),
            "sar": video.get("sample_aspect_ratio"),
            "dar": video.get("display_aspect_ratio"),
        }
    if audio:
        out["audio"] = {
            "codec": audio.get("codec_name"),
            "sample_rate": int(f(audio.get("sample_rate"), 0) or 0),
            "channels": audio.get("channels"),
            "channel_layout": audio.get("channel_layout"),
            "bit_rate": int(f(audio.get("bit_rate"), 0) or 0),
        }
    return out


def _rotation(stream: Dict) -> int:
    for sd in stream.get("side_data_list", []) or []:
        if "rotation" in sd:
            try:
                return int(sd["rotation"])
            except (TypeError, ValueError):
                pass
    tags = stream.get("tags", {}) or {}
    try:
        return int(tags.get("rotate", 0))
    except (TypeError, ValueError):
        return 0


# ---------------------------------------------------------------------------
# Gambar: thumbnail, contact sheet
# ---------------------------------------------------------------------------

def grab_frame(src: Path, at: float, out_png: Path, width: int = 320) -> bool:
    """Ambil satu frame pada detik `at` (seek cepat, tidak decode seluruh file)."""
    at = max(0.0, at)
    cmd = [config.FFMPEG, "-hide_banner", "-nostdin", "-loglevel", "error", "-y",
           "-ss", f"{at:.3f}", "-i", str(src), "-frames:v", "1",
           "-vf", f"scale={width}:-2", "-q:v", "4", str(out_png)]
    proc = subprocess.run(cmd, capture_output=True, text=True, errors="replace")
    return proc.returncode == 0 and out_png.exists() and out_png.stat().st_size > 0


def contact_sheet(src: Path, duration: float, out_png: Path, cols: int = 4, rows: int = 3,
                  width: int = 320) -> List[float]:
    """Contact sheet cols x rows dari frame yang diambil merata sepanjang video."""
    n = cols * rows
    times = [duration * (i + 0.5) / n for i in range(n)] if duration > 0 else [0.0] * n
    tmp_dir = out_png.parent / "_sheet"
    tmp_dir.mkdir(parents=True, exist_ok=True)
    frames: List[Path] = []
    for i, t in enumerate(times):
        p = tmp_dir / f"f{i:02d}.jpg"
        if grab_frame(src, t, p, width):
            frames.append(p)
    if not frames:
        return []
    # ffmpeg tile butuh jumlah frame sesuai; yang kurang dipad hitam oleh tile.
    list_file = tmp_dir / "list.txt"
    list_file.write_text("".join(f"file '{p.name}'\n" for p in frames), encoding="utf-8")
    cmd = [config.FFMPEG, "-hide_banner", "-nostdin", "-loglevel", "error", "-y",
           "-f", "concat", "-safe", "0", "-i", str(list_file),
           "-vf", f"scale={width}:-2:force_original_aspect_ratio=decrease,"
                  f"pad={width}:ih:(ow-iw)/2:0,tile={cols}x{rows}",
           "-frames:v", "1", "-q:v", "4", str(out_png)]
    subprocess.run(cmd, capture_output=True, text=True, errors="replace")
    for p in frames:
        p.unlink(missing_ok=True)
    list_file.unlink(missing_ok=True)
    try:
        tmp_dir.rmdir()
    except OSError:
        pass
    return times


# ---------------------------------------------------------------------------
# Proxy (preview ringan untuk browser)
# ---------------------------------------------------------------------------

def make_proxy(src: Path, out: Path, duration: float, has_audio: bool,
               height: int = 480, progress: ProgressCb = None) -> None:
    vf = f"scale=-2:'min({height},ih)',format=yuv420p"
    cmd = ["-y", "-i", str(src), "-map", "0:v:0", "-vf", vf,
           "-c:v", "libx264", "-preset", "veryfast", "-crf", "28", "-g", "48"]
    if has_audio:
        cmd += ["-map", "0:a:0", "-c:a", "aac", "-b:a", "96k", "-ac", "2", "-ar", "48000"]
    else:
        cmd += ["-an"]
    cmd += ["-movflags", "+faststart", str(out)]
    run_with_progress(cmd, duration, progress)


# ---------------------------------------------------------------------------
# Analisis audio: keheningan, loudness
# ---------------------------------------------------------------------------

_SIL_START = re.compile(r"silence_start:\s*([0-9.]+)")
_SIL_END = re.compile(r"silence_end:\s*([0-9.]+)")


def detect_silence(src: Path, noise_db: float = -35.0, min_duration: float = 0.6,
                   duration: Optional[float] = None, progress: ProgressCb = None) -> List[Dict]:
    cmd = ["-i", str(src), "-vn", "-map", "0:a:0",
           "-af", f"silencedetect=noise={noise_db}dB:d={min_duration}", "-f", "null", "-"]
    full = [config.FFMPEG, "-hide_banner", "-nostdin", "-nostats", "-progress", "pipe:1",
            "-loglevel", "info"] + cmd
    proc = subprocess.Popen(full, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                            errors="replace")
    err_lines: List[str] = []

    def drain() -> None:
        assert proc.stderr is not None
        for line in proc.stderr:
            err_lines.append(line)

    t = threading.Thread(target=drain, daemon=True)
    t.start()
    assert proc.stdout is not None
    for line in proc.stdout:
        if progress and duration and line.startswith("out_time_us="):
            try:
                progress(min(1.0, int(line.split("=")[1]) / 1_000_000 / duration))
            except ValueError:
                pass
    proc.wait()
    t.join(timeout=5)
    if proc.returncode != 0:
        raise FFmpegError(f"silencedetect gagal:\n{_tail(''.join(err_lines))}")
    silences: List[Dict] = []
    start: Optional[float] = None
    for line in err_lines:
        m = _SIL_START.search(line)
        if m:
            start = float(m.group(1))
            continue
        m = _SIL_END.search(line)
        if m and start is not None:
            end = float(m.group(1))
            silences.append({"start": round(start, 3), "end": round(end, 3),
                             "duration": round(end - start, 3)})
            start = None
    if start is not None and duration:
        silences.append({"start": round(start, 3), "end": round(duration, 3),
                         "duration": round(duration - start, 3)})
    return silences


_LOUD_I = re.compile(r"\bI:\s*(-?[0-9.]+)\s*LUFS")
_LOUD_LRA = re.compile(r"LRA:\s*(-?[0-9.]+)\s*LU")
_LOUD_PEAK = re.compile(r"Peak:\s*(-?[0-9.]+)\s*dBFS")


def measure_loudness(src: Path, duration: Optional[float] = None,
                     progress: ProgressCb = None) -> Dict:
    cmd = ["-i", str(src), "-vn", "-map", "0:a:0", "-af", "ebur128=peak=true", "-f", "null", "-"]
    full = [config.FFMPEG, "-hide_banner", "-nostdin", "-nostats", "-progress", "pipe:1",
            "-loglevel", "info"] + cmd
    proc = subprocess.Popen(full, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                            errors="replace")
    err_lines: List[str] = []

    def drain() -> None:
        assert proc.stderr is not None
        for line in proc.stderr:
            err_lines.append(line)

    t = threading.Thread(target=drain, daemon=True)
    t.start()
    assert proc.stdout is not None
    for line in proc.stdout:
        if progress and duration and line.startswith("out_time_us="):
            try:
                progress(min(1.0, int(line.split("=")[1]) / 1_000_000 / duration))
            except ValueError:
                pass
    proc.wait()
    t.join(timeout=5)
    err = "".join(err_lines)
    if proc.returncode != 0:
        raise FFmpegError(f"ebur128 gagal:\n{_tail(err)}")
    summary = err[err.rfind("Summary:"):] if "Summary:" in err else err
    out = {"integrated_lufs": None, "lra": None, "true_peak_dbfs": None}
    m = _LOUD_I.search(summary)
    if m:
        out["integrated_lufs"] = float(m.group(1))
    m = _LOUD_LRA.search(summary)
    if m:
        out["lra"] = float(m.group(1))
    m = _LOUD_PEAK.search(summary)
    if m:
        out["true_peak_dbfs"] = float(m.group(1))
    return out


# ---------------------------------------------------------------------------
# Deteksi adegan (scene)
# ---------------------------------------------------------------------------

def detect_scenes(src: Path, duration: float, threshold: float = 27.0,
                  progress: ProgressCb = None) -> Dict:
    """Pakai PySceneDetect bila ada, kalau tidak pakai filter `scene` ffmpeg."""
    try:
        from scenedetect import ContentDetector, detect  # type: ignore

        pairs = detect(str(src), ContentDetector(threshold=threshold), show_progress=False)
        scenes = [{"start": round(s.get_seconds(), 3), "end": round(e.get_seconds(), 3)}
                  for s, e in pairs]
        if not scenes and duration > 0:
            scenes = [{"start": 0.0, "end": round(duration, 3)}]
        if progress:
            progress(1.0)
        return {"engine": "pyscenedetect", "threshold": threshold, "scenes": scenes}
    except ImportError:
        pass
    except Exception as exc:  # noqa: BLE001 - jatuh ke ffmpeg
        fallback_reason = f"{type(exc).__name__}: {exc}"
    else:
        fallback_reason = None

    cmd = ["-i", str(src), "-an", "-vf", "select='gt(scene,0.4)',showinfo", "-fps_mode", "passthrough",
           "-f", "null", "-"]
    full = [config.FFMPEG, "-hide_banner", "-nostdin", "-nostats", "-progress", "pipe:1",
            "-loglevel", "info"] + cmd
    proc = subprocess.Popen(full, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                            errors="replace")
    err_lines: List[str] = []

    def drain() -> None:
        assert proc.stderr is not None
        for line in proc.stderr:
            if "pts_time" in line:
                err_lines.append(line)

    t = threading.Thread(target=drain, daemon=True)
    t.start()
    assert proc.stdout is not None
    for line in proc.stdout:
        if progress and duration and line.startswith("out_time_us="):
            try:
                progress(min(1.0, int(line.split("=")[1]) / 1_000_000 / duration))
            except ValueError:
                pass
    proc.wait()
    t.join(timeout=5)
    cuts: List[float] = []
    for line in err_lines:
        m = re.search(r"pts_time:\s*([0-9.]+)", line)
        if m:
            cuts.append(float(m.group(1)))
    bounds = [0.0] + sorted(c for c in cuts if 0 < c < duration) + [duration]
    scenes = [{"start": round(a, 3), "end": round(b, 3)} for a, b in zip(bounds, bounds[1:])
              if b - a > 0.05]
    return {"engine": "ffmpeg-scene", "threshold": 0.4, "scenes": scenes,
            "fallback_reason": fallback_reason}


# ---------------------------------------------------------------------------
# Cek integritas (decode)
# ---------------------------------------------------------------------------

def integrity_check(src: Path, seconds: Optional[float] = None, duration: Optional[float] = None,
                    progress: ProgressCb = None) -> Dict:
    cmd = ["-xerror", "-i", str(src)]
    if seconds and seconds > 0:
        cmd += ["-t", str(seconds)]
    cmd += ["-f", "null", "-"]
    full = [config.FFMPEG, "-hide_banner", "-nostdin", "-nostats", "-progress", "pipe:1",
            "-loglevel", "error"] + cmd
    proc = subprocess.Popen(full, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                            errors="replace")
    err_lines: List[str] = []

    def drain() -> None:
        assert proc.stderr is not None
        for line in proc.stderr:
            if len(err_lines) < 200:
                err_lines.append(line.rstrip())

    t = threading.Thread(target=drain, daemon=True)
    t.start()
    total = seconds if seconds and duration and seconds < duration else duration
    assert proc.stdout is not None
    for line in proc.stdout:
        if progress and total and line.startswith("out_time_us="):
            try:
                progress(min(1.0, int(line.split("=")[1]) / 1_000_000 / total))
            except ValueError:
                pass
    proc.wait()
    t.join(timeout=5)
    errors = [l for l in err_lines if l.strip()]
    return {"ok": proc.returncode == 0 and not errors, "exit_code": proc.returncode,
            "checked_seconds": total, "full_file": not (seconds and duration and seconds < duration),
            "errors": errors[:20], "error_count": len(errors)}


def ffmpeg_version() -> str:
    try:
        proc = subprocess.run([config.FFMPEG, "-version"], capture_output=True, text=True)
        return proc.stdout.splitlines()[0] if proc.stdout else "?"
    except OSError:
        return "tidak ditemukan"
