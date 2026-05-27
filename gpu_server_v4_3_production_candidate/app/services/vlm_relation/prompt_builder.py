from __future__ import annotations

import json
from typing import Any, Dict, List


class PromptBuilder:
    def __init__(self, cfg: Dict[str, Any]):
        self.cfg = cfg
        self.allowed = cfg.get("allowed_relations", [])
        self.prohibited = cfg.get("prohibited_relations", [])

    def base_rules(self) -> str:
        return f"""
You are a visual relation extraction module for an edge-triggered monitoring system.

Rules:
- Use ONLY the provided entity IDs. Do not invent people, objects, zones, labels, or IDs.
- Extract ONLY observable visual relations.
- Do NOT infer hidden intent, crime, emotion, motivation, or identity.
- If a relation is unclear, put it in uncertain_relations.
- If a target relation is not visually supported, put it in rejected_relations.
- Choose relation only from allowed_relations.
- For every accepted relation, evidence MUST contain 1-3 concrete visual observations, such as relative position, contact/touching, gaze/facing, body pose, hand-object proximity, overlap, or visible containment.
- Confidence must reflect visual support only: 0.80-1.00 clear contact/use; 0.60-0.79 strong proximity/pose support; 0.45-0.59 weak but plausible; below 0.45 should usually be uncertain.
- Do not use hidden intent as evidence.
- Return JSON only. No markdown.

allowed_relations = {json.dumps(self.allowed, ensure_ascii=False)}
prohibited_relations = {json.dumps(self.prohibited, ensure_ascii=False)}
""".strip()

    def scene_prompt(self, entities: List[dict[str, Any]], candidate_pairs: List[dict[str, Any]]) -> str:
        payload = {
            "entities": entities,
            "candidate_pairs": candidate_pairs,
            "task": "Extract up to the most visually supported relations among the candidate pairs. Prefer semantic relations over near when visually supported."
        }
        return self.base_rules() + "\n\nInput JSON:\n" + json.dumps(payload, ensure_ascii=False, indent=2)

    def pairwise_prompt(self, pair: dict[str, Any], entities: List[dict[str, Any]], geometry: dict[str, Any] | None = None) -> str:
        payload = {
            "entities": entities,
            "candidate_pair": pair,
            "geometry_evidence": geometry or {},
            "task": "Verify the relation for this single candidate pair. If the image only supports proximity, use near or standing_near. If semantic relation is unclear, use uncertain_relations."
        }
        return self.base_rules() + "\n\nInput JSON:\n" + json.dumps(payload, ensure_ascii=False, indent=2)
