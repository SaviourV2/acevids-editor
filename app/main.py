"""ACEVIDS server: upload video besar (chunked/resumable), cek, susun, render jadi satu video.

Jalankan:  uvicorn app.main:app --host 0.0.0.0 --port 8080
"""

import os
import re
import shutil
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from . import config, ffmpeg_tools as ff
from .analysis import analyze_media, media_dir
from .jobs import JobManager
from .render import PRESETS, TRANSITIONS, build_plan, keep_segments, render_project
from .store import Store, new_id, now
from .transcribe import ALLOWED_MODELS, DEFAULT_MODEL, transcribe_media, whisper_available

config.ensure_dirs()
store = Store(config.DB_FILE)
jobs = JobManager(store, max_workers=config.MAX_WORKERS)

app = FastAPI(title="ACEVIDS", version="0.1.0",
              description="Upload video besar, cek, lalu edit menjadi satu video.")
STATIC = Path(__file__).parent / "static"

_SAFE_NAME = re.compile(r"[^A-Za-z0-9._ \-()\[\]]+")


def safe_filename(name: str) -> str:
    name = os.path.basename(name or "").strip() or "video"
    name = _SAFE_NAME.sub("_", name)[:180]
    return name


def ext_of(name: str) -> str:
    ext = Path(name).suffix.lower()
    if ext not in config.ALLOWED_EXTENSIONS:
        raise HTTPException(400, f"Ekstensi '{ext or '(kosong)'}' tidak didukung")
    return ext


# ---------------------------------------------------------------------------
# Model request
# ---------------------------------------------------------------------------

class UploadInit(BaseModel):
    filename: str
    size: int = Field(gt=0)
    chunk_size: Optional[int] = None


class AnalyzeRequest(BaseModel):
    deep: bool = False


class AutocutRequest(BaseModel):
    margin: float = 0.2
    min_segment: float = 0.5
    start: Optional[float] = None
    end: Optional[float] = None


class TranscribeRequest(BaseModel):
    model: str = DEFAULT_MODEL
    language: Optional[str] = None  # None/"auto" = deteksi otomatis, "id", "en", ...


class ClipModel(BaseModel):
    media_id: str
    in_: Optional[float] = Field(default=None, alias="in")
    out: Optional[float] = None
    label: Optional[str] = None
    speed: Optional[float] = 1.0
    remove_silence: Optional[bool] = None

    model_config = {"populate_by_name": True}


class ProjectModel(BaseModel):
    name: Optional[str] = None
    clips: Optional[List[ClipModel]] = None
    settings: Optional[Dict[str, Any]] = None


# ---------------------------------------------------------------------------
# Halaman & info
# ---------------------------------------------------------------------------

@app.get("/")
def index() -> FileResponse:
    return FileResponse(STATIC / "index.html")


@app.get("/api/health")
def health() -> Dict[str, Any]:
    try:
        import scenedetect  # type: ignore
        sd = scenedetect.__version__
    except Exception:  # noqa: BLE001
        sd = None
    return {
        "ok": True, "ffmpeg": ff.ffmpeg_version(), "scenedetect": sd,
        "auto_editor": shutil.which("auto-editor") is not None,
        "whisper": whisper_available(), "whisper_models": sorted(ALLOWED_MODELS), "whisper_default": DEFAULT_MODEL,
        "data_dir": str(config.DATA_DIR), "chunk_size": config.CHUNK_SIZE,
        "presets": list(PRESETS), "transitions": sorted(TRANSITIONS),
        "disk_free_gb": round(shutil.disk_usage(config.DATA_DIR).free / 1e9, 2),
    }


# ---------------------------------------------------------------------------
# Upload chunked / resumable
# ---------------------------------------------------------------------------

@app.post("/api/uploads/init")
def upload_init(body: UploadInit) -> Dict[str, Any]:
    filename = safe_filename(body.filename)
    ext_of(filename)
    chunk = int(body.chunk_size or config.CHUNK_SIZE)
    if chunk < 256 * 1024 or chunk > 512 * 1024 * 1024:
        raise HTTPException(400, "chunk_size di luar batas")
    free = shutil.disk_usage(config.UPLOAD_DIR).free
    if body.size > free * 0.9:
        raise HTTPException(507, f"Ruang disk tidak cukup ({free / 1e9:.1f} GB tersisa)")
    # Lanjutkan upload yang belum selesai dengan nama+ukuran sama.
    for up in store.list("uploads", filename=filename, size=body.size, status="uploading"):
        if up["chunk_size"] == chunk and Path(up["path"]).exists():
            return up
    upload_id = new_id("up")
    path = config.UPLOAD_DIR / f"{upload_id}{Path(filename).suffix.lower()}"
    with open(path, "wb") as f:
        f.truncate(body.size)
    total_chunks = -(-body.size // chunk)
    return store.put("uploads", {
        "id": upload_id, "filename": filename, "size": body.size, "chunk_size": chunk,
        "total_chunks": total_chunks, "received": [], "path": str(path), "status": "uploading",
    })


@app.get("/api/uploads")
def upload_find(filename: str, size: int) -> Dict[str, Any]:
    for up in store.list("uploads", filename=safe_filename(filename), size=size, status="uploading"):
        if Path(up["path"]).exists():
            return up
    raise HTTPException(404, "tidak ada upload yang bisa dilanjutkan")


@app.get("/api/uploads/{upload_id}")
def upload_status(upload_id: str) -> Dict[str, Any]:
    up = store.get("uploads", upload_id)
    if up is None:
        raise HTTPException(404, "upload tidak ditemukan")
    return up


@app.put("/api/uploads/{upload_id}/chunks/{index}")
async def upload_chunk(upload_id: str, index: int, request: Request) -> Dict[str, Any]:
    up = store.get("uploads", upload_id)
    if up is None or up["status"] != "uploading":
        raise HTTPException(404, "upload tidak ditemukan atau sudah selesai")
    if index < 0 or index >= up["total_chunks"]:
        raise HTTPException(400, "indeks chunk di luar jangkauan")
    offset = index * up["chunk_size"]
    expected = min(up["chunk_size"], up["size"] - offset)
    written = 0
    with open(up["path"], "r+b") as f:
        f.seek(offset)
        async for part in request.stream():
            if written + len(part) > expected:
                raise HTTPException(400, f"chunk {index} lebih besar dari yang diharapkan")
            f.write(part)
            written += len(part)
    if written != expected:
        raise HTTPException(400, f"chunk {index}: diterima {written} byte, diharapkan {expected}")
    received = sorted(set(up["received"]) | {index})
    store.update("uploads", upload_id, received=received)
    return {"id": upload_id, "received_count": len(received), "total_chunks": up["total_chunks"]}


def _register_media(filename: str, src_tmp: Path, size: int) -> Dict[str, Any]:
    media_id = new_id("med")
    mdir = media_dir(media_id)
    mdir.mkdir(parents=True, exist_ok=True)
    dest = mdir / f"source{Path(filename).suffix.lower()}"
    shutil.move(str(src_tmp), str(dest))
    media = store.put("media", {
        "id": media_id, "filename": filename, "size": size, "source_path": str(dest),
        "status": "queued", "probe": None, "analysis": None, "duration": None, "error": None,
    })
    jobs.submit("analyze", media_id, analyze_media(store, media_id), label=f"Cek {filename}")
    return media


@app.post("/api/uploads/{upload_id}/complete")
def upload_complete(upload_id: str) -> Dict[str, Any]:
    up = store.get("uploads", upload_id)
    if up is None:
        raise HTTPException(404, "upload tidak ditemukan")
    if up["status"] == "done" and up.get("media_id"):
        return store.get("media", up["media_id"]) or {}
    missing = sorted(set(range(up["total_chunks"])) - set(up["received"]))
    if missing:
        raise HTTPException(409, {"message": "masih ada chunk yang belum diterima", "missing": missing[:50],
                                  "missing_count": len(missing)})
    path = Path(up["path"])
    if not path.exists() or path.stat().st_size != up["size"]:
        raise HTTPException(500, "ukuran file di server tidak sesuai")
    media = _register_media(up["filename"], path, up["size"])
    store.update("uploads", upload_id, status="done", media_id=media["id"])
    return media


@app.put("/api/uploads/direct")
async def upload_direct(request: Request, filename: str = Query(...)) -> Dict[str, Any]:
    """Upload satu permintaan (mis. `curl -T file.mp4 '…/api/uploads/direct?filename=file.mp4'`)."""
    filename = safe_filename(filename)
    ext_of(filename)
    tmp = config.UPLOAD_DIR / f"{new_id('direct')}{Path(filename).suffix.lower()}"
    size = 0
    with open(tmp, "wb") as f:
        async for part in request.stream():
            f.write(part)
            size += len(part)
    if size == 0:
        tmp.unlink(missing_ok=True)
        raise HTTPException(400, "body kosong")
    return _register_media(filename, tmp, size)


# ---------------------------------------------------------------------------
# Media
# ---------------------------------------------------------------------------

def _media_or_404(media_id: str) -> Dict[str, Any]:
    media = store.get("media", media_id)
    if media is None:
        raise HTTPException(404, "media tidak ditemukan")
    return media


def _media_view(media: Dict[str, Any]) -> Dict[str, Any]:
    job = jobs.active_for("analyze", media["id"])
    media["job"] = {"id": job["id"], "progress": job["progress"], "message": job["message"],
                    "status": job["status"]} if job else None
    tjob = jobs.active_for("transcribe", media["id"])
    media["transcribe_job"] = {"id": tjob["id"], "progress": tjob["progress"], "message": tjob["message"],
                               "status": tjob["status"]} if tjob else None
    if tjob is None and (media.get("transcript") or {}).get("status") == "running":
        failed = [j for j in store.list("jobs", kind="transcribe", target_id=media["id"]) if j["status"] in ("failed", "cancelled")]
        media["transcript"] = {"status": "failed", "error": failed[0].get("error") if failed else "job hilang"}
    if media["job"] is None:
        failed = [j for j in store.list("jobs", kind="analyze", target_id=media["id"]) if j["status"] == "failed"]
        if failed and media.get("status") not in ("ready",):
            media["status"] = "failed"
            media["error"] = failed[0].get("error")
    return media


@app.get("/api/media")
def media_list() -> List[Dict[str, Any]]:
    return [_media_view(m) for m in store.list("media")]


@app.get("/api/media/{media_id}")
def media_get(media_id: str) -> Dict[str, Any]:
    return _media_view(_media_or_404(media_id))


@app.delete("/api/media/{media_id}")
def media_delete(media_id: str) -> Dict[str, Any]:
    _media_or_404(media_id)
    used = [p["name"] for p in store.list("projects")
            if any(c.get("media_id") == media_id for c in p.get("clips", []))]
    if used:
        raise HTTPException(409, f"media dipakai project: {', '.join(used)}")
    shutil.rmtree(media_dir(media_id), ignore_errors=True)
    store.delete("media", media_id)
    return {"deleted": media_id}


@app.post("/api/media/{media_id}/analyze")
def media_analyze(media_id: str, body: AnalyzeRequest = AnalyzeRequest()) -> Dict[str, Any]:
    _media_or_404(media_id)
    active = jobs.active_for("analyze", media_id)
    if active:
        return active
    store.update("media", media_id, status="queued", error=None)
    return jobs.submit("analyze", media_id, analyze_media(store, media_id, deep=body.deep),
                       label=("Cek penuh " if body.deep else "Cek ") + (store.get("media", media_id) or {}).get("filename", ""))


@app.get("/api/media/{media_id}/proxy")
def media_proxy(media_id: str) -> FileResponse:
    media = _media_or_404(media_id)
    p = media.get("proxy_path")
    if not p or not Path(p).exists():
        raise HTTPException(404, "proxy belum tersedia")
    return FileResponse(p, media_type="video/mp4" if p.endswith(".mp4") else "audio/mp4")


@app.get("/api/media/{media_id}/source")
def media_source(media_id: str) -> FileResponse:
    media = _media_or_404(media_id)
    return FileResponse(media["source_path"], filename=media["filename"])


@app.get("/api/media/{media_id}/thumbs/{name}")
def media_thumb(media_id: str, name: str) -> FileResponse:
    _media_or_404(media_id)
    if "/" in name or ".." in name:
        raise HTTPException(400, "nama tidak valid")
    p = media_dir(media_id) / "thumbs" / name
    if not p.exists():
        raise HTTPException(404, "thumbnail tidak ada")
    return FileResponse(p, media_type="image/jpeg")


@app.post("/api/media/{media_id}/transcribe")
def media_transcribe(media_id: str, body: TranscribeRequest = TranscribeRequest()) -> Dict[str, Any]:
    """Transkripsi lokal (faster-whisper) -> transcript.json (tingkat kata), .srt, .txt."""
    media = _media_or_404(media_id)
    if not whisper_available():
        raise HTTPException(501, "faster-whisper belum terpasang: pip install faster-whisper")
    if media.get("status") != "ready":
        raise HTTPException(409, "media belum selesai dicek")
    if not (media.get("probe") or {}).get("has_audio"):
        raise HTTPException(400, "media tidak punya audio")
    active = jobs.active_for("transcribe", media_id)
    if active:
        return active
    lang = (body.language or "").strip().lower() or None
    if lang == "auto":
        lang = None
    try:
        fn = transcribe_media(store, media_id, body.model, lang)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    job = jobs.submit("transcribe", media_id, fn, label=f"Transkrip {media['filename']} ({body.model})")
    store.update("media", media_id, transcript={"status": "running", "model": body.model, "job_id": job["id"]})
    return job


@app.get("/api/media/{media_id}/transcript")
def media_transcript(media_id: str, format: str = "json") -> FileResponse:
    media = _media_or_404(media_id)
    t = media.get("transcript") or {}
    if t.get("status") != "done":
        raise HTTPException(404, "transkrip belum ada")
    key = {"json": "json_path", "srt": "srt_path", "txt": "txt_path"}.get(format)
    if key is None:
        raise HTTPException(400, "format harus json, srt, atau txt")
    stem = re.sub(r"[^A-Za-z0-9._-]+", "_", Path(media["filename"]).stem) or "transcript"
    mt = {"json": "application/json", "srt": "application/x-subrip", "txt": "text/plain"}[format]
    return FileResponse(t[key], media_type=mt, filename=f"{stem}.{format}")


@app.post("/api/media/{media_id}/autocut")
def media_autocut(media_id: str, body: AutocutRequest = AutocutRequest()) -> Dict[str, Any]:
    """Potongan otomatis: buang keheningan (gaya auto-editor) -> daftar segmen yang dipertahankan."""
    media = _media_or_404(media_id)
    if media.get("status") != "ready":
        raise HTTPException(409, "media belum selesai dicek")
    silences = (media.get("analysis") or {}).get("silences", [])
    dur = float(media.get("duration") or 0)
    start = float(body.start or 0.0)
    end = float(body.end or dur)
    segs = keep_segments(start, end, silences, body.margin, body.min_segment)
    kept = sum(b - a for a, b in segs)
    return {
        "media_id": media_id, "segments": [{"in": round(a, 3), "out": round(b, 3)} for a, b in segs],
        "kept_seconds": round(kept, 3), "removed_seconds": round((end - start) - kept, 3),
        "clips": [{"media_id": media_id, "in": round(a, 3), "out": round(b, 3),
                   "label": f"{media['filename']} #{i + 1}", "remove_silence": False}
                  for i, (a, b) in enumerate(segs)],
    }


# ---------------------------------------------------------------------------
# Project (timeline) & render
# ---------------------------------------------------------------------------

def _project_or_404(project_id: str) -> Dict[str, Any]:
    p = store.get("projects", project_id)
    if p is None:
        raise HTTPException(404, "project tidak ditemukan")
    return p


def _project_view(p: Dict[str, Any]) -> Dict[str, Any]:
    job = jobs.active_for("render", p["id"])
    p["job"] = {"id": job["id"], "progress": job["progress"], "message": job["message"],
                "status": job["status"]} if job else None
    return p


DEFAULT_SETTINGS = {"preset": "youtube", "transition": "none", "transition_duration": 0.5,
                    "remove_silence": False, "silence_margin": 0.2, "normalize": True, "lufs": -14,
                    "title": "", "title_seconds": 3}


@app.get("/api/projects")
def project_list() -> List[Dict[str, Any]]:
    return [_project_view(p) for p in store.list("projects")]


@app.post("/api/projects")
def project_create(body: ProjectModel) -> Dict[str, Any]:
    settings = dict(DEFAULT_SETTINGS)
    settings.update(body.settings or {})
    return store.put("projects", {
        "id": new_id("prj"), "name": (body.name or "").strip() or f"Project {len(store.list('projects')) + 1}",
        "clips": [c.model_dump(by_alias=True) for c in (body.clips or [])],
        "settings": settings, "last_render": None,
    })


@app.get("/api/projects/{project_id}")
def project_get(project_id: str) -> Dict[str, Any]:
    return _project_view(_project_or_404(project_id))


@app.put("/api/projects/{project_id}")
def project_update(project_id: str, body: ProjectModel) -> Dict[str, Any]:
    p = _project_or_404(project_id)
    fields: Dict[str, Any] = {}
    if body.name is not None:
        fields["name"] = body.name.strip() or p["name"]
    if body.clips is not None:
        fields["clips"] = [c.model_dump(by_alias=True) for c in body.clips]
    if body.settings is not None:
        s = dict(p.get("settings") or DEFAULT_SETTINGS)
        s.update(body.settings)
        fields["settings"] = s
    return _project_view(store.update("projects", project_id, **fields))


@app.delete("/api/projects/{project_id}")
def project_delete(project_id: str) -> Dict[str, Any]:
    _project_or_404(project_id)
    if jobs.active_for("render", project_id):
        raise HTTPException(409, "render masih berjalan")
    shutil.rmtree(config.OUTPUT_DIR / project_id, ignore_errors=True)
    store.delete("projects", project_id)
    return {"deleted": project_id}


@app.get("/api/projects/{project_id}/plan")
def project_plan(project_id: str) -> Dict[str, Any]:
    p = _project_or_404(project_id)
    try:
        return build_plan(p, store)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


@app.post("/api/projects/{project_id}/render")
def project_render(project_id: str) -> Dict[str, Any]:
    p = _project_or_404(project_id)
    active = jobs.active_for("render", project_id)
    if active:
        return active
    try:
        build_plan(p, store)  # validasi dulu supaya error langsung terlihat
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    job = jobs.submit("render", project_id, render_project(store, project_id), label=f"Render {p['name']}")
    # Tandai sekarang juga supaya klien yang langsung polling tidak melihat hasil render lama.
    store.update("projects", project_id, last_render={"status": "running", "job_id": job["id"]})
    return job


@app.get("/api/projects/{project_id}/output")
def project_output(project_id: str) -> FileResponse:
    p = _project_or_404(project_id)
    lr = p.get("last_render") or {}
    path = lr.get("output_path")
    if lr.get("status") != "done" or not path or not Path(path).exists():
        raise HTTPException(404, "belum ada hasil render")
    name = re.sub(r"[^A-Za-z0-9._-]+", "_", p["name"]) or "acevids"
    return FileResponse(path, media_type="video/mp4", filename=f"{name}.mp4")


# ---------------------------------------------------------------------------
# Jobs
# ---------------------------------------------------------------------------

@app.get("/api/jobs")
def job_list(limit: int = 50) -> List[Dict[str, Any]]:
    return store.list("jobs")[:limit]


@app.get("/api/jobs/{job_id}")
def job_get(job_id: str) -> Dict[str, Any]:
    j = store.get("jobs", job_id)
    if j is None:
        raise HTTPException(404, "job tidak ditemukan")
    return j


@app.post("/api/jobs/{job_id}/cancel")
def job_cancel(job_id: str) -> Dict[str, Any]:
    if not jobs.cancel(job_id):
        raise HTTPException(409, "job tidak sedang berjalan")
    return {"cancelling": job_id}


@app.exception_handler(ff.FFmpegError)
def ffmpeg_error(_: Request, exc: ff.FFmpegError) -> JSONResponse:
    return JSONResponse(status_code=500, content={"detail": str(exc)})


app.mount("/static", StaticFiles(directory=str(STATIC)), name="static")
