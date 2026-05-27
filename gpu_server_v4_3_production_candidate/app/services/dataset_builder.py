from __future__ import annotations

import csv
import hashlib
import json
import shutil
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

from PIL import Image, ImageStat

from app.core.db import Database, dumps


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def average_hash(path: Path, hash_size: int = 8) -> str:
    img = Image.open(path).convert("L").resize((hash_size, hash_size))
    pixels = list(img.getdata())
    avg = sum(pixels) / len(pixels)
    bits = ''.join('1' if p > avg else '0' for p in pixels)
    return f"{int(bits, 2):0{hash_size*hash_size//4}x}"


def hamming_hex(a: str, b: str) -> int:
    try:
        return bin(int(a, 16) ^ int(b, 16)).count('1')
    except Exception:
        return 9999


class DatasetBuilder:
    def __init__(self, db: Database, cfg: Dict[str, Any]):
        self.db = db
        self.cfg = cfg
        self.enabled = bool(cfg.get("enabled", False))
        self.task = cfg.get("target_task", "uniform_classification")
        self.root = Path(cfg.get("root_dir", "./storage/datasets")) / self.task
        self.root.mkdir(parents=True, exist_ok=True)
        (self.root / "images" / "unknown").mkdir(parents=True, exist_ok=True)
        (self.root / "metadata").mkdir(parents=True, exist_ok=True)

    def summary(self) -> dict[str, Any]:
        with self.db.session() as conn:
            total = conn.execute("SELECT COUNT(*) c FROM dataset_samples WHERE task=?", (self.task,)).fetchone()["c"]
            rows = conn.execute("SELECT label, COUNT(*) c FROM dataset_samples WHERE task=? GROUP BY label", (self.task,)).fetchall()
            verified = conn.execute("SELECT COUNT(*) c FROM dataset_samples WHERE task=? AND verified=1", (self.task,)).fetchone()["c"]
            review = conn.execute("SELECT COUNT(*) c FROM review_queue").fetchone()["c"]
        return {"task": self.task, "total": total, "by_label": [dict(r) for r in rows], "verified": verified, "review_queue": review, "limits": self.cfg.get("limits", {})}

    def maybe_collect(self, event_id: str, event_dir: Path, metadata: dict[str, Any], entities: List[dict[str, Any]]) -> list[dict[str, Any]]:
        if not self.enabled:
            return []
        limits = self.cfg.get("limits", {}) or {}
        max_per_event = int(limits.get("max_samples_per_event", 5))
        collected: list[dict[str, Any]] = []
        crops = list((event_dir / "crops").glob("*.jpg")) + list((event_dir / "crops").glob("*.png"))
        if not crops:
            return []
        total = self._count_total()
        if total >= int(limits.get("max_total_samples", 10**9)):
            return []
        # collect person-like crops first
        person_ids = {e.get("id") for e in entities if e.get("label") == "person" or e.get("type") == "person"}
        candidates = []
        for p in crops:
            name = p.name.lower()
            score = 1.0 if any(str(pid).lower() in name for pid in person_ids if pid) or "person" in name else 0.2
            candidates.append((score, p))
        candidates.sort(key=lambda x: x[0], reverse=True)
        for _, crop in candidates:
            if len(collected) >= max_per_event:
                break
            if not self._quality_ok(crop):
                continue
            ah = average_hash(crop)
            if self._is_duplicate(ah):
                continue
            sample_id = f"sample_{uuid.uuid4().hex[:16]}"
            label = "unknown"
            dst = self.root / "images" / label / f"{sample_id}.jpg"
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(crop, dst)
            quality = self._quality(crop)
            row = {
                "sample_id": sample_id,
                "task": self.task,
                "label": label,
                "image_path": str(dst),
                "event_id": event_id,
                "source_type": metadata.get("source_type"),
                "camera_id": metadata.get("camera_id"),
                "video_name": metadata.get("video_name"),
                "bbox": [],
                "confidence": 0.0,
                "quality": quality,
                "hash": ah,
                "created_at": now_iso(),
            }
            self._insert_sample(row)
            collected.append(row)
        self._write_csv_export()
        return collected

    def _count_total(self) -> int:
        with self.db.session() as conn:
            return int(conn.execute("SELECT COUNT(*) c FROM dataset_samples WHERE task=?", (self.task,)).fetchone()["c"])

    def _is_duplicate(self, ah: str) -> bool:
        if not self.cfg.get("duplicate_filter", {}).get("enabled", True):
            return False
        thr = int(self.cfg.get("duplicate_filter", {}).get("hamming_threshold", 4))
        with self.db.session() as conn:
            rows = conn.execute("SELECT hash FROM dataset_samples WHERE task=? AND hash IS NOT NULL ORDER BY created_at DESC LIMIT 500", (self.task,)).fetchall()
        return any(hamming_hex(ah, r["hash"]) <= thr for r in rows if r["hash"])

    def _quality(self, path: Path) -> dict[str, Any]:
        img = Image.open(path).convert("RGB")
        stat = ImageStat.Stat(img)
        brightness = sum(stat.mean) / 3
        w, h = img.size
        return {"width": w, "height": h, "brightness": round(brightness, 2)}

    def _quality_ok(self, path: Path) -> bool:
        q = self._quality(path)
        filt = self.cfg.get("quality_filter", {}) or {}
        if q["brightness"] < float(filt.get("min_brightness", 0)):
            return False
        if q["brightness"] > float(filt.get("max_brightness", 255)):
            return False
        return True

    def _insert_sample(self, row: dict[str, Any]) -> None:
        with self.db.session() as conn:
            conn.execute(
                """
                INSERT INTO dataset_samples(sample_id, task, label, image_path, event_id, source_type, camera_id, video_name, bbox_json, confidence, quality_json, hash, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (row["sample_id"], row["task"], row["label"], row["image_path"], row.get("event_id"), row.get("source_type"), row.get("camera_id"), row.get("video_name"), dumps(row.get("bbox", [])), float(row.get("confidence") or 0), dumps(row.get("quality", {})), row.get("hash"), row["created_at"]),
            )
            conn.execute("INSERT OR IGNORE INTO review_queue(sample_id, priority, reason, created_at) VALUES (?, ?, ?, ?)", (row["sample_id"], 0.5, "new_unlabeled_sample", row["created_at"]))

    def _write_csv_export(self) -> None:
        path = self.root / "metadata" / "samples.csv"
        with self.db.session() as conn:
            rows = conn.execute("SELECT * FROM dataset_samples WHERE task=? ORDER BY created_at DESC", (self.task,)).fetchall()
        with path.open("w", encoding="utf-8", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(["sample_id", "label", "verified", "image_path", "event_id", "created_at"])
            for r in rows:
                writer.writerow([r["sample_id"], r["label"], r["verified"], r["image_path"], r["event_id"], r["created_at"]])

    def label_sample(self, sample_id: str, label: str, verified: bool = True) -> dict[str, Any]:
        with self.db.session() as conn:
            row = conn.execute("SELECT * FROM dataset_samples WHERE sample_id=?", (sample_id,)).fetchone()
            if not row:
                raise KeyError(sample_id)
            conn.execute("UPDATE dataset_samples SET label=?, verified=?, trainable=1 WHERE sample_id=?", (label, 1 if verified else 0, sample_id))
            conn.execute("DELETE FROM review_queue WHERE sample_id=?", (sample_id,))
        self._write_csv_export()
        return {"ok": True, "sample_id": sample_id, "label": label, "verified": verified}

    def list_samples(self, limit: int = 100, label: str | None = None, review_only: bool = False) -> list[dict[str, Any]]:
        with self.db.session() as conn:
            if review_only:
                rows = conn.execute("SELECT ds.* FROM dataset_samples ds JOIN review_queue rq ON ds.sample_id=rq.sample_id ORDER BY rq.created_at DESC LIMIT ?", (limit,)).fetchall()
            elif label:
                rows = conn.execute("SELECT * FROM dataset_samples WHERE task=? AND label=? ORDER BY created_at DESC LIMIT ?", (self.task, label, limit)).fetchall()
            else:
                rows = conn.execute("SELECT * FROM dataset_samples WHERE task=? ORDER BY created_at DESC LIMIT ?", (self.task, limit)).fetchall()
        return [dict(r) for r in rows]
