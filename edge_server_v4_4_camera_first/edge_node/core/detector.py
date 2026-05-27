from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from typing import Any

import numpy as np


@dataclass
class Detection:
    id: str
    type: str
    label: str
    bbox: list[int]
    confidence: float
    source: str
    class_id: int | None = None
    track_id: int | None = None
    crop_path: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            'id': self.id,
            'type': self.type,
            'label': self.label,
            'bbox': self.bbox,
            'confidence': round(float(self.confidence), 6),
            'source': self.source,
            'class_id': self.class_id,
            'track_id': self.track_id,
            'crop_path': self.crop_path,
            'motion_candidate': False,
        }


class BaseDetector:
    def detect(self, frame: np.ndarray) -> list[Detection]:
        raise NotImplementedError

    def info(self) -> dict[str, Any]:
        raise NotImplementedError


class NoOpDetector(BaseDetector):
    def __init__(self, cfg: dict):
        self.cfg = cfg

    def detect(self, frame: np.ndarray) -> list[Detection]:
        return []

    def info(self) -> dict[str, Any]:
        return {'backend': 'none', 'model_path': None, 'device': None}


class UltralyticsDetector(BaseDetector):
    def __init__(self, cfg: dict):
        det = cfg.get('object_detection', {})
        self.model_path = det.get('model_path', 'yolov8n.pt')
        self.device = det.get('device', 'cpu')
        self.min_confidence = float(det.get('min_confidence', 0.35))
        self.iou = float(det.get('iou', 0.45))
        self.imgsz = int(det.get('imgsz', 640))
        self.allowed_labels = set(det.get('allowed_labels') or [])
        self.max_objects = int(det.get('max_objects_per_event', 30) or 30)
        try:
            from ultralytics import YOLO
        except Exception as exc:
            raise RuntimeError(
                'Ultralytics is not installed. Install it with `pip install ultralytics`, '
                'or set object_detection.backend: "none" for camera-only diagnosis.'
            ) from exc
        self.model = YOLO(self.model_path)

    def detect(self, frame: np.ndarray) -> list[Detection]:
        results = self.model.predict(frame, conf=self.min_confidence, iou=self.iou, imgsz=self.imgsz, device=self.device, verbose=False)
        if not results:
            return []
        result = results[0]
        names = result.names or getattr(self.model, 'names', {}) or {}
        detections: list[Detection] = []
        label_counts: dict[str, int] = defaultdict(int)
        boxes = getattr(result, 'boxes', None)
        if boxes is None:
            return []
        for box in boxes:
            xyxy = box.xyxy[0].detach().cpu().numpy().tolist()
            conf = float(box.conf[0].detach().cpu().item()) if box.conf is not None else 0.0
            cls = int(box.cls[0].detach().cpu().item()) if box.cls is not None else None
            label = str(names.get(cls, cls)) if cls is not None else 'object'
            if self.allowed_labels and label not in self.allowed_labels:
                continue
            if conf < self.min_confidence:
                continue
            x1, y1, x2, y2 = [int(round(v)) for v in xyxy]
            h, w = frame.shape[:2]
            x1, y1 = max(0, x1), max(0, y1)
            x2, y2 = min(w - 1, x2), min(h - 1, y2)
            if x2 <= x1 or y2 <= y1:
                continue
            label_counts[label] += 1
            object_id = f'{label}_{label_counts[label]}'.replace(' ', '_')
            obj_type = 'person' if label == 'person' else 'object'
            detections.append(Detection(
                id=object_id,
                type=obj_type,
                label=label,
                bbox=[x1, y1, x2, y2],
                confidence=conf,
                source='edge_yolo_ultralytics',
                class_id=cls,
            ))
            if len(detections) >= self.max_objects:
                break
        return detections

    def info(self) -> dict[str, Any]:
        return {
            'backend': 'ultralytics',
            'model_path': self.model_path,
            'device': self.device,
            'min_confidence': self.min_confidence,
            'iou': self.iou,
            'imgsz': self.imgsz,
        }


def make_detector(cfg: dict) -> BaseDetector:
    backend = cfg.get('object_detection', {}).get('backend', 'ultralytics')
    if backend == 'ultralytics':
        return UltralyticsDetector(cfg)
    if backend == 'none':
        return NoOpDetector(cfg)
    raise ValueError(f'Unsupported object_detection.backend: {backend}')
