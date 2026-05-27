from __future__ import annotations

from fastapi import APIRouter, Request

router = APIRouter(prefix="/api", tags=["edge-nodes"])


@router.post("/edge/heartbeat")
def heartbeat(request: Request, payload: dict):
    return request.app.state.edge_nodes.heartbeat(payload)


@router.get("/edge/nodes")
def nodes(request: Request):
    return {"nodes": request.app.state.edge_nodes.list_nodes()}
