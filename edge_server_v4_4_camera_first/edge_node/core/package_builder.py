from __future__ import annotations

import json
import shutil
import zipfile
from collections import Counter
from pathlib import Path
from typing import Any

import cv2
import numpy as np

from .detector import Detection
from .overlay import draw_overlay
from .utils import ensure_dir, now_iso, safe_name, write_json


def _crop(frame: np.ndarray, bbox: list[int], padding_ratio: float = 0.08) -> np.ndarray:
    h, w = frame.shape[:2]
    x1, y1, x2, y2 = bbox
    bw, bh = x2 - x1, y2 - y1
    px, py = int(bw * padding_ratio), int(bh * padding_ratio)
    x1 = max(0, x1 - px)
    y1 = max(0, y1 - py)
    x2 = min(w - 1, x2 + px)
    y2 = min(h - 1, y2 + py)
    return frame[y1:y2, x1:x2].copy()


class PackageBuilder:
    def __init__(self, cfg: dict):
        self.cfg = cfg
        pcfg = cfg.get('package', {})
        self.schema_version = pcfg.get('schema_version', 'edge_event_v4.4')
        self.output_dir = Path(pcfg.get('output_dir', './data/packages'))
        self.queue_dir = ensure_dir(self.output_dir / 'queue')
        ensure_dir(self.output_dir / 'sending')
        ensure_dir(self.output_dir / 'sent')
        ensure_dir(self.output_dir / 'failed')
        self.include_overlay = bool(pcfg.get('include_overlay', True))
        self.include_crops = bool(pcfg.get('include_crops', True))
        self.crop_padding_ratio = float(pcfg.get('crop_padding_ratio', 0.08))
        self.jpeg_quality = int(pcfg.get('jpeg_quality', 92))
        self.edge_cfg = cfg.get('edge', {})
        self.source_cfg = cfg.get('source', {})
        self.motion_enabled = bool(cfg.get('motion_candidate', {}).get('enabled', False))

    def event_id(self, camera_id: str, ts: str, seq: int, level: str) -> str:
        # UTC timestamp safe for filenames: 20260530_055131
        compact = ts.replace('-', '').replace(':', '').replace('T', '_').split('.')[0]
        compact = compact.replace('+0000', '').replace('+00:00', '').replace('Z', '')
        return safe_name(f'{camera_id}_{compact}_{seq:06d}_{level}')

    def build(self, *, frame: np.ndarray, detections: list[Detection], frame_packet: Any, trigger: Any, detector_info: dict[str, Any], sequence: int) -> Path:
        camera_id = self.edge_cfg.get('camera_id', 'cam01')
        edge_id = self.edge_cfg.get('edge_id', 'edge-01')
        level = trigger.level or 'L0'
        event_id = self.event_id(camera_id, frame_packet.timestamp, sequence, level)
        work_dir = self.queue_dir / f'{event_id}__work'
        if work_dir.exists():
            shutil.rmtree(work_dir)
        ensure_dir(work_dir)
        ensure_dir(work_dir / 'overlay')
        ensure_dir(work_dir / 'crops')

        h, w = frame.shape[:2]
        frame_path = work_dir / 'frame_t.jpg'
        cv2.imwrite(str(frame_path), frame, [int(cv2.IMWRITE_JPEG_QUALITY), self.jpeg_quality])
        context_path = work_dir / 'context_t.jpg'
        cv2.imwrite(str(context_path), frame, [int(cv2.IMWRITE_JPEG_QUALITY), self.jpeg_quality])

        overlay_rel = None
        if self.include_overlay:
            overlay = draw_overlay(frame, detections, title=f'{event_id} {level}')
            overlay_rel = 'overlay/edge_overlay_t.jpg'
            cv2.imwrite(str(work_dir / overlay_rel), overlay, [int(cv2.IMWRITE_JPEG_QUALITY), self.jpeg_quality])

        det_dicts: list[dict[str, Any]] = []
        for det in detections:
            det_copy = Detection(**{**det.__dict__})
            if self.include_crops:
                crop = _crop(frame, det.bbox, self.crop_padding_ratio)
                crop_name = safe_name(f'{det.id}_{det.label}.jpg')
                crop_rel = f'crops/{crop_name}'
                if crop.size > 0:
                    cv2.imwrite(str(work_dir / crop_rel), crop, [int(cv2.IMWRITE_JPEG_QUALITY), self.jpeg_quality])
                    det_copy.crop_path = crop_rel
            det_dicts.append(det_copy.to_dict())

        object_counts = dict(Counter(d['label'] for d in det_dicts))
        detections_json = {
            'schema_version': self.schema_version,
            'event_id': event_id,
            'detections': det_dicts,
            'object_counts': object_counts,
            'bbox_format': 'xyxy_original_frame_pixels',
            'frame_width': w,
            'frame_height': h,
            'motion_candidate_enabled': False,
        }
        write_json(work_dir / 'detections.json', detections_json)

        # Backward-compatible roi_hints.json for older GPU server code paths.
        roi_hints = {
            'schema_version': self.schema_version,
            'event_id': event_id,
            'entities': det_dicts,
            'detections': det_dicts,
            'object_counts': object_counts,
            'motion_candidate_enabled': False,
        }
        write_json(work_dir / 'roi_hints.json', roi_hints)

        metadata = {
            'schema_version': self.schema_version,
            'event_id': event_id,
            'edge_id': edge_id,
            'camera_id': camera_id,
            'created_at': now_iso(),
            'captured_at': frame_packet.timestamp,
            'source_type': frame_packet.source_type,
            'source_ref': frame_packet.source_ref,
            'trigger_level': level,
            'trigger_reason': list(trigger.reason),
            'trigger_signature': trigger.signature,
            'frame': {'path': 'frame_t.jpg', 'width': w, 'height': h},
            'context': {'path': 'context_t.jpg', 'width': w, 'height': h},
            'overlay': {'path': overlay_rel} if overlay_rel else None,
            'detections_path': 'detections.json',
            'roi_hints_path': 'roi_hints.json',
            'crops_dir': 'crops',
            'object_counts': object_counts,
            'detector': detector_info,
            'motion_candidate_enabled': False,
            'upload': {'retry_count': 0, 'last_error': None, 'last_attempt_at': None},
        }
        write_json(work_dir / 'metadata.json', metadata)

        files = []
        for p in sorted(work_dir.rglob('*')):
            if p.is_file():
                files.append(str(p.relative_to(work_dir)))
        manifest = {
            'schema_version': self.schema_version,
            'event_id': event_id,
            'created_at': now_iso(),
            'files': files,
        }
        write_json(work_dir / 'manifest.json', manifest)

        zip_path = self.queue_dir / f'{event_id}.zip'
        with zipfile.ZipFile(zip_path, 'w', compression=zipfile.ZIP_DEFLATED) as zf:
            for p in sorted(work_dir.rglob('*')):
                if p.is_file():
                    zf.write(p, p.relative_to(work_dir).as_posix())
        shutil.rmtree(work_dir)
        return zip_path
