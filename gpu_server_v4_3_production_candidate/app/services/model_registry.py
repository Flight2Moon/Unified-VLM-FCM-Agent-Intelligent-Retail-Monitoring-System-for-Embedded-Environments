from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.core.db import Database, dumps


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class ModelRegistry:
    def __init__(self, db: Database, root: str):
        self.db = db
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    def list_models(self) -> list[dict[str, Any]]:
        with self.db.session() as conn:
            rows = conn.execute("SELECT * FROM model_versions ORDER BY created_at DESC").fetchall()
        return [dict(r) for r in rows]

    def register(self, task: str, version: str, path: str, metrics: dict[str, Any] | None = None, set_current: bool = False) -> dict[str, Any]:
        model_id = f"{task}:{version}"
        with self.db.session() as conn:
            if set_current:
                conn.execute("UPDATE model_versions SET is_current=0 WHERE task=?", (task,))
            conn.execute(
                "INSERT OR REPLACE INTO model_versions(model_id, task, version, path, metrics_json, is_current, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (model_id, task, version, path, dumps(metrics or {}), 1 if set_current else 0, now_iso()),
            )
        return {"ok": True, "model_id": model_id}

    def deploy(self, model_id: str) -> dict[str, Any]:
        with self.db.session() as conn:
            row = conn.execute("SELECT * FROM model_versions WHERE model_id=?", (model_id,)).fetchone()
            if not row:
                raise KeyError(model_id)
            conn.execute("UPDATE model_versions SET is_current=0 WHERE task=?", (row["task"],))
            conn.execute("UPDATE model_versions SET is_current=1 WHERE model_id=?", (model_id,))
        return {"ok": True, "model_id": model_id, "deployed": True}
