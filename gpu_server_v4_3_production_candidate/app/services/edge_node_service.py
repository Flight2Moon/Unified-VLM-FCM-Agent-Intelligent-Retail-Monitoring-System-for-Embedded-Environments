from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from app.core.db import Database, dumps, loads


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class EdgeNodeService:
    def __init__(self, db: Database):
        self.db = db

    def heartbeat(self, payload: dict[str, Any]) -> dict[str, Any]:
        edge_id = payload.get("edge_id") or payload.get("node_id") or "edge-unknown"
        ts = now_iso()
        with self.db.session() as conn:
            conn.execute(
                """
                INSERT INTO edge_nodes(edge_id, camera_id, status, policy_version, source_type, queue_count, sent_count, failed_count, last_event_at, last_heartbeat_at, payload_json)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(edge_id) DO UPDATE SET
                  camera_id=excluded.camera_id,
                  status=excluded.status,
                  policy_version=excluded.policy_version,
                  source_type=excluded.source_type,
                  queue_count=excluded.queue_count,
                  sent_count=excluded.sent_count,
                  failed_count=excluded.failed_count,
                  last_event_at=excluded.last_event_at,
                  last_heartbeat_at=excluded.last_heartbeat_at,
                  payload_json=excluded.payload_json
                """,
                (
                    edge_id,
                    payload.get("camera_id"),
                    payload.get("status", "unknown"),
                    int(payload.get("policy_version") or 0),
                    payload.get("source_type"),
                    int(payload.get("queue_count") or 0),
                    int(payload.get("sent_count") or 0),
                    int(payload.get("failed_count") or 0),
                    payload.get("last_event_at"),
                    ts,
                    dumps(payload),
                ),
            )
        return {"ok": True, "edge_id": edge_id, "received_at": ts}

    def list_nodes(self) -> list[dict[str, Any]]:
        with self.db.session() as conn:
            rows = conn.execute("SELECT * FROM edge_nodes ORDER BY last_heartbeat_at DESC").fetchall()
        out = []
        for r in rows:
            d = dict(r)
            d["payload"] = loads(d.pop("payload_json"), {})
            out.append(d)
        return out
