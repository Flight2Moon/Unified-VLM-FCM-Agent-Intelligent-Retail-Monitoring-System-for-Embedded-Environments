from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel

router = APIRouter(prefix="/api", tags=["dataset"])


class LabelPayload(BaseModel):
    label: str
    verified: bool = True


@router.get("/dataset/summary")
def summary(request: Request):
    return request.app.state.dataset_builder.summary()


@router.get("/dataset/samples")
def samples(request: Request, limit: int = 100, label: str | None = None, review_only: bool = False):
    return {"samples": request.app.state.dataset_builder.list_samples(limit=limit, label=label, review_only=review_only)}


@router.post("/dataset/samples/{sample_id}/label")
def label_sample(request: Request, sample_id: str, payload: LabelPayload):
    try:
        return request.app.state.dataset_builder.label_sample(sample_id, payload.label, payload.verified)
    except KeyError:
        raise HTTPException(status_code=404, detail="sample not found")


@router.get("/dataset/samples/{sample_id}/image")
def sample_image(request: Request, sample_id: str):
    samples = request.app.state.dataset_builder.list_samples(limit=10000)
    found = next((s for s in samples if s["sample_id"] == sample_id), None)
    if not found:
        raise HTTPException(status_code=404, detail="sample not found")
    p = Path(found["image_path"])
    if not p.exists():
        raise HTTPException(status_code=404, detail="image not found")
    return FileResponse(p)


@router.get("/review-queue")
def review_queue(request: Request, limit: int = 100):
    return {"samples": request.app.state.dataset_builder.list_samples(limit=limit, review_only=True)}
