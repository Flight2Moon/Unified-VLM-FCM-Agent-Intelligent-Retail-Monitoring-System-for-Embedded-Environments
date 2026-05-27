from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

router = APIRouter(prefix="/api", tags=["detection-policy"])


class LabelState(BaseModel):
    label: str
    state: str


@router.get("/detection-policy")
def get_policy(request: Request):
    return request.app.state.policy_service.get_policy()


@router.post("/detection-policy")
def update_policy(request: Request, patch: dict):
    return request.app.state.policy_service.update_policy(patch)


@router.post("/detection-policy/label-state")
def set_label_state(request: Request, payload: LabelState):
    try:
        return request.app.state.policy_service.set_label_state(payload.label, payload.state)
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/detection-policy/ignore-label")
def ignore_label(request: Request, payload: dict):
    return request.app.state.policy_service.set_label_state(payload.get("label"), "ignore")


@router.post("/detection-policy/keep-label")
def keep_label(request: Request, payload: dict):
    return request.app.state.policy_service.set_label_state(payload.get("label"), "keep")


@router.post("/detection-policy/important-label")
def important_label(request: Request, payload: dict):
    return request.app.state.policy_service.set_label_state(payload.get("label"), "important")


@router.get("/detection-policy/history")
def policy_history(request: Request, limit: int = 20):
    return {"history": request.app.state.policy_service.history(limit)}


@router.get("/detection-labels/stats")
def label_stats(request: Request, limit: int = 200):
    return {"labels": request.app.state.label_stats.stats(limit)}
