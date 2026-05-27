from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List

from app.services.vlm_client import OllamaClient, parse_json_response

from .schema import RELATION_OUTPUT_SCHEMA
from .prompt_builder import PromptBuilder
from .pair_selector import PairSelector
from .image_preparer import ImagePreparer
from .relation_validator import RelationValidator
from .relation_consolidator import RelationConsolidator
from .eventlet_builder import EventletBuilder
from .geometry import GeometryRelationExtractor


class VLMRelationExtractor:
    def __init__(self, cfg: Dict[str, Any], ollama: OllamaClient, geometry_cfg: Dict[str, Any]):
        self.cfg = cfg
        self.ollama = ollama
        self.prompt_builder = PromptBuilder(cfg)
        self.selector = PairSelector(cfg)
        self.images = ImagePreparer(cfg)
        self.validator = RelationValidator(cfg)
        self.consolidator = RelationConsolidator(cfg)
        self.eventlets = EventletBuilder()
        self.geometry = GeometryRelationExtractor(geometry_cfg)

    def run(self, event_id: str, event_dir: Path, entities: List[dict[str, Any]], roi_hints: dict[str, Any], keyframe_names: dict[str, list[str]]) -> dict[str, Any]:
        edge_relation_hints = roi_hints.get("relation_hints") or []
        pairs = self.selector.select(entities, edge_relation_hints)
        geometry_edges = self.geometry.extract(entities, edge_relation_hints)
        base = self.images.find_image(event_dir, keyframe_names.get("curr", []))
        if not base:
            return self._fallback(event_id, geometry_edges, [], [], "no image found")
        overlay = self.images.find_image(event_dir, ["edge_overlay_t.jpg", "overlay.jpg"])
        if not overlay:
            overlay = self.images.make_overlay(base, entities, event_dir / "evidence" / "overlay_entity_ids.jpg")
        union_crops = self.images.make_union_crops(event_dir, base, entities, pairs) if self.cfg.get("use_pairwise_union_crop", True) else {}
        semantic_edges: List[dict[str, Any]] = []
        uncertain: List[dict[str, Any]] = []
        rejected: List[dict[str, Any]] = []
        runtime: dict[str, Any] = {"called": False, "calls": [], "model": self.ollama.model, "provider": getattr(self.ollama, "provider_name", "ollama")}
        call_debugs: dict[str, dict[str, Any]] = {}
        debug_dir = event_dir / "vlm_debug"
        debug_dir.mkdir(parents=True, exist_ok=True)
        if not self.cfg.get("enabled", True) or self.cfg.get("mode") == "off":
            return self._fallback(event_id, geometry_edges, pairs, [], "vlm disabled")
        mode = self.cfg.get("mode", "hybrid")
        # scene call
        if mode in {"scene_only", "hybrid"}:
            prompt = self.prompt_builder.scene_prompt(entities, pairs)
            image_paths = [overlay] if self.cfg.get("use_overlay", True) else [base]
            res = self.ollama.generate(prompt, image_paths=image_paths, schema=RELATION_OUTPUT_SCHEMA if self.cfg.get("structured_output", True) else None)
            runtime["called"] = True
            call_id = "scene"
            debug_artifacts = self._save_debug(debug_dir, call_id, prompt, res)
            ok, parsed, err = parse_json_response(res.get("response", ""))
            runtime["calls"].append({"call_id": call_id, "type": "scene", "ok": res.get("ok"), "json_parse_ok": ok, "parse_error": err, "latency_sec": res.get("latency_sec"), "status_code": res.get("status_code"), "artifacts": debug_artifacts, "images": [str(x) for x in image_paths]})
            call_debugs[call_id] = {"call_id": call_id, "type": "scene", "artifacts": debug_artifacts, "images": [str(x) for x in image_paths]}
            if ok:
                self._tag_parsed_relations(parsed, call_id)
                self._save_parsed(debug_dir, call_id, parsed)
                val = self.validator.validate(parsed, entities)
                semantic_edges.extend(val["relations"])
                uncertain.extend(val["uncertain_relations"])
                rejected.extend(val["rejected_relations"])
            else:
                runtime["scene_error"] = err
        # pairwise calls
        if mode in {"pairwise_only", "hybrid"}:
            for i, pair in enumerate(pairs[: int(self.cfg.get("max_pairwise_checks", 6))], 1):
                crop = union_crops.get(pair["pair_id"])
                if not crop:
                    continue
                geom = {"distance_px": pair.get("distance_px"), "iou": pair.get("iou"), "edge_hint": pair.get("edge_hint")}
                prompt = self.prompt_builder.pairwise_prompt(pair, entities, geom)
                res = self.ollama.generate(prompt, image_paths=[crop], schema=RELATION_OUTPUT_SCHEMA if self.cfg.get("structured_output", True) else None)
                runtime["called"] = True
                call_id = f"pairwise_{i:02d}_{pair['pair_id']}"
                debug_artifacts = self._save_debug(debug_dir, call_id, prompt, res)
                ok, parsed, err = parse_json_response(res.get("response", ""))
                runtime["calls"].append({"call_id": call_id, "type": "pairwise", "pair_id": pair["pair_id"], "ok": res.get("ok"), "json_parse_ok": ok, "parse_error": err, "latency_sec": res.get("latency_sec"), "status_code": res.get("status_code"), "artifacts": debug_artifacts, "images": [str(crop)]})
                call_debugs[call_id] = {"call_id": call_id, "type": "pairwise", "pair_id": pair["pair_id"], "artifacts": debug_artifacts, "images": [str(crop)]}
                if ok:
                    self._tag_parsed_relations(parsed, call_id)
                    self._save_parsed(debug_dir, call_id, parsed)
                    val = self.validator.validate(parsed, entities)
                    semantic_edges.extend(val["relations"])
                    uncertain.extend(val["uncertain_relations"])
                    rejected.extend(val["rejected_relations"])
                else:
                    runtime.setdefault("pairwise_errors", []).append({"pair_id": pair["pair_id"], "error": err})
        consolidated = self.consolidator.consolidate(geometry_edges, semantic_edges, uncertain)
        explanations = self._build_relation_explanations(
            consolidated["final_edges"], entities, pairs, geometry_edges, semantic_edges,
            consolidated["uncertain_relations"], rejected, consolidated["dropped_edges"], call_debugs
        )
        eventlets = self.eventlets.build(consolidated["final_edges"], event_id)
        runtime["valid_json_calls"] = sum(1 for c in runtime["calls"] if c.get("json_parse_ok"))
        runtime["successful_http_calls"] = sum(1 for c in runtime["calls"] if c.get("ok"))
        runtime["failed_calls"] = sum(1 for c in runtime["calls"] if not c.get("ok") or not c.get("json_parse_ok"))
        return {
            "candidate_pairs": pairs,
            "edge_geometry": geometry_edges,
            "vlm_semantic": semantic_edges,
            "uncertain_relations": consolidated["uncertain_relations"],
            "rejected_relations": rejected,
            "dropped_edges": consolidated["dropped_edges"],
            "final_graph_edges": consolidated["final_edges"],
            "relation_explanations": explanations,
            "eventlets": eventlets,
            "vlm_runtime": runtime,
            "evidence_assets": {"overlay": str(overlay), "union_crops": union_crops, "vlm_debug_dir": str(debug_dir)},
        }

    def _fallback(self, event_id: str, geometry_edges: list[dict[str, Any]], pairs: list[dict[str, Any]], uncertain: list[dict[str, Any]], reason: str) -> dict[str, Any]:
        final_edges = geometry_edges[: self.consolidator.max_final_edges]
        return {
            "candidate_pairs": pairs,
            "edge_geometry": geometry_edges,
            "vlm_semantic": [],
            "uncertain_relations": uncertain,
            "rejected_relations": [],
            "dropped_edges": [],
            "final_graph_edges": final_edges,
            "relation_explanations": self._build_relation_explanations(final_edges, [], pairs, geometry_edges, [], uncertain, [], [], {}),
            "eventlets": self.eventlets.build(final_edges, event_id),
            "vlm_runtime": {"called": False, "fallback_used": True, "reason": reason, "model": self.ollama.model, "provider": getattr(self.ollama, "provider_name", "ollama")},
            "evidence_assets": {},
        }

    @staticmethod
    def _tag_parsed_relations(parsed: dict[str, Any], call_id: str) -> None:
        scene_summary = parsed.get("scene_summary", "")
        for key in ("relations", "uncertain_relations", "rejected_relations"):
            for rel in parsed.get(key, []) or []:
                if isinstance(rel, dict):
                    rel["source_call"] = call_id
                    rel["scene_summary"] = scene_summary

    @staticmethod
    def _save_debug(debug_dir: Path, name: str, prompt: str, result: dict[str, Any]) -> dict[str, str]:
        safe = ''.join(c if c.isalnum() or c in ('_', '-') else '_' for c in name)[:120]
        prompt_path = debug_dir / f"{safe}_prompt.txt"
        response_path = debug_dir / f"{safe}_response.json"
        prompt_path.write_text(prompt, encoding="utf-8")
        response_path.write_text(json.dumps(result, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
        return {"prompt": str(prompt_path), "response": str(response_path)}

    @staticmethod
    def _save_parsed(debug_dir: Path, name: str, parsed: dict[str, Any]) -> None:
        safe = ''.join(c if c.isalnum() or c in ('_', '-') else '_' for c in name)[:120]
        (debug_dir / f"{safe}_parsed.json").write_text(json.dumps(parsed, ensure_ascii=False, indent=2, default=str), encoding="utf-8")

    @staticmethod
    def _edge_key(edge: dict[str, Any]) -> tuple[Any, Any, Any]:
        return (edge.get("subject_id"), edge.get("relation"), edge.get("object_id"))

    def _build_relation_explanations(
        self,
        final_edges: list[dict[str, Any]],
        entities: list[dict[str, Any]],
        pairs: list[dict[str, Any]],
        geometry_edges: list[dict[str, Any]],
        semantic_edges: list[dict[str, Any]],
        uncertain: list[dict[str, Any]],
        rejected: list[dict[str, Any]],
        dropped: list[dict[str, Any]],
        call_debugs: dict[str, dict[str, Any]],
    ) -> list[dict[str, Any]]:
        entity_map = {e.get("id"): e for e in entities}
        pair_map = {p.get("pair_id"): p for p in pairs}
        # Fallback lookup by unordered entity pair.
        by_entities = {}
        for p in pairs:
            by_entities[frozenset([p.get("subject_id"), p.get("object_id")])] = p
        geom_by_pair = {}
        for g in geometry_edges:
            geom_by_pair.setdefault((g.get("subject_id"), g.get("object_id")), []).append(g)
        semantic_by_key = {self._edge_key(e): e for e in semantic_edges}
        dropped_by_pair = {}
        for d in dropped:
            dropped_by_pair.setdefault((d.get("subject_id"), d.get("object_id")), []).append(d)
        explanations = []
        for edge in final_edges:
            s = edge.get("subject_id")
            o = edge.get("object_id")
            call_id = edge.get("source_call")
            matched_pair = None
            for p in pairs:
                ids = {p.get("subject_id"), p.get("object_id")}
                if {s, o} == ids:
                    matched_pair = p
                    break
            source_kind = "VLM semantic relation" if edge.get("relation_type") == "semantic" or edge.get("source") == "vlm_semantic" else "Edge geometry relation"
            why_kept = []
            if edge.get("relation_type") == "semantic" or edge.get("source") == "vlm_semantic":
                why_kept.append("VLM returned an observable relation that passed allowed-relation and entity-id validation.")
                why_kept.append(f"Semantic confidence {float(edge.get('confidence') or 0):.3f} met the consolidation threshold.")
            else:
                why_kept.append("No stronger semantic relation replaced this geometry edge, so the edge geometry evidence was kept.")
            suppressed = dropped_by_pair.get((s, o), []) + dropped_by_pair.get((o, s), [])
            if suppressed:
                why_kept.append(f"{len(suppressed)} lower-priority duplicate edge(s) for the pair were dropped during consolidation.")
            explanations.append({
                "edge": edge,
                "subject": entity_map.get(s, {"id": s}),
                "object": entity_map.get(o, {"id": o}),
                "source_kind": source_kind,
                "why_kept": why_kept,
                "vlm_evidence": edge.get("evidence", []),
                "scene_summary": edge.get("scene_summary", ""),
                "geometry_evidence": {
                    "candidate_pair": matched_pair,
                    "geometry_edges_same_pair": geom_by_pair.get((s, o), []) + geom_by_pair.get((o, s), []),
                },
                "debug_call": call_debugs.get(call_id, {"call_id": call_id}) if call_id else None,
                "dropped_competing_edges": suppressed,
            })
        return explanations
