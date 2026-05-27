from __future__ import annotations

import asyncio
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

from fastapi import APIRouter, BackgroundTasks, File, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse
from PIL import Image, ImageDraw

router = APIRouter(prefix="/api", tags=["events"])
executor = ThreadPoolExecutor(max_workers=2)


def _threadsafe_broadcast(app, loop, message: dict[str, Any]) -> None:
    try:
        asyncio.run_coroutine_threadsafe(app.state.ws_manager.broadcast(message), loop)
    except Exception:
        app.state.logger.exception("websocket broadcast scheduling failed")


def _process_and_notify(app, event_id: str, loop):
    _threadsafe_broadcast(app, loop, {"type": "event_processing", "event_id": event_id})
    try:
        result = app.state.event_processor.process(event_id)
        _threadsafe_broadcast(app, loop, {
            "type": "event_done",
            "event_id": event_id,
            "status": "done",
            "score": result.get("scoring", {}).get("score"),
            "decision": result.get("scoring", {}).get("decision"),
        })
        return result
    except Exception as e:
        app.state.logger.exception("event processing failed event_id=%s", event_id)
        app.state.ingestion.update_status(event_id, "failed")
        try:
            app.state.ingestion.add_log(event_id, "failed", str(e), {"error": str(e)})
        except Exception:
            pass
        _threadsafe_broadcast(app, loop, {"type": "event_failed", "event_id": event_id, "error": str(e)})
        return {"event_id": event_id, "status": "failed", "error": str(e)}


@router.post("/events")
async def upload_event(request: Request, background: BackgroundTasks, file: UploadFile = File(...)):
    try:
        saved = await request.app.state.ingestion.save_upload(file)
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))
    event_id = saved["event_id"]
    request.app.state.ingestion.add_log(event_id, "queued", "Event zip uploaded and queued", {"filename": file.filename})
    await request.app.state.ws_manager.broadcast({"type": "event_queued", "event_id": event_id, "status": "queued"})
    async_mode = request.app.state.settings.get("processing.mode", "async") == "async"
    if async_mode:
        loop = asyncio.get_running_loop()
        loop.run_in_executor(executor, _process_and_notify, request.app, event_id, loop)
        return {"ok": True, "event_id": event_id, "status": "queued"}
    result = _process_and_notify(request.app, event_id, asyncio.get_running_loop())
    return {"ok": True, "event_id": event_id, "status": result.get("status"), "result": result}


@router.get("/events/recent")
def recent_events(request: Request, limit: int = 100):
    return {"events": request.app.state.ingestion.list_recent(limit=limit)}


@router.get("/events/status-summary")
def event_status_summary(request: Request, limit_per_group: int = 30):
    return request.app.state.ingestion.list_by_status_group(limit_per_group=limit_per_group)


@router.post("/events/recover-stale")
async def recover_stale_events(request: Request, older_than_sec: int | None = None, action: str = "mark_failed"):
    older = int(older_than_sec or request.app.state.settings.get("processing.recovery.older_than_sec", 600))
    recovered = request.app.state.ingestion.recover_stale_events(older_than_sec=older, action=action)
    await request.app.state.ws_manager.broadcast({"type": "recovery", "count": len(recovered), "items": recovered})
    # If requested, reprocess recovered items that were requeued.
    if action == "requeue":
        loop = asyncio.get_running_loop()
        for item in recovered:
            if item.get("new_status") == "queued_recovered":
                loop.run_in_executor(executor, _process_and_notify, request.app, item["event_id"], loop)
    return {"ok": True, "recovered": recovered}


@router.get("/events/{event_id}")
def get_event(request: Request, event_id: str):
    event = request.app.state.ingestion.get_event(event_id)
    if not event:
        raise HTTPException(status_code=404, detail="event not found")
    return event


@router.get("/events/{event_id}/logs")
def get_event_logs(request: Request, event_id: str, limit: int = 200):
    event = request.app.state.ingestion.get_event(event_id)
    if not event:
        raise HTTPException(status_code=404, detail="event not found")
    return {"event_id": event_id, "logs": request.app.state.ingestion.list_logs(event_id, limit=limit)}


def _asset_url(event_id: str, event_dir: Path, value: Any) -> Any:
    if isinstance(value, str):
        try:
            p = Path(value).resolve()
            base = event_dir.resolve()
            if p.exists() and str(p).startswith(str(base)):
                rel = p.relative_to(base).as_posix()
                return f"/api/events/{event_id}/assets/{rel}"
        except Exception:
            pass
        return value
    if isinstance(value, list):
        return [_asset_url(event_id, event_dir, v) for v in value]
    if isinstance(value, dict):
        return {k: _asset_url(event_id, event_dir, v) for k, v in value.items()}
    return value


@router.get("/events/{event_id}/explain")
def explain_event(request: Request, event_id: str):
    event = request.app.state.ingestion.get_event(event_id)
    if not event:
        raise HTTPException(status_code=404, detail="event not found")
    result = event.get("result") or {}
    event_dir = Path(event["event_dir"])
    relations = result.get("relations", {}) or {}
    graph = result.get("dynamic_evidence_graph", {}) or {}
    payload = {
        "event": {k: v for k, v in event.items() if k not in {"result", "logs"}},
        "logs": event.get("logs", []),
        "metadata": result.get("metadata", event.get("metadata", {})),
        "entities": result.get("entities", []),
        "relation_explanations": relations.get("relation_explanations", []),
        "final_graph_edges": relations.get("final_graph_edges", graph.get("edges", [])),
        "vlm_runtime": relations.get("vlm_runtime", {}),
        "evidence_assets": relations.get("evidence_assets", graph.get("evidence_assets", {})),
        "scoring": result.get("scoring", {}),
        "explainability": result.get("explainability", {}),
        "uncertain_relations": relations.get("uncertain_relations", []),
        "rejected_relations": relations.get("rejected_relations", []),
        "dropped_edges": relations.get("dropped_edges", []),
    }
    return _asset_url(event_id, event_dir, payload)


def _find_frame(event_dir: Path) -> Path | None:
    for name in ["frame_t.jpg", "context_t.jpg", "current.jpg", "test_frame.jpg"]:
        p = event_dir / name
        if p.exists():
            return p
    for p in event_dir.rglob("*.jpg"):
        if "crop" not in p.as_posix().lower() and "union" not in p.as_posix().lower():
            return p
    return None


def _entity_crop(event_id: str, event_dir: Path, entity: dict[str, Any]) -> str | None:
    bbox = entity.get("bbox") or []
    if len(bbox) < 4:
        return None
    crop_dir = event_dir / "evidence" / "node_crops"
    crop_dir.mkdir(parents=True, exist_ok=True)
    safe_id = ''.join(c if c.isalnum() or c in ('_', '-') else '_' for c in str(entity.get('id', 'node')))[:80]
    crop_path = crop_dir / f"{safe_id}.jpg"
    if not crop_path.exists():
        frame = _find_frame(event_dir)
        if not frame:
            return None
        try:
            img = Image.open(frame).convert("RGB")
            x1, y1, x2, y2 = [int(float(v)) for v in bbox[:4]]
            w, h = img.size
            pad = max(8, int(max(x2 - x1, y2 - y1) * 0.08))
            x1, y1 = max(0, x1 - pad), max(0, y1 - pad)
            x2, y2 = min(w, x2 + pad), min(h, y2 + pad)
            if x2 <= x1 or y2 <= y1:
                return None
            crop = img.crop((x1, y1, x2, y2))
            crop.save(crop_path, quality=90)
        except Exception:
            return None
    rel = crop_path.resolve().relative_to(event_dir.resolve()).as_posix()
    return f"/api/events/{event_id}/assets/{rel}"


@router.get("/events/{event_id}/graph")
def event_graph(request: Request, event_id: str):
    event = request.app.state.ingestion.get_event(event_id)
    if not event:
        raise HTTPException(status_code=404, detail="event not found")
    result = event.get("result") or {}
    event_dir = Path(event["event_dir"])
    entities = result.get("entities", []) or []
    edges = ((result.get("relations") or {}).get("final_graph_edges") or [])
    nodes = []
    for e in entities:
        crop_url = _entity_crop(event_id, event_dir, e)
        nodes.append({
            "id": e.get("id"),
            "label": f"{e.get('id')}\n{e.get('label', '')}",
            "group": e.get("type", "entity"),
            "title": f"{e.get('label', '')} {e.get('confidence', '')}",
            "entity": e,
            "image_url": crop_url,
        })
    vis_edges = [{
        "from": e.get("subject_id"),
        "to": e.get("object_id"),
        "label": f"{e.get('relation')} ({float(e.get('confidence') or 0):.2f})",
        "title": str(e),
        "arrows": "to",
        "smooth": {"type": "dynamic"},
        "source": e.get("source") or e.get("relation_type"),
    } for e in edges]
    return {"event_id": event_id, "nodes": nodes, "edges": vis_edges}


@router.get("/events/{event_id}/assets/{asset_path:path}")
def event_asset(request: Request, event_id: str, asset_path: str):
    event = request.app.state.ingestion.get_event(event_id)
    if not event:
        raise HTTPException(status_code=404, detail="event not found")
    base = Path(event["event_dir"]).resolve()
    target = (base / asset_path).resolve()
    if not str(target).startswith(str(base)) or not target.exists() or not target.is_file():
        raise HTTPException(status_code=404, detail="asset not found")
    return FileResponse(target)
