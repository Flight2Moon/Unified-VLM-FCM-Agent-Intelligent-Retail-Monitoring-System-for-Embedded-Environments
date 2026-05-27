from __future__ import annotations

import subprocess
import threading
from datetime import datetime, timezone
from typing import Any, Dict

from apscheduler.schedulers.background import BackgroundScheduler


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class TrainingService:
    def __init__(self, cfg: Dict[str, Any]):
        self.cfg = cfg
        self.scheduler = BackgroundScheduler()
        self.current: dict[str, Any] | None = None
        self.history: list[dict[str, Any]] = []
        if cfg.get("schedule", {}).get("enabled"):
            hour = int(cfg.get("schedule", {}).get("hour", 3))
            minute = int(cfg.get("schedule", {}).get("minute", 0))
            self.scheduler.add_job(self.start_training, "cron", hour=hour, minute=minute, id="scheduled_training", replace_existing=True)
        self.scheduler.start(paused=not bool(cfg.get("enabled", False)))

    def start_training(self) -> dict[str, Any]:
        if self.current and self.current.get("status") == "running":
            return {"ok": False, "reason": "training already running", "current": self.current}
        job = {"job_id": f"train_{datetime.now().strftime('%Y%m%d_%H%M%S')}", "status": "running", "started_at": now_iso(), "command": self.cfg.get("command")}
        self.current = job
        t = threading.Thread(target=self._run, args=(job,), daemon=True)
        t.start()
        return {"ok": True, "job": job}

    def _run(self, job: dict[str, Any]) -> None:
        cmd = job.get("command")
        if not cmd:
            job.update({"status": "skipped", "finished_at": now_iso(), "reason": "no training command configured"})
            self.history.insert(0, dict(job))
            return
        try:
            p = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=60 * 60 * 6)
            job.update({"status": "done" if p.returncode == 0 else "failed", "returncode": p.returncode, "stdout": p.stdout[-4000:], "stderr": p.stderr[-4000:], "finished_at": now_iso()})
        except Exception as e:
            job.update({"status": "failed", "error": str(e), "finished_at": now_iso()})
        self.history.insert(0, dict(job))

    def status(self) -> dict[str, Any]:
        return {"enabled": bool(self.cfg.get("enabled", False)), "current": self.current, "history": self.history[:20]}
