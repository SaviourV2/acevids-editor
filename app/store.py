"""Penyimpanan sederhana berbasis satu file JSON (cukup untuk pemakaian lokal / tim kecil).

Koleksi: uploads, media, projects, jobs. Semua operasi dilindungi lock dan
ditulis secara atomik (tulis ke file sementara lalu rename).
"""

import json
import os
import threading
import time
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional

COLLECTIONS = ("uploads", "media", "projects", "jobs")


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


def now() -> float:
    return time.time()


class Store:
    def __init__(self, path: Path):
        self.path = Path(path)
        self._lock = threading.RLock()
        self._data: Dict[str, Dict[str, Any]] = {c: {} for c in COLLECTIONS}
        self._load()

    # ---- persistence -------------------------------------------------
    def _load(self) -> None:
        if self.path.exists():
            try:
                with open(self.path, "r", encoding="utf-8") as f:
                    raw = json.load(f)
                for c in COLLECTIONS:
                    self._data[c] = dict(raw.get(c, {}))
            except (OSError, ValueError):
                # File rusak: mulai kosong, tapi simpan salinan file lama.
                backup = self.path.with_suffix(".corrupt.json")
                try:
                    os.replace(self.path, backup)
                except OSError:
                    pass

    def _save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(self._data, f, ensure_ascii=False, indent=1)
        os.replace(tmp, self.path)

    # ---- CRUD ---------------------------------------------------------
    def get(self, collection: str, item_id: str) -> Optional[Dict[str, Any]]:
        with self._lock:
            item = self._data[collection].get(item_id)
            return json.loads(json.dumps(item)) if item is not None else None

    def put(self, collection: str, item: Dict[str, Any]) -> Dict[str, Any]:
        with self._lock:
            item = dict(item)
            item["updated_at"] = now()
            item.setdefault("created_at", item["updated_at"])
            self._data[collection][item["id"]] = item
            self._save()
            return json.loads(json.dumps(item))

    def update(self, collection: str, item_id: str, **fields: Any) -> Dict[str, Any]:
        with self._lock:
            item = self._data[collection].get(item_id)
            if item is None:
                raise KeyError(f"{collection}/{item_id} tidak ditemukan")
            item.update(fields)
            item["updated_at"] = now()
            self._save()
            return json.loads(json.dumps(item))

    def delete(self, collection: str, item_id: str) -> bool:
        with self._lock:
            existed = self._data[collection].pop(item_id, None) is not None
            if existed:
                self._save()
            return existed

    def list(self, collection: str, **where: Any) -> List[Dict[str, Any]]:
        with self._lock:
            items = list(self._data[collection].values())
        if where:
            items = [i for i in items if all(i.get(k) == v for k, v in where.items())]
        items.sort(key=lambda i: i.get("created_at", 0), reverse=True)
        return json.loads(json.dumps(items))
