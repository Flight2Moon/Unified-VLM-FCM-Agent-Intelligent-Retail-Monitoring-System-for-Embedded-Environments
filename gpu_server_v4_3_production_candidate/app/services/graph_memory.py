from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, List

from app.core.db import Database


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class GraphMemory:
    def __init__(self, db: Database, store_near: bool = False):
        self.db = db
        self.store_near = store_near

    def update(self, edges: List[dict[str, Any]], entity_map: dict[str, dict[str, Any]]) -> None:
        ts = now_iso()
        with self.db.session() as conn:
            for e in edges:
                rel = e.get("relation")
                if rel == "near" and not self.store_near:
                    continue
                s_label = entity_map.get(e.get("subject_id"), {}).get("label", e.get("subject_id"))
                o_label = entity_map.get(e.get("object_id"), {}).get("label", e.get("object_id"))
                key = f"{s_label}|{rel}|{o_label}"
                row = conn.execute("SELECT count FROM graph_memory WHERE key=?", (key,)).fetchone()
                if row:
                    conn.execute("UPDATE graph_memory SET count=count+1, last_seen_at=? WHERE key=?", (ts, key))
                else:
                    conn.execute("INSERT INTO graph_memory(key, subject_label, relation, object_label, count, last_seen_at) VALUES (?, ?, ?, ?, ?, ?)", (key, s_label, rel, o_label, 1, ts))

    def rarity_score(self, edges: List[dict[str, Any]], entity_map: dict[str, dict[str, Any]]) -> float:
        if not edges:
            return 0.0
        vals = []
        with self.db.session() as conn:
            for e in edges:
                s_label = entity_map.get(e.get("subject_id"), {}).get("label", e.get("subject_id"))
                o_label = entity_map.get(e.get("object_id"), {}).get("label", e.get("object_id"))
                key = f"{s_label}|{e.get('relation')}|{o_label}"
                row = conn.execute("SELECT count FROM graph_memory WHERE key=?", (key,)).fetchone()
                count = int(row["count"]) if row else 0
                vals.append(1.0 / (1.0 + count))
        return sum(vals) / max(len(vals), 1)

    def top(self, limit: int = 100) -> list[dict[str, Any]]:
        with self.db.session() as conn:
            rows = conn.execute("SELECT * FROM graph_memory ORDER BY count DESC LIMIT ?", (limit,)).fetchall()
        return [dict(r) for r in rows]
