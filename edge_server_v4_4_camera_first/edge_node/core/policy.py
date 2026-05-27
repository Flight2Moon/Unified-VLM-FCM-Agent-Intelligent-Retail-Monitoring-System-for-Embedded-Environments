from __future__ import annotations

import requests


class PolicyClient:
    def __init__(self, cfg: dict):
        self.cfg = cfg
        server = cfg.get('server', {})
        self.base_url = str(server.get('base_url', 'http://127.0.0.1:8008')).rstrip('/')
        self.endpoint = server.get('detection_policy_endpoint', '/api/detection-policy')
        self.timeout = float(server.get('timeout_sec', 15))
        self.verify_tls = bool(server.get('verify_tls', False))
        self.last_policy = None

    def fetch(self) -> dict | None:
        try:
            r = requests.get(self.base_url + self.endpoint, timeout=self.timeout, verify=self.verify_tls)
            if 200 <= r.status_code < 300:
                self.last_policy = r.json()
                return self.last_policy
        except Exception:
            return None
        return None

    def apply_to_config(self, policy: dict | None) -> None:
        if not policy:
            return
        det_cfg = self.cfg.setdefault('object_detection', {})
        # Accept flexible server policy shapes.
        allowed = policy.get('allowed_labels') or policy.get('allowed_objects') or policy.get('labels')
        if allowed:
            det_cfg['allowed_labels'] = list(allowed)
        min_conf = policy.get('min_confidence')
        if min_conf is not None:
            det_cfg['min_confidence'] = float(min_conf)
        # Never re-enable motion candidates in v4.4 camera-first edge.
        self.cfg.setdefault('motion_candidate', {})['enabled'] = False
