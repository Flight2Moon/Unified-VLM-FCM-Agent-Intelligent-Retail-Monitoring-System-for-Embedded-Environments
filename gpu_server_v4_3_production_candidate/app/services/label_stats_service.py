from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Iterable

from app.core.db import Database


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class LabelStatsService:
    def __init__(self, db: Database):
        self.db = db

    def update_from_entities(self, entities: Iterable[dict[str, Any]]) -> None:
        ts = now_iso()
        with self.db.session() as conn:
            for ent in entities:
                label = ent.get("label") or ent.get("type") or "unknown"
                conf = float(ent.get("confidence") or 0)
                row = conn.execute("SELECT count, avg_conf FROM label_stats WHERE label=?", (label,)).fetchone()
                if row:
                    count = int(row["count"])
                    avg = float(row["avg_conf"] or 0)
                    new_count = count + 1
                    new_avg = (avg * count + conf) / max(new_count, 1)
                    conn.execute("UPDATE label_stats SET count=?, avg_conf=?, last_seen_at=? WHERE label=?", (new_count, new_avg, ts, label))
                else:
                    conn.execute("INSERT INTO label_stats(label, count, avg_conf, last_seen_at) VALUES (?, ?, ?, ?)", (label, 1, conf, ts))

    def stats(self, limit: int = 200) -> list[dict[str, Any]]:
        with self.db.session() as conn:
            rows = conn.execute("SELECT label, count, avg_conf, last_seen_at FROM label_stats ORDER BY count DESC LIMIT ?", (limit,)).fetchall()
        return [dict(r) for r in rows]
