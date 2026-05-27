from __future__ import annotations

RELATION_OUTPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "scene_summary": {"type": "string"},
        "relations": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "subject_id": {"type": "string"},
                    "relation": {"type": "string"},
                    "object_id": {"type": "string"},
                    "confidence": {"type": "number"},
                    "evidence": {"type": "array", "items": {"type": "string"}},
                    "observable": {"type": "boolean"}
                },
                "required": ["subject_id", "relation", "object_id", "confidence", "evidence", "observable"]
            }
        },
        "uncertain_relations": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "subject_id": {"type": "string"},
                    "relation": {"type": "string"},
                    "object_id": {"type": "string"},
                    "confidence": {"type": "number"},
                    "reason": {"type": "string"}
                },
                "required": ["subject_id", "relation", "object_id", "confidence", "reason"]
            }
        },
        "rejected_relations": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "subject_id": {"type": "string"},
                    "relation": {"type": "string"},
                    "object_id": {"type": "string"},
                    "reason": {"type": "string"}
                },
                "required": ["subject_id", "relation", "object_id", "reason"]
            }
        },
        "warnings": {"type": "array", "items": {"type": "string"}}
    },
    "required": ["relations", "uncertain_relations", "rejected_relations", "warnings"]
}
