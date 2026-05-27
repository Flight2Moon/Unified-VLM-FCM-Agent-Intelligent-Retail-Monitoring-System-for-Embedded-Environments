from __future__ import annotations

import json
import uuid
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import UploadFile

from app.core.db import Database, dumps, loads
from app.core.storage import safe_name


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class EventIngestionService:
    def __init__(self, db: Database, events_dir: str, max_upload_mb: int = 120, keep_zip: bool = True):
        self.db = db
        self.events_dir = Path(events_dir)
        self.events_dir.mkdir(parents=True, exist_ok=True)
        self.max_upload_mb = max_upload_mb
        self.keep_zip = keep_zip

    async def save_upload(self, file: UploadFile) -> dict[str, Any]:
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        suffix = Path(file.filename or "event.zip").suffix or ".zip"
        tmp_id = f"upload_{ts}_{uuid.uuid4().hex[:8]}"
        tmp_dir = self.events_dir / tmp_id
        tmp_dir.mkdir(parents=True, exist_ok=True)
        zip_path = tmp_dir / safe_name(file.filename or f"{tmp_id}{suffix}")
        size = 0
        with zip_path.open("wb") as f:
            while True:
                chunk = await file.read(1024 * 1024)
                if not chunk:
                    break
                size += len(chunk)
                if size > self.max_upload_mb * 1024 * 1024:
                    raise ValueError(f"Upload exceeds max_upload_mb={self.max_upload_mb}")
                f.write(chunk)
        event_dir = tmp_dir / "extracted"
        event_dir.mkdir(parents=True, exist_ok=True)
        self._extract_zip(zip_path, event_dir)
        metadata = self._read_metadata(event_dir)
        edge_event_id = metadata.get("event_id") or metadata.get("id")
        event_id = safe_name(edge_event_id or tmp_id)
        final_dir = self.events_dir / event_id
        if final_dir.exists():
            event_id = safe_name(f"{event_id}_{uuid.uuid4().hex[:6]}")
            final_dir = self.events_dir / event_id
        tmp_dir.rename(final_dir)
        zip_path = final_dir / zip_path.name
        event_dir = final_dir / "extracted"
        metadata["event_id"] = event_id
        metadata_path = event_dir / "metadata.normalized.json"
        metadata_path.write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")
        with self.db.session() as conn:
            conn.execute(
                """
                INSERT INTO events(event_id, created_at, status, source_type, camera_id, trigger_level, event_dir, zip_path, metadata_json)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (event_id, now_iso(), "queued", metadata.get("source_type"), metadata.get("camera_id"), metadata.get("trigger_level") or metadata.get("trigger"), str(event_dir), str(zip_path), dumps(metadata)),
            )
        return {"event_id": event_id, "event_dir": str(event_dir), "zip_path": str(zip_path), "size_bytes": size, "metadata": metadata}

    @staticmethod
    def _extract_zip(zip_path: Path, out_dir: Path) -> None:
        """Safely extract an event zip without allowing path traversal."""
        try:
            with zipfile.ZipFile(zip_path) as zf:
                bad = zf.testzip()
                if bad:
                    raise ValueError(f"Corrupt member in event zip: {bad}")
                members = zf.infolist()
                if len(members) > 300:
                    raise ValueError("Too many files in event zip")
                base = out_dir.resolve()
                total_uncompressed = 0
                for member in members:
                    total_uncompressed += int(member.file_size or 0)
                    if total_uncompressed > 1024 * 1024 * 1024:
                        raise ValueError("Uncompressed zip payload is too large")
                    target = (out_dir / member.filename).resolve()
                    if not str(target).startswith(str(base)):
                        raise ValueError(f"Unsafe zip path blocked: {member.filename}")
                    if member.is_dir():
                        target.mkdir(parents=True, exist_ok=True)
                    else:
                        target.parent.mkdir(parents=True, exist_ok=True)
                        with zf.open(member) as src, target.open("wb") as dst:
                            while True:
                                chunk = src.read(1024 * 1024)
                                if not chunk:
                                    break
                                dst.write(chunk)
        except zipfile.BadZipFile as e:
            raise ValueError(f"Invalid event zip: {e}") from e

    @staticmethod
    def _read_metadata(event_dir: Path) -> dict[str, Any]:
        for name in ["metadata.json", "event_metadata.json", "metadata.normalized.json"]:
            for p in event_dir.rglob(name):
                try:
                    return json.loads(p.read_text(encoding="utf-8"))
                except Exception:
                    pass
        return {}

    def update_status(self, event_id: str, status: str, result_path: str | None = None, score: float | None = None, decision: str | None = None) -> None:
        with self.db.session() as conn:
            conn.execute(
                "UPDATE events SET status=?, result_path=COALESCE(?, result_path), score=COALESCE(?, score), decision=COALESCE(?, decision) WHERE event_id=?",
                (status, result_path, score, decision, event_id),
            )

    def add_log(self, event_id: str, stage: str, message: str = "", payload: dict[str, Any] | None = None) -> None:
        with self.db.session() as conn:
            conn.execute(
                "INSERT INTO event_logs(event_id, stage, message, payload_json, created_at) VALUES (?, ?, ?, ?, ?)",
                (event_id, stage, message, dumps(payload or {}), now_iso()),
            )

    def list_logs(self, event_id: str, limit: int = 200) -> list[dict[str, Any]]:
        with self.db.session() as conn:
            rows = conn.execute(
                "SELECT * FROM event_logs WHERE event_id=? ORDER BY id ASC LIMIT ?",
                (event_id, limit),
            ).fetchall()
        out = []
        for r in rows:
            d = dict(r)
            d["payload"] = loads(d.pop("payload_json"), {})
            out.append(d)
        return out

    def list_recent(self, limit: int = 100) -> list[dict[str, Any]]:
        with self.db.session() as conn:
            rows = conn.execute("SELECT * FROM events ORDER BY created_at DESC LIMIT ?", (limit,)).fetchall()
        out = []
        for r in rows:
            d = dict(r)
            d["metadata"] = loads(d.pop("metadata_json"), {})
            out.append(d)
        return out


    def list_by_status_group(self, limit_per_group: int = 30) -> dict[str, Any]:
        queued_statuses = {"queued", "queued_recovered"}
        done_statuses = {"done", "failed", "failed_stale"}
        processing_statuses = {
            "processing", "reading_roi_hints", "entities_normalized", "dataset_collecting",
            "vlm_relation_start", "vlm_relation_done", "scored", "graph_memory_updated"
        }
        recent = self.list_recent(limit=500)
        groups = {"incoming": [], "processing": [], "done": [], "failed": []}
        for e in recent:
            st = e.get("status")
            if st in queued_statuses:
                groups["incoming"].append(e)
            elif st in processing_statuses:
                groups["processing"].append(e)
            elif st == "done":
                groups["done"].append(e)
            elif st in {"failed", "failed_stale"}:
                groups["failed"].append(e)
            else:
                groups["processing"].append(e)
        for k in groups:
            groups[k] = groups[k][:limit_per_group]
        return {"groups": groups, "counts": {k: len(v) for k, v in groups.items()}}

    def recover_stale_events(self, older_than_sec: int = 600, action: str = "mark_failed") -> list[dict[str, Any]]:
        terminal = {"done", "failed", "failed_stale"}
        now = datetime.now(timezone.utc)
        recovered: list[dict[str, Any]] = []
        with self.db.session() as conn:
            rows = conn.execute("SELECT event_id, status, created_at FROM events ORDER BY created_at DESC").fetchall()
            for row in rows:
                status = row["status"]
                if status in terminal:
                    continue
                last = conn.execute("SELECT created_at FROM event_logs WHERE event_id=? ORDER BY id DESC LIMIT 1", (row["event_id"],)).fetchone()
                ts_text = (last["created_at"] if last else row["created_at"]) or row["created_at"]
                try:
                    ts = datetime.fromisoformat(str(ts_text).replace("Z", "+00:00"))
                    if ts.tzinfo is None:
                        ts = ts.replace(tzinfo=timezone.utc)
                except Exception:
                    ts = now
                age = (now - ts).total_seconds()
                if age < older_than_sec:
                    continue
                new_status = "queued_recovered" if action == "requeue" else "failed_stale"
                conn.execute("UPDATE events SET status=? WHERE event_id=?", (new_status, row["event_id"]))
                conn.execute(
                    "INSERT INTO event_logs(event_id, stage, message, payload_json, created_at) VALUES (?, ?, ?, ?, ?)",
                    (row["event_id"], new_status, f"Recovered stale event from status={status}", dumps({"previous_status": status, "age_sec": age, "action": action}), now_iso()),
                )
                recovered.append({"event_id": row["event_id"], "previous_status": status, "new_status": new_status, "age_sec": age})
        return recovered

    def get_event(self, event_id: str) -> dict[str, Any] | None:
        with self.db.session() as conn:
            row = conn.execute("SELECT * FROM events WHERE event_id=?", (event_id,)).fetchone()
        if not row:
            return None
        d = dict(row)
        d["metadata"] = loads(d.pop("metadata_json"), {})
        if d.get("result_path") and Path(d["result_path"]).exists():
            try:
                d["result"] = json.loads(Path(d["result_path"]).read_text(encoding="utf-8"))
            except Exception:
                d["result"] = None
        d["logs"] = self.list_logs(event_id)
        return d
