from __future__ import annotations

from fastapi import APIRouter, Request

router = APIRouter(prefix="/api", tags=["storage"])


@router.get("/storage/stats")
def stats(request: Request):
    return request.app.state.retention.stats()


@router.post("/storage/cleanup")
def cleanup(request: Request):
    return request.app.state.retention.cleanup_events()
