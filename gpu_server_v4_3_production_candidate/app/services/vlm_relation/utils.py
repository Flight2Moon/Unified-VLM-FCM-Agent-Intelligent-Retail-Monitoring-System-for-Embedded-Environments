from __future__ import annotations

from math import sqrt
from typing import Sequence


def bbox_center(b: Sequence[float]) -> tuple[float, float]:
    return ((float(b[0]) + float(b[2])) / 2, (float(b[1]) + float(b[3])) / 2)


def bbox_area(b: Sequence[float]) -> float:
    return max(0.0, float(b[2]) - float(b[0])) * max(0.0, float(b[3]) - float(b[1]))


def bbox_iou(a: Sequence[float], b: Sequence[float]) -> float:
    x1 = max(float(a[0]), float(b[0])); y1 = max(float(a[1]), float(b[1]))
    x2 = min(float(a[2]), float(b[2])); y2 = min(float(a[3]), float(b[3]))
    inter = max(0.0, x2-x1) * max(0.0, y2-y1)
    union = bbox_area(a) + bbox_area(b) - inter
    return inter / union if union > 0 else 0.0


def center_distance(a: Sequence[float], b: Sequence[float]) -> float:
    ax, ay = bbox_center(a); bx, by = bbox_center(b)
    return sqrt((ax-bx)**2 + (ay-by)**2)


def union_bbox(a: Sequence[float], b: Sequence[float], pad: int = 20) -> list[int]:
    return [int(min(a[0], b[0])-pad), int(min(a[1], b[1])-pad), int(max(a[2], b[2])+pad), int(max(a[3], b[3])+pad)]
