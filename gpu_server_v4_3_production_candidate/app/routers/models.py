from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request

router = APIRouter(prefix="/api", tags=["models"])


@router.get("/models")
def list_models(request: Request):
    return {"models": request.app.state.model_registry.list_models()}


@router.post("/models/{model_id}/deploy")
def deploy(request: Request, model_id: str):
    try:
        return request.app.state.model_registry.deploy(model_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="model not found")
