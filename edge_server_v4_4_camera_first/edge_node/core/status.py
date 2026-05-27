from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .utils import now_iso, write_json


@dataclass
class EdgeStats:
    created_count: int = 0
    sent_count: int = 0
    failed_count: int = 0
    skipped_count: int = 0
    last_event_id: str | None = None
    last_event_at: str | None = None
    last_error: str | None = None
    started_at: str = field(default_factory=now_iso)


class StatusWriter:
    def __init__(self, cfg: dict):
        self.path = Path('./data/status/edge_status.json')
        self.edge_cfg = cfg.get('edge', {})
        self.source_cfg = cfg.get('source', {})
        self.motion_enabled = bool(cfg.get('motion_candidate', {}).get('enabled', False))

    def snapshot(self, *, stats: EdgeStats, detector_info: dict[str, Any], queue_count: int, failed_queue_count: int, status: str = 'running') -> dict[str, Any]:
        return {
            'edge_id': self.edge_cfg.get('edge_id', 'edge-01'),
            'camera_id': self.edge_cfg.get('camera_id', 'cam01'),
            'status': status,
            'updated_at': now_iso(),
            'started_at': stats.started_at,
            'source_type': self.source_cfg.get('type', 'camera'),
            'queue_count': queue_count,
            'failed_queue_count': failed_queue_count,
            'created_count': stats.created_count,
            'sent_count': stats.sent_count,
            'failed_count': stats.failed_count,
            'skipped_count': stats.skipped_count,
            'last_event_id': stats.last_event_id,
            'last_event_at': stats.last_event_at,
            'last_error': stats.last_error,
            'motion_candidate_enabled': self.motion_enabled,
            'detector': detector_info,
        }

    def write(self, payload: dict[str, Any]) -> None:
        write_json(self.path, payload)
