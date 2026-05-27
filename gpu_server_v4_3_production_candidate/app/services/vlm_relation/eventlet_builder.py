from __future__ import annotations

from typing import Any, List


class EventletBuilder:
    def build(self, final_edges: List[dict[str, Any]], event_id: str) -> list[dict[str, Any]]:
        out = []
        for idx, e in enumerate(final_edges, 1):
            rel = e.get("relation")
            conf = float(e.get("confidence") or 0)
            status = "confirmed" if conf >= 0.75 and rel not in {"near", "standing_near"} else "candidate"
            out.append({
                "eventlet_id": f"{event_id}_evtlet_{idx:03d}",
                "subject_id": e.get("subject_id"),
                "relation": rel,
                "object_id": e.get("object_id"),
                "confidence": conf,
                "status": status,
                "evidence_refs": e.get("evidence", []),
                "source": e.get("source", "unknown"),
            })
        return out
