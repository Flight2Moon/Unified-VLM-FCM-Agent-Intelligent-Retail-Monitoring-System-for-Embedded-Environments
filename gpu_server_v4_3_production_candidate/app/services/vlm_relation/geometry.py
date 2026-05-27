from __future__ import annotations

from typing import Any, Dict, List

from .utils import center_distance, bbox_iou


class GeometryRelationExtractor:
    def __init__(self, cfg: Dict[str, Any]):
        self.cfg = cfg
        self.enabled = bool(cfg.get("enabled", True))
        self.max_edges = int(cfg.get("max_edges", 12))
        self.near_distance_px = float(cfg.get("near_distance_px", 180))
        self.overlap_iou_threshold = float(cfg.get("overlap_iou_threshold", 0.04))

    def extract(self, entities: List[dict[str, Any]], edge_hints: List[dict[str, Any]] | None = None) -> List[dict[str, Any]]:
        if not self.enabled:
            return []
        people = [e for e in entities if e.get("type") == "person" or e.get("label") == "person"]
        others = [e for e in entities if e not in people]
        edges = []
        for p in people:
            pb = p.get("bbox") or []
            if len(pb) < 4:
                continue
            for o in others:
                ob = o.get("bbox") or []
                if len(ob) < 4:
                    continue
                dist = center_distance(pb, ob)
                iou = bbox_iou(pb, ob)
                if iou >= self.overlap_iou_threshold:
                    rel = str(self.cfg.get("touching_relation", "touching_candidate"))
                    conf = min(0.70, 0.40 + iou * 3.0)
                elif dist <= self.near_distance_px:
                    rel = "near"
                    conf = max(0.25, 1.0 - dist / max(self.near_distance_px, 1.0))
                else:
                    continue
                edges.append({
                    "subject_id": p.get("id"),
                    "relation": rel,
                    "object_id": o.get("id"),
                    "confidence": round(float(conf), 4),
                    "evidence": [f"bbox distance={dist:.1f}px", f"bbox iou={iou:.4f}"],
                    "source": "edge_geometry",
                    "relation_type": "geometry",
                })
        edges.sort(key=lambda x: float(x.get("confidence") or 0), reverse=True)
        return edges[:self.max_edges]
