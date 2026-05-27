from __future__ import annotations

from fastapi import APIRouter, Request

router = APIRouter(prefix="/api", tags=["training"])


@router.get("/training/status")
def status(request: Request):
    return request.app.state.training.status()


@router.post("/training/start")
def start(request: Request):
    return request.app.state.training.start_training()
