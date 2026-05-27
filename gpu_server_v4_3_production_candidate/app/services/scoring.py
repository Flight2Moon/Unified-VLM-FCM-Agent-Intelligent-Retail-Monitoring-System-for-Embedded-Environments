from __future__ import annotations

from typing import Any, Dict, List


class AnomalyScorer:
    def __init__(self, cfg: Dict[str, Any]):
        self.weights = cfg.get("weights", {}) or {}
        self.thresholds = cfg.get("thresholds", {}) or {}

    def score(self, relations: dict[str, Any], rarity: float) -> dict[str, Any]:
        final_edges: List[dict[str, Any]] = relations.get("final_graph_edges", []) or []
        semantic = [e for e in final_edges if e.get("relation_type") == "semantic" or e.get("source") == "vlm_semantic"]
        semantic_strength = sum(float(e.get("confidence") or 0) for e in semantic) / max(len(semantic), 1) if semantic else 0.0
        vlm_rt = relations.get("vlm_runtime", {}) or {}
        uncertainty = 0.20
        if not vlm_rt.get("called"):
            uncertainty += 0.35
        if vlm_rt.get("scene_error") or vlm_rt.get("pairwise_errors"):
            uncertainty += 0.15
        uncertain_count = len(relations.get("uncertain_relations", []) or [])
        uncertainty += min(0.25, uncertain_count * 0.04)
        uncertainty = min(1.0, uncertainty)
        persistence = 0.10 if final_edges else 0.0
        rule = 0.0
        comp = {
            "rarity": float(rarity),
            "semantic_strength": float(semantic_strength),
            "rule": float(rule),
            "uncertainty": float(uncertainty),
            "persistence": float(persistence),
        }
        total = sum(comp[k] * float(self.weights.get(k, 0)) for k in comp)
        decision = "NORMAL"
        if total >= float(self.thresholds.get("abnormal", 0.80)):
            decision = "ABNORMAL"
        elif total >= float(self.thresholds.get("suspicious", 0.60)):
            decision = "SUSPICIOUS"
        elif total >= float(self.thresholds.get("normal", 0.35)):
            decision = "WATCH"
        return {"score": round(total, 4), "decision": decision, "components": comp}
