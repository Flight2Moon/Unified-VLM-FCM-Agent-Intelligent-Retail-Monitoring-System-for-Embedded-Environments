from __future__ import annotations

import json
import shutil
import time
import zipfile
from pathlib import Path
from typing import Any

import requests

from .utils import env_or_none, now_iso, read_json, write_json


class EventUploader:
    def __init__(self, cfg: dict):
        self.cfg = cfg
        server = cfg.get('server', {})
        uploader = cfg.get('uploader', {})
        self.base_url = str(server.get('base_url', 'http://127.0.0.1:8008')).rstrip('/')
        self.event_endpoint = server.get('event_endpoint', '/api/events')
        self.heartbeat_endpoint = server.get('heartbeat_endpoint', '/api/edge/heartbeat')
        self.timeout_sec = float(server.get('timeout_sec', 15))
        self.verify_tls = bool(server.get('verify_tls', False))
        self.api_key = env_or_none(server.get('edge_api_key_env'))
        self.max_retry = int(uploader.get('max_retry', 5) or 5)
        self.retry_backoff_sec = float(uploader.get('retry_backoff_sec', 5) or 5)
        self.max_upload_per_flush = int(uploader.get('max_upload_per_flush', 3) or 3)
        self.keep_sent = bool(uploader.get('keep_sent', True))
        out = Path(cfg.get('package', {}).get('output_dir', './data/packages'))
        self.queue_dir = out / 'queue'
        self.sending_dir = out / 'sending'
        self.sent_dir = out / 'sent'
        self.failed_dir = out / 'failed'
        for d in [self.queue_dir, self.sending_dir, self.sent_dir, self.failed_dir]:
            d.mkdir(parents=True, exist_ok=True)

    def _headers(self) -> dict[str, str]:
        headers = {}
        if self.api_key:
            headers['X-Edge-Api-Key'] = self.api_key
        return headers

    def health(self) -> bool:
        try:
            r = requests.get(self.base_url.rstrip('/') + '/', timeout=self.timeout_sec, verify=self.verify_tls)
            return r.status_code < 500
        except Exception:
            return False

    def heartbeat(self, payload: dict[str, Any]) -> tuple[bool, str | None]:
        url = self.base_url + self.heartbeat_endpoint
        try:
            r = requests.post(url, json=payload, headers=self._headers(), timeout=self.timeout_sec, verify=self.verify_tls)
            if 200 <= r.status_code < 300:
                return True, None
            return False, f'heartbeat status={r.status_code}: {r.text[:300]}'
        except Exception as exc:
            return False, str(exc)

    def _read_zip_metadata(self, zip_path: Path) -> dict[str, Any]:
        try:
            with zipfile.ZipFile(zip_path, 'r') as zf:
                with zf.open('metadata.json') as f:
                    return json.loads(f.read().decode('utf-8'))
        except Exception:
            return {}

    def _update_zip_metadata_upload(self, zip_path: Path, retry_count: int, last_error: str | None) -> None:
        # Rewriting the zip just for upload metadata is intentionally skipped for speed.
        # A sidecar file is enough for retry bookkeeping.
        sidecar = zip_path.with_suffix('.upload.json')
        write_json(sidecar, {'retry_count': retry_count, 'last_error': last_error, 'last_attempt_at': now_iso()})

    def _sidecar_retry_count(self, zip_path: Path) -> int:
        data = read_json(zip_path.with_suffix('.upload.json'), {}) or {}
        return int(data.get('retry_count', 0) or 0)

    def upload_one(self, zip_path: Path) -> tuple[bool, str | None]:
        url = self.base_url + self.event_endpoint
        try:
            with open(zip_path, 'rb') as f:
                files = {'file': (zip_path.name, f, 'application/zip')}
                r = requests.post(url, files=files, headers=self._headers(), timeout=self.timeout_sec, verify=self.verify_tls)
            if 200 <= r.status_code < 300:
                return True, None
            return False, f'upload status={r.status_code}: {r.text[:500]}'
        except Exception as exc:
            return False, str(exc)

    def flush_queue(self) -> dict[str, int]:
        result = {'attempted': 0, 'sent': 0, 'failed': 0, 'requeued': 0}
        for zip_path in sorted(self.queue_dir.glob('*.zip'))[: self.max_upload_per_flush]:
            result['attempted'] += 1
            sending_path = self.sending_dir / zip_path.name
            sidecar = zip_path.with_suffix('.upload.json')
            sending_sidecar = sending_path.with_suffix('.upload.json')
            if sending_path.exists():
                sending_path.unlink()
            shutil.move(str(zip_path), str(sending_path))
            if sidecar.exists():
                shutil.move(str(sidecar), str(sending_sidecar))
            ok, err = self.upload_one(sending_path)
            if ok:
                result['sent'] += 1
                dest = self.sent_dir / sending_path.name
                if self.keep_sent:
                    shutil.move(str(sending_path), str(dest))
                    if sending_sidecar.exists():
                        sending_sidecar.unlink()
                else:
                    sending_path.unlink(missing_ok=True)
                    sending_sidecar.unlink(missing_ok=True)
            else:
                retry_count = self._sidecar_retry_count(sending_path) + 1
                self._update_zip_metadata_upload(sending_path, retry_count, err)
                if retry_count > self.max_retry:
                    result['failed'] += 1
                    shutil.move(str(sending_path), str(self.failed_dir / sending_path.name))
                    if sending_sidecar.exists():
                        shutil.move(str(sending_sidecar), str((self.failed_dir / sending_path.name).with_suffix('.upload.json')))
                else:
                    result['requeued'] += 1
                    time.sleep(min(self.retry_backoff_sec, 1.0))
                    shutil.move(str(sending_path), str(self.queue_dir / sending_path.name))
                    if sending_sidecar.exists():
                        shutil.move(str(sending_sidecar), str((self.queue_dir / sending_path.name).with_suffix('.upload.json')))
        return result

    def counts(self) -> dict[str, int]:
        return {
            'queue': len(list(self.queue_dir.glob('*.zip'))),
            'sending': len(list(self.sending_dir.glob('*.zip'))),
            'sent': len(list(self.sent_dir.glob('*.zip'))),
            'failed': len(list(self.failed_dir.glob('*.zip'))),
        }
