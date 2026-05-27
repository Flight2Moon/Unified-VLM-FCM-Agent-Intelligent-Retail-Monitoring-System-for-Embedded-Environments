from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any

from app.core.storage import dir_size_bytes


class RetentionService:
    def __init__(self, cfg: dict[str, Any], storage_root: str):
        self.cfg = cfg
        self.storage_root = Path(storage_root)

    def stats(self) -> dict[str, Any]:
        return {
            "storage_root": str(self.storage_root),
            "total_bytes": dir_size_bytes(self.storage_root),
            "events_bytes": dir_size_bytes(self.storage_root / "events"),
            "datasets_bytes": dir_size_bytes(self.storage_root / "datasets"),
            "models_bytes": dir_size_bytes(self.storage_root / "model_registry"),
        }

    def cleanup_events(self) -> dict[str, Any]:
        events_dir = self.storage_root / "events"
        max_events = int(self.cfg.get("events", {}).get("max_events", 5000))
        dirs = [p for p in events_dir.iterdir() if p.is_dir()] if events_dir.exists() else []
        dirs.sort(key=lambda p: p.stat().st_mtime, reverse=True)
        removed = 0
        for p in dirs[max_events:]:
            shutil.rmtree(p, ignore_errors=True)
            removed += 1
        return {"ok": True, "removed_event_dirs": removed}
