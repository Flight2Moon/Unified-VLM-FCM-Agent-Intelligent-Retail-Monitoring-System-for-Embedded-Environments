from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

from app.core.db import Database, dumps, loads
from app.services.dataset_builder import DatasetBuilder
from app.services.graph_memory import GraphMemory
from app.services.label_stats_service import LabelStatsService
from app.services.scoring import AnomalyScorer
from app.services.vlm_relation.relation_extractor import VLMRelationExtractor


class EventProcessor:
    def __init__(
        self,
        db: Database,
        relation_extractor: VLMRelationExtractor,
        label_stats: LabelStatsService,
        dataset_builder: DatasetBuilder,
        graph_memory: GraphMemory,
        scorer: AnomalyScorer,
        keyframe_names: dict[str, list[str]],
    ):
        self.db = db
        self.relation_extractor = relation_extractor
        self.label_stats = label_stats
        self.dataset_builder = dataset_builder
        self.graph_memory = graph_memory
        self.scorer = scorer
        self.keyframe_names = keyframe_names

    def process(self, event_id: str) -> dict[str, Any]:
        self._stage(event_id, "processing", "Event processing started")
        with self.db.session() as conn:
            row = conn.execute("SELECT * FROM events WHERE event_id=?", (event_id,)).fetchone()
        if not row:
            raise KeyError(event_id)
        event_dir = Path(row["event_dir"])
        metadata = loads(row["metadata_json"], {}) or {}
        self._stage(event_id, "reading_roi_hints", "Reading ROI hints and edge metadata")
        roi_hints = self._read_roi_hints(event_dir)
        entities = self._normalize_entities(roi_hints)
        self._stage(event_id, "entities_normalized", f"Normalized {len(entities)} entities", {"entity_count": len(entities)})
        self.label_stats.update_from_entities(entities)
        self._stage(event_id, "dataset_collecting", "Collecting review/train samples when configured")
        collected = self.dataset_builder.maybe_collect(event_id, event_dir, metadata, entities)
        self._stage(event_id, "vlm_relation_start", "Starting VLM visual relation extraction", {"entity_count": len(entities)})
        relation_result = self.relation_extractor.run(event_id, event_dir, entities, roi_hints, self.keyframe_names)
        self._stage(event_id, "vlm_relation_done", "VLM/geometry relation extraction completed", {"final_edges": len(relation_result.get("final_graph_edges", [])), "semantic_edges": len(relation_result.get("vlm_semantic", []))})
        entity_map = {e.get("id"): e for e in entities}
        rarity = self.graph_memory.rarity_score(relation_result.get("final_graph_edges", []), entity_map)
        scoring = self.scorer.score(relation_result, rarity)
        self._stage(event_id, "scored", f"Scored event as {scoring['decision']} / {scoring['score']}", scoring)
        self.graph_memory.update(relation_result.get("final_graph_edges", []), entity_map)
        self._stage(event_id, "graph_memory_updated", "Updated global graph memory")
        result = {
            "event_id": event_id,
            "status": "done",
            "metadata": metadata,
            "entities": entities,
            "relations": relation_result,
            "dynamic_evidence_graph": {
                "entities": entities,
                "edges": relation_result.get("final_graph_edges", []),
                "eventlets": relation_result.get("eventlets", []),
                "evidence_assets": relation_result.get("evidence_assets", {}),
            },
            "dataset_builder": {"collected_count": len(collected), "samples": collected[:20]},
            "scoring": scoring,
            "explainability": self._build_explainability_summary(relation_result, scoring),
        }
        result_path = event_dir / "result.json"
        result_path.write_text(json.dumps(result, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
        with self.db.session() as conn:
            conn.execute("UPDATE events SET status=?, result_path=?, score=?, decision=? WHERE event_id=?", ("done", str(result_path), scoring["score"], scoring["decision"], event_id))
        self._stage(event_id, "done", "Event processing completed", {"result_path": str(result_path), "score": scoring["score"], "decision": scoring["decision"]})
        return result

    def _stage(self, event_id: str, stage: str, message: str = "", payload: dict[str, Any] | None = None) -> None:
        with self.db.session() as conn:
            conn.execute("UPDATE events SET status=? WHERE event_id=?", (stage, event_id))
            conn.execute(
                "INSERT INTO event_logs(event_id, stage, message, payload_json, created_at) VALUES (?, ?, ?, ?, ?)",
                (event_id, stage, message, dumps(payload or {}), datetime.now(timezone.utc).isoformat()),
            )

    @staticmethod
    def _build_explainability_summary(relation_result: dict[str, Any], scoring: dict[str, Any]) -> dict[str, Any]:
        explanations = relation_result.get("relation_explanations", []) or []
        return {
            "relation_count": len(explanations),
            "vlm_called": bool((relation_result.get("vlm_runtime") or {}).get("called")),
            "vlm_model": (relation_result.get("vlm_runtime") or {}).get("model"),
            "available_debug_artifacts": sum(1 for e in explanations if e.get("debug_call")),
            "score_components": scoring.get("components", {}),
            "read_me": "Open /dashboard/events/{event_id} to inspect VLM evidence strings, prompt/response debug files, geometry evidence, dropped competing edges, and scoring components.",
        }

    @staticmethod
    def _read_roi_hints(event_dir: Path) -> dict[str, Any]:
        for name in ["roi_hints.json", "rois.json", "detections.json"]:
            for p in event_dir.rglob(name):
                try:
                    return json.loads(p.read_text(encoding="utf-8"))
                except Exception:
                    pass
        return {"entities": [], "relation_hints": []}

    @staticmethod
    def _normalize_entities(roi: dict[str, Any]) -> List[dict[str, Any]]:
        raw = roi.get("entities") or roi.get("objects") or roi.get("detections") or []
        out = []
        seen = set()
        for i, e in enumerate(raw, 1):
            if not isinstance(e, dict):
                continue
            label = e.get("label") or e.get("class_name") or e.get("type") or "object"
            typ_raw = e.get("type") or ""
            source_raw = e.get("source") or ""
            # GPU server v4.2+: ignore separate Edge Motion Candidate entities.
            # The server now uses YOLO/detector outputs only for graph/VLM relation extraction.
            if str(label).lower() == "motion_candidate" or str(typ_raw).lower() == "motion_candidate" or str(source_raw).lower() == "edge_frame_difference":
                continue
            eid = e.get("id") or f"entity_{i}_{label}".replace(" ", "_")
            if eid in seen:
                eid = f"{eid}_{i}"
            seen.add(eid)
            typ = e.get("type") or ("person" if label == "person" else "detected_object")
            bbox = e.get("bbox") or e.get("xyxy") or []
            if len(bbox) >= 4:
                bbox = [int(float(v)) for v in bbox[:4]]
            out.append({
                "id": eid,
                "type": typ,
                "label": label,
                "bbox": bbox,
                "confidence": float(e.get("confidence") or e.get("conf") or 0),
                "source": e.get("source", "edge"),
            })
        return out
