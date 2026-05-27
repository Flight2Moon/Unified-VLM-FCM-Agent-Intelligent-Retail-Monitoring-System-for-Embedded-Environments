from __future__ import annotations

from typing import Any, Dict, List, Tuple


class RelationValidator:
    def __init__(self, cfg: Dict[str, Any]):
        self.allowed = set(cfg.get("allowed_relations", []))
        self.prohibited = set(cfg.get("prohibited_relations", []))

    def validate(self, data: dict[str, Any], entities: List[dict[str, Any]]) -> dict[str, Any]:
        entity_ids = {e.get("id") for e in entities}
        kept, uncertain, rejected, warnings = [], [], [], list(data.get("warnings") or [])
        for rel in data.get("relations", []) or []:
            ok, reason = self._valid_relation(rel, entity_ids)
            if ok and rel.get("observable", True):
                kept.append(self._normalize(rel))
            else:
                rel["reason"] = reason
                rejected.append(rel)
        for rel in data.get("uncertain_relations", []) or []:
            ok, reason = self._valid_relation(rel, entity_ids, allow_uncertain=True)
            if ok:
                uncertain.append(self._normalize_uncertain(rel))
            else:
                rel["reason"] = reason
                rejected.append(rel)
        for rel in data.get("rejected_relations", []) or []:
            rejected.append(rel)
        return {
            "scene_summary": data.get("scene_summary", ""),
            "relations": kept,
            "uncertain_relations": uncertain,
            "rejected_relations": rejected,
            "warnings": warnings,
        }

    def _valid_relation(self, rel: dict[str, Any], entity_ids: set, allow_uncertain: bool = False) -> Tuple[bool, str | None]:
        s = rel.get("subject_id"); o = rel.get("object_id"); r = rel.get("relation")
        if s not in entity_ids:
            return False, f"unknown subject_id: {s}"
        if o not in entity_ids:
            return False, f"unknown object_id: {o}"
        if r in self.prohibited:
            return False, f"prohibited relation: {r}"
        if self.allowed and r not in self.allowed:
            return False, f"relation not allowed: {r}"
        return True, None

    @staticmethod
    def _conf(v: Any) -> float:
        try:
            return max(0.0, min(1.0, float(v)))
        except Exception:
            return 0.0

    def _normalize(self, rel: dict[str, Any]) -> dict[str, Any]:
        evidence = rel.get("evidence") or []
        if isinstance(evidence, str):
            evidence = [evidence]
        return {
            "subject_id": rel.get("subject_id"),
            "relation": rel.get("relation"),
            "object_id": rel.get("object_id"),
            "confidence": self._conf(rel.get("confidence")),
            "evidence": evidence[:3],
            "observable": bool(rel.get("observable", True)),
            "source": rel.get("source", "vlm_semantic"),
            "relation_type": "semantic",
            "source_call": rel.get("source_call"),
            "scene_summary": rel.get("scene_summary", ""),
        }

    def _normalize_uncertain(self, rel: dict[str, Any]) -> dict[str, Any]:
        return {
            "subject_id": rel.get("subject_id"),
            "relation": rel.get("relation"),
            "object_id": rel.get("object_id"),
            "confidence": self._conf(rel.get("confidence")),
            "reason": rel.get("reason", "uncertain"),
            "source": rel.get("source", "vlm_semantic"),
            "source_call": rel.get("source_call"),
        }
