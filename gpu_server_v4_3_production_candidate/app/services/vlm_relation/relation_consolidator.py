from __future__ import annotations

from typing import Any, Dict, List


PRIORITY = {
    "holding_candidate": 90,
    "carrying_candidate": 85,
    "touching": 80,
    "using": 78,
    "reaching_toward": 70,
    "looking_at": 60,
    "sitting_on": 60,
    "facing": 55,
    "interacting_with": 55,
    "inside_zone": 50,
    "entering_zone": 50,
    "leaving_zone": 50,
    "standing_near": 30,
    "near": 10,
}


class RelationConsolidator:
    def __init__(self, cfg: Dict[str, Any]):
        cons = cfg.get("consolidation", {}) or {}
        self.suppress_near = bool(cons.get("suppress_near_if_semantic_relation_exists", True))
        self.max_final_edges = int(cons.get("max_final_edges", 12))
        self.min_sem_conf = float(cons.get("min_semantic_confidence", 0.45))

    def consolidate(self, geometry_edges: List[dict[str, Any]], semantic_edges: List[dict[str, Any]], uncertain: List[dict[str, Any]]) -> dict[str, Any]:
        dropped = []
        candidates: List[dict[str, Any]] = []
        for e in geometry_edges:
            e = dict(e)
            e.setdefault("source", "edge_geometry")
            e.setdefault("relation_type", "geometry")
            candidates.append(e)
        for e in semantic_edges:
            if float(e.get("confidence") or 0) >= self.min_sem_conf:
                candidates.append(e)
            else:
                uncertain.append({**e, "reason": "semantic confidence below threshold"})
        # group by pair and keep best relation. suppress near when better semantic exists.
        by_pair: dict[tuple[str, str], list[dict[str, Any]]] = {}
        for e in candidates:
            by_pair.setdefault((e.get("subject_id"), e.get("object_id")), []).append(e)
        final = []
        for pair, edges in by_pair.items():
            edges.sort(key=lambda x: (PRIORITY.get(x.get("relation"), 0), float(x.get("confidence") or 0)), reverse=True)
            best = edges[0]
            for other in edges[1:]:
                if self.suppress_near and other.get("relation") == "near" and best.get("relation") != "near":
                    dropped.append({**other, "reason": "suppressed_by_semantic_relation"})
                else:
                    dropped.append({**other, "reason": "lower_priority_duplicate_pair"})
            final.append(best)
        final.sort(key=lambda x: (PRIORITY.get(x.get("relation"), 0), float(x.get("confidence") or 0)), reverse=True)
        if len(final) > self.max_final_edges:
            dropped.extend([{**e, "reason": "max_final_edges_exceeded"} for e in final[self.max_final_edges:]])
            final = final[:self.max_final_edges]
        return {"final_edges": final, "uncertain_relations": uncertain, "dropped_edges": dropped}
