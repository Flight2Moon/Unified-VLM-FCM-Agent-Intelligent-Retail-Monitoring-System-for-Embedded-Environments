from __future__ import annotations

import cv2
import numpy as np

from .detector import Detection


def draw_overlay(frame: np.ndarray, detections: list[Detection], title: str | None = None) -> np.ndarray:
    out = frame.copy()
    if title:
        cv2.putText(out, title, (10, 26), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2, cv2.LINE_AA)
    for det in detections:
        x1, y1, x2, y2 = det.bbox
        color = (60, 220, 60) if det.label == 'person' else (0, 170, 255)
        cv2.rectangle(out, (x1, y1), (x2, y2), color, 2)
        text = f'{det.id} {det.label} {det.confidence:.2f}'
        y_text = max(20, y1 - 6)
        cv2.putText(out, text, (x1, y_text), cv2.FONT_HERSHEY_SIMPLEX, 0.48, color, 1, cv2.LINE_AA)
    return out
