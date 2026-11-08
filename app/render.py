"""Render project: daftar klip (media + in/out) -> satu video hasil edit.

Dua tahap:
  1. Tiap klip di-render ke file perantara dengan frame seragam (ukuran, fps,
     format, audio stereo 48 kHz). Bila "hapus keheningan" aktif, bagian hening
     di dalam klip dibuang di tahap ini (concat beberapa segmen).
  2. Semua perantara digabung: tanpa transisi -> concat demuxer (video disalin,
     cepat); dengan transisi -> rantai xfade + acrossfade (re-encode).
     Normalisasi loudness (loudnorm) dan judul (drawtext) diterapkan di sini.
"""

import json
import shutil
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from . import config, ffmpeg_tools as ff
from .jobs import JobHandle
from .store import Store

PRESETS: Dict[str, Optional[Tuple[int, int, float]]] = {
    "source": None,                   # ikut klip pertama
    "youtube": (1920, 1080, 30.0),
    "hd720": (1280, 720, 30.0),
    "reels": (1080, 1920, 30.0),      # 9:16
    "square": (1080, 1080, 30.0),
}

TRANSITIONS = {"none", "fade", "fadeblack", "wipeleft", "wiperight", "slideleft", "slideright",
               "dissolve", "circleopen"}


# ---------------------------------------------------------------------------
# Perencanaan
# ---------------------------------------------------------------------------

def _fmt_time(t: float) -> str:
    return f"{t:.3f}"


def keep_segments(start: float, end: float, silences: List[Dict], margin: float = 0.2,
                  min_segment: float = 0.3) -> List[Tuple[float, float]]:
    """Komplemen dari keheningan di dalam [start, end], dengan margin di tiap sisi."""
    cursor = start
    out: List[Tuple[float, float]] = []
    for s in sorted(silences, key=lambda x: x["start"]):
        s0 = max(start, s["start"] + margin)
        s1 = min(end, s["end"] - margin)
        if s1 <= s0:
            continue  # keheningan terlalu pendek setelah margin
        if s0 > cursor:
            out.append((cursor, s0))
        cursor = max(cursor, s1)
    if end > cursor:
        out.append((cursor, end))
    out = [(a, b) for a, b in out if b - a >= min_segment]
    return out or [(start, end)]


def build_plan(project: Dict, store: Store) -> Dict:
    settings = project.get("settings", {}) or {}
    preset = settings.get("preset", "youtube")
    if preset not in PRESETS:
        raise ValueError(f"preset tidak dikenal: {preset}")
    transition = settings.get("transition", "none") or "none"
    if transition not in TRANSITIONS:
        raise ValueError(f"transisi tidak dikenal: {transition}")
    tdur = float(settings.get("transition_duration", 0.5) or 0.5)
    remove_silence = bool(settings.get("remove_silence", False))
    margin = float(settings.get("silence_margin", 0.2) or 0.2)
    normalize = bool(settings.get("normalize", True))
    lufs = float(settings.get("lufs", -14) or -14)

    clips = project.get("clips", []) or []
    if not clips:
        raise ValueError("Project belum punya klip")

    items: List[Dict] = []
    warnings: List[str] = []
    frame: Optional[Tuple[int, int, float]] = PRESETS[preset]
    for i, clip in enumerate(clips):
        media = store.get("media", clip["media_id"])
        if media is None:
            raise ValueError(f"klip {i + 1}: media {clip['media_id']} tidak ada")
        if media.get("status") != "ready":
            raise ValueError(f"klip {i + 1}: media '{media.get('filename')}' belum selesai dicek")
        info = media["probe"]
        dur = float(media.get("duration") or 0)
        start = float(clip.get("in") or 0.0)
        end = float(clip.get("out") or dur)
        end = min(end, dur) if dur else end
        if end <= start:
            raise ValueError(f"klip {i + 1}: OUT ({end}) harus lebih besar dari IN ({start})")
        if frame is None:
            v = info.get("video") or {}
            w, h = int(v.get("width") or 1280), int(v.get("height") or 720)
            if v.get("rotation") in (90, -90, 270, -270):
                w, h = h, w
            frame = (w - w % 2, h - h % 2, float(v.get("fps") or 30.0))
        silences = (media.get("analysis") or {}).get("silences", [])
        use_silence = remove_silence if clip.get("remove_silence") is None else bool(clip["remove_silence"])
        if use_silence and silences:
            segs = keep_segments(start, end, silences, margin)
        else:
            segs = [(start, end)]
        speed = float(clip.get("speed") or 1.0)
        if speed <= 0:
            speed = 1.0
        items.append({
            "index": i, "media_id": media["id"], "filename": media.get("filename"),
            "source_path": media["source_path"], "has_video": info["has_video"],
            "has_audio": info["has_audio"], "in": start, "out": end,
            "segments": [{"start": round(a, 3), "end": round(b, 3)} for a, b in segs],
            "speed": speed,
            "duration": round(sum(b - a for a, b in segs) / speed, 3),
            "removed_silence": round((end - start) - sum(b - a for a, b in segs), 3),
        })
        if not info["has_video"]:
            warnings.append(f"klip {i + 1} hanya audio; akan ditampilkan sebagai layar hitam.")

    assert frame is not None
    total = sum(it["duration"] for it in items)
    if transition != "none" and len(items) > 1:
        shortest = min(it["duration"] for it in items)
        if tdur * 2 > shortest:
            tdur = max(0.1, round(shortest / 2 - 0.05, 2))
            warnings.append(f"Durasi transisi dikurangi ke {tdur}s karena ada klip pendek.")
        total -= tdur * (len(items) - 1)
    return {
        "frame": {"width": frame[0], "height": frame[1], "fps": frame[2]},
        "preset": preset, "transition": transition, "transition_duration": tdur,
        "remove_silence": remove_silence, "silence_margin": margin,
        "normalize": normalize, "lufs": lufs,
        "title": (settings.get("title") or "").strip(), "title_seconds": float(settings.get("title_seconds", 3) or 3),
        "items": items, "estimated_duration": round(total, 3), "warnings": warnings,
    }


# ---------------------------------------------------------------------------
# Tahap 1: klip perantara
# ---------------------------------------------------------------------------

def _render_item(item: Dict, frame: Dict, out: Path, progress) -> None:
    w, h, fps = frame["width"], frame["height"], frame["fps"]
    cmd: List[str] = ["-y"]
    n = len(item["segments"])
    speed = item["speed"]
    inputs = 0
    v_labels, a_labels = [], []
    filters: List[str] = []
    for k, seg in enumerate(item["segments"]):
        d = seg["end"] - seg["start"]
        cmd += ["-ss", _fmt_time(seg["start"]), "-t", _fmt_time(d), "-i", item["source_path"]]
        src_idx = inputs
        inputs += 1
        if item["has_video"]:
            vf = (f"[{src_idx}:v:0]scale={w}:{h}:force_original_aspect_ratio=decrease:flags=bicubic,"
                  f"pad={w}:{h}:(ow-iw)/2:(oh-ih)/2:color=black,setsar=1,fps={fps},format=yuv420p,"
                  f"setpts=PTS-STARTPTS")
        else:
            cmd += ["-f", "lavfi", "-t", _fmt_time(d / speed), "-i", f"color=c=black:size={w}x{h}:rate={fps}"]
            vf = f"[{inputs}:v:0]format=yuv420p,setpts=PTS-STARTPTS"
            inputs += 1
        if speed != 1.0 and item["has_video"]:
            vf += f",setpts=PTS/{speed}"
        filters.append(vf + f"[v{k}]")
        if item["has_audio"]:
            af = f"[{src_idx}:a:0]aresample=48000,aformat=sample_fmts=fltp:channel_layouts=stereo,asetpts=PTS-STARTPTS"
            if speed != 1.0:
                af += "," + _atempo_chain(speed)
        else:
            cmd += ["-f", "lavfi", "-t", _fmt_time(d / speed), "-i", "anullsrc=r=48000:cl=stereo"]
            af = f"[{inputs}:a:0]asetpts=PTS-STARTPTS"
            inputs += 1
        filters.append(af + f"[a{k}]")
        v_labels.append(f"[v{k}]")
        a_labels.append(f"[a{k}]")
    concat = "".join(v + a for v, a in zip(v_labels, a_labels)) + f"concat=n={n}:v=1:a=1[vout][aout]"
    filters.append(concat)
    cmd += ["-filter_complex", ";".join(filters), "-map", "[vout]", "-map", "[aout]",
            "-c:v", "libx264", "-preset", "fast", "-crf", "18", "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-movflags", "+faststart", str(out)]
    ff.run_with_progress(cmd, item["duration"], progress)


def _atempo_chain(speed: float) -> str:
    """atempo hanya menerima 0.5..100 per filter; rantai bila perlu."""
    parts = []
    s = speed
    while s < 0.5:
        parts.append("atempo=0.5")
        s /= 0.5
    while s > 100:
        parts.append("atempo=100")
        s /= 100
    parts.append(f"atempo={s:.4f}")
    return ",".join(parts)


# ---------------------------------------------------------------------------
# Tahap 2: gabung
# ---------------------------------------------------------------------------

def _escape_drawtext(text: str) -> str:
    return (text.replace("\\", "\\\\").replace(":", "\\:").replace("'", "\\\\\\'")
            .replace("%", "\\%").replace(",", "\\,"))


def _join(parts: List[Path], durations: List[float], plan: Dict, out: Path, progress) -> None:
    w, h, fps = plan["frame"]["width"], plan["frame"]["height"], plan["frame"]["fps"]
    transition, tdur = plan["transition"], plan["transition_duration"]
    total = plan["estimated_duration"]
    post_v: List[str] = []
    if plan["title"]:
        secs = plan["title_seconds"]
        size = max(24, int(h * 0.07))
        post_v.append(
            f"drawtext=text='{_escape_drawtext(plan['title'])}':fontsize={size}:fontcolor=white:"
            f"borderw={max(2, size // 12)}:bordercolor=black@0.7:x=(w-text_w)/2:y=(h-text_h)/2:"
            f"enable='between(t,0,{secs})'")
    post_a: List[str] = []
    if plan["normalize"]:
        post_a.append(f"loudnorm=I={plan['lufs']}:TP=-1.5:LRA=11")

    cmd: List[str] = ["-y"]
    if transition == "none" or len(parts) == 1:
        list_file = out.parent / "concat.txt"
        list_file.write_text("".join(f"file '{p.as_posix()}'\n" for p in parts), encoding="utf-8")
        cmd += ["-f", "concat", "-safe", "0", "-i", str(list_file)]
        if post_v:
            cmd += ["-vf", ",".join(post_v), "-c:v", "libx264", "-preset", "medium", "-crf", "20"]
        else:
            cmd += ["-c:v", "copy"]
        if post_a:
            cmd += ["-af", ",".join(post_a), "-c:a", "aac", "-b:a", "192k"]
        else:
            cmd += ["-c:a", "copy"]
        cmd += ["-movflags", "+faststart", str(out)]
        ff.run_with_progress(cmd, total, progress)
        return

    for p in parts:
        cmd += ["-i", str(p)]
    filters: List[str] = []
    prev_v, prev_a = "[0:v:0]", "[0:a:0]"
    offset = 0.0
    for i in range(1, len(parts)):
        offset += durations[i - 1] - tdur
        filters.append(f"{prev_v}[{i}:v:0]xfade=transition={transition}:duration={tdur}:"
                       f"offset={offset:.3f}[vx{i}]")
        filters.append(f"{prev_a}[{i}:a:0]acrossfade=d={tdur}:c1=tri:c2=tri[ax{i}]")
        prev_v, prev_a = f"[vx{i}]", f"[ax{i}]"
    filters.append(f"{prev_v}{','.join(post_v) if post_v else 'null'}[vout]")
    filters.append(f"{prev_a}{','.join(post_a) if post_a else 'anull'}[aout]")
    cmd += ["-filter_complex", ";".join(filters), "-map", "[vout]", "-map", "[aout]",
            "-c:v", "libx264", "-preset", "medium", "-crf", "20", "-pix_fmt", "yuv420p",
            "-r", str(fps), "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart", str(out)]
    ff.run_with_progress(cmd, total, progress)


# ---------------------------------------------------------------------------
# Job render
# ---------------------------------------------------------------------------

def render_project(store: Store, project_id: str):
    def job(handle: JobHandle) -> Dict:
        try:
            return _run(handle)
        except Exception as exc:
            store.update("projects", project_id,
                         last_render={"status": "failed", "job_id": handle.id, "error": str(exc)})
            raise

    def _run(handle: JobHandle) -> Dict:
        project = store.get("projects", project_id)
        if project is None:
            raise RuntimeError("project tidak ditemukan")
        plan = build_plan(project, store)
        out_dir = config.OUTPUT_DIR / project_id
        work = out_dir / "work"
        if work.exists():
            shutil.rmtree(work)
        work.mkdir(parents=True, exist_ok=True)
        (out_dir / "plan.json").write_text(json.dumps(plan, indent=2, ensure_ascii=False), encoding="utf-8")
        store.update("projects", project_id, last_render={"status": "running", "job_id": handle.id})

        items = plan["items"]
        total_dur = sum(it["duration"] for it in items) or 1.0
        # Bobot progres: tahap 1 = 70 %, tahap 2 = 30 %.
        parts: List[Path] = []
        durations: List[float] = []
        done = 0.0
        for it in items:
            part = work / f"clip_{it['index']:03d}.mp4"
            label = f"Render klip {it['index'] + 1}/{len(items)}: {it['filename']}"
            base = 0.70 * done / total_dur
            weight = 0.70 * it["duration"] / total_dur
            handle.set_progress(base, label, force=True)
            _render_item(it, plan["frame"], part,
                         lambda f, b=base, w=weight, l=label: handle.set_progress(b + w * f, l))
            durations.append(float(ff.probe(part)["duration"]))
            parts.append(part)
            done += it["duration"]

        final = out_dir / "final.mp4"
        handle.set_progress(0.70, "Menggabungkan klip", force=True)
        _join(parts, durations, plan, final,
              lambda f: handle.set_progress(0.70 + 0.28 * f, "Menggabungkan klip"))
        handle.set_progress(0.98, "Memeriksa hasil", force=True)
        info = ff.probe(final)
        loud = ff.measure_loudness(final, info["duration"]) if info["has_audio"] else {}
        shutil.rmtree(work, ignore_errors=True)
        result = {
            "output_path": str(final), "size": info["size"], "duration": info["duration"],
            "video": info.get("video"), "audio": info.get("audio"), "loudness": loud,
            "plan": {k: plan[k] for k in ("frame", "preset", "transition", "estimated_duration", "warnings")},
            "clips": len(items),
            "removed_silence": round(sum(it["removed_silence"] for it in items), 3),
        }
        store.update("projects", project_id, last_render={"status": "done", "job_id": handle.id, **result})
        return result

    return job
