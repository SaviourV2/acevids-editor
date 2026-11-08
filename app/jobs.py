"""Job latar belakang (analisis media, render project) dengan progres.

Dibuat sesederhana mungkin: thread pool di dalam proses server. Catatan job
disimpan di Store supaya UI bisa polling lewat /api/jobs.
"""

import threading
import time
import traceback
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Callable, Dict, Optional

from .store import Store, new_id, now


class JobCancelled(Exception):
    pass


class JobHandle:
    """Diberikan ke fungsi job supaya bisa melaporkan progres."""

    def __init__(self, manager: "JobManager", job_id: str):
        self.manager = manager
        self.id = job_id
        self._last_write = 0.0
        self._cancel = threading.Event()

    def set_progress(self, fraction: float, message: str = "", force: bool = False) -> None:
        if self._cancel.is_set():
            raise JobCancelled()
        fraction = max(0.0, min(1.0, float(fraction)))
        # Jangan tulis ke disk lebih dari ~4x per detik.
        t = time.time()
        if not force and t - self._last_write < 0.25:
            return
        self._last_write = t
        self.manager.store.update("jobs", self.id, progress=round(fraction, 4), message=message)

    def cancel(self) -> None:
        self._cancel.set()

    @property
    def cancelled(self) -> bool:
        return self._cancel.is_set()


class JobManager:
    def __init__(self, store: Store, max_workers: int = 2):
        self.store = store
        self.executor = ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="acevids-job")
        self._handles: Dict[str, JobHandle] = {}
        self._lock = threading.Lock()
        # Job yang tertinggal "running" dari proses sebelumnya dianggap gagal.
        for job in store.list("jobs"):
            if job.get("status") in ("queued", "running"):
                store.update("jobs", job["id"], status="failed",
                             error="Server dimulai ulang sebelum job selesai", finished_at=now())

    def submit(self, kind: str, target_id: str, fn: Callable[[JobHandle], Any],
               label: str = "") -> Dict[str, Any]:
        job = self.store.put("jobs", {
            "id": new_id("job"), "kind": kind, "target_id": target_id, "label": label,
            "status": "queued", "progress": 0.0, "message": "Menunggu giliran",
            "error": None, "result": None, "started_at": None, "finished_at": None,
        })
        handle = JobHandle(self, job["id"])
        with self._lock:
            self._handles[job["id"]] = handle
        self.executor.submit(self._run, handle, fn)
        return job

    def _run(self, handle: JobHandle, fn: Callable[[JobHandle], Any]) -> None:
        self.store.update("jobs", handle.id, status="running", started_at=now(), message="Mulai")
        try:
            result = fn(handle)
            self.store.update("jobs", handle.id, status="done", progress=1.0,
                              message="Selesai", result=result, finished_at=now())
        except JobCancelled:
            self.store.update("jobs", handle.id, status="cancelled", message="Dibatalkan",
                              finished_at=now())
        except Exception as exc:  # noqa: BLE001 - laporkan apa pun yang terjadi
            self.store.update("jobs", handle.id, status="failed",
                              error=f"{type(exc).__name__}: {exc}",
                              traceback=traceback.format_exc()[-4000:], finished_at=now())
        finally:
            with self._lock:
                self._handles.pop(handle.id, None)

    def cancel(self, job_id: str) -> bool:
        with self._lock:
            handle = self._handles.get(job_id)
        if handle is None:
            return False
        handle.cancel()
        return True

    def active_for(self, kind: str, target_id: str) -> Optional[Dict[str, Any]]:
        for job in self.store.list("jobs", kind=kind, target_id=target_id):
            if job["status"] in ("queued", "running"):
                return job
        return None
