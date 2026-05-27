from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any

from .detector import Detection


@dataclass
class TriggerDecision:
    should_emit: bool
    level: str | None
    reason: list[str]
    signature: str


class TriggerEngine:
    def __init__(self, cfg: dict):
        tcfg = cfg.get('trigger', {})
        self.enabled = bool(tcfg.get('enabled', True))
        self.event_labels = set(tcfg.get('event_labels') or ['person'])
        self.interesting_labels = set(tcfg.get('interesting_labels') or [])
        self.min_interval = tcfg.get('min_event_interval_sec', {}) or {}
        dup = tcfg.get('duplicate_suppression', {}) or {}
        self.dup_enabled = bool(dup.get('enabled', True))
        self.dup_window = float(dup.get('window_sec', 20))
        self.last_emit_by_level: dict[str, float] = {}
        self.recent_signatures: list[tuple[float, str]] = []

    def decide(self, detections: list[Detection]) -> TriggerDecision:
        if not self.enabled:
            return TriggerDecision(False, None, ['trigger disabled'], '')
        labels = [d.label for d in detections]
        label_set = set(labels)
        counts = {label: labels.count(label) for label in sorted(label_set)}
        signature = '|'.join(f'{k}:{v}' for k, v in counts.items())
        reason: list[str] = []
        level: str | None = None
        if self.event_labels & label_set:
            level = 'L1'
            reason.append(f'target label detected: {sorted(self.event_labels & label_set)}')
        if 'person' in label_set and (self.interesting_labels & label_set):
            level = 'L2'
            reason.append(f'person with interesting object: {sorted(self.interesting_labels & label_set)}')
        if not level:
            return TriggerDecision(False, None, ['no trigger label found'], signature)
        now = time.time()
        min_sec = float(self.min_interval.get(level, 0) or 0)
        last = self.last_emit_by_level.get(level, 0)
        if now - last < min_sec:
            return TriggerDecision(False, level, [f'rate limited: {now-last:.1f}s < {min_sec:.1f}s'], signature)
        if self.dup_enabled:
            self.recent_signatures = [(ts, sig) for ts, sig in self.recent_signatures if now - ts < self.dup_window]
            if signature and any(sig == signature for _, sig in self.recent_signatures):
                return TriggerDecision(False, level, ['duplicate signature suppressed'], signature)
            self.recent_signatures.append((now, signature))
        self.last_emit_by_level[level] = now
        return TriggerDecision(True, level, reason, signature)
