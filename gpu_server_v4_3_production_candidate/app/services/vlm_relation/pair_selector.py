from __future__ import annotations

from typing import Any, Dict, List

from .utils import center_distance, bbox_iou


class PairSelector:
    def __init__(self, cfg: Dict[str, Any]):
        self.cfg = cfg

    def select(self, entities: List[dict[str, Any]], edge_hints: List[dict[str, Any]] | None = None) -> List[dict[str, Any]]:
        max_checks = int(self.cfg.get("max_pairwise_checks", 6))
        max_per_person = int(self.cfg.get("max_pairs_per_person", 3))
        dist_thr = float(self.cfg.get("candidate_pair_distance_px", 220))
        min_conf = float(self.cfg.get("min_object_confidence", 0.15))
        people = [e for e in entities if e.get("type") == "person" or e.get("label") == "person"]
        objects = [e for e in entities if e not in people and float(e.get("confidence") or 0) >= min_conf]
        pairs: List[dict[str, Any]] = []
        hinted = set()
        for h in edge_hints or []:
            s = h.get("subject") or h.get("subject_id")
            o = h.get("object") or h.get("object_id")
            if s and o:
                hinted.add((s, o))
        for p in people:
            pbox = p.get("bbox") or []
            if len(pbox) < 4:
                continue
            candidates = []
            for o in objects:
                obox = o.get("bbox") or []
                if len(obox) < 4:
                    continue
                dist = center_distance(pbox, obox)
                iou = bbox_iou(pbox, obox)
                priority = 0.0
                if (p.get("id"), o.get("id")) in hinted:
                    priority += 0.35
                if o.get("label") in self.cfg.get("important_labels", []):
                    priority += 0.20
                priority += max(0.0, 1.0 - dist / max(dist_thr, 1.0))
                priority += min(iou * 2.0, 0.25)
                if dist <= dist_thr or iou > 0.01 or (p.get("id"), o.get("id")) in hinted:
                    candidates.append({
                        "pair_id": f"{p.get('id')}__{o.get('id')}",
                        "subject_id": p.get("id"),
                        "subject_label": p.get("label", "person"),
                        "object_id": o.get("id"),
                        "object_label": o.get("label", o.get("type", "object")),
                        "edge_hint": "near" if dist <= dist_thr else "candidate",
                        "distance_px": round(dist, 2),
                        "iou": round(iou, 4),
                        "priority": round(priority, 4),
                    })
            candidates.sort(key=lambda x: x["priority"], reverse=True)
            pairs.extend(candidates[:max_per_person])
        pairs.sort(key=lambda x: x["priority"], reverse=True)
        return pairs[:max_checks]
