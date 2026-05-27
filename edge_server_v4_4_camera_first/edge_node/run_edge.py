from __future__ import annotations

import argparse
import signal
import sys
import time
from pathlib import Path

import cv2

from core.camera import CameraOpenError, make_source, list_video_devices
from core.detector import make_detector
from core.package_builder import PackageBuilder
from core.policy import PolicyClient
from core.status import EdgeStats, StatusWriter
from core.triggers import TriggerEngine
from core.uploader import EventUploader
from core.utils import load_yaml, now_iso

RUNNING = True


def _handle_signal(signum, frame):
    global RUNNING
    RUNNING = False


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description='Edge Server v4.4 camera-first event packager')
    p.add_argument('--config', default='config.yaml')
    p.add_argument('--mode', choices=['camera', 'video_file', 'video_dir', 'image_dir'], default=None, help='Override source.type')
    p.add_argument('--path', default=None, help='Override video_file or image_dir path')
    p.add_argument('--camera-index', type=int, default=None, help='Override source.camera_index')
    p.add_argument('--camera-device', default=None, help='Override source.camera_device, e.g. /dev/video0')
    p.add_argument('--detector', choices=['ultralytics', 'none'], default=None, help='Override object_detection.backend')
    p.add_argument('--device', default=None, help='Override YOLO device, e.g. cpu or cuda:0')
    p.add_argument('--once', action='store_true', help='Process one emitted event then exit')
    p.add_argument('--dry-run', action='store_true', help='Create packages but do not upload')
    p.add_argument('--camera-test', action='store_true', help='Only test camera capture and save snapshots')
    p.add_argument('--list-cameras', action='store_true')
    p.add_argument('--save-every-frame', action='store_true', help='Save raw frames to data/frames for diagnosis')
    p.add_argument('--force-event', action='store_true', help='Package the next frame even if no YOLO trigger is detected; useful for camera/upload diagnosis')
    return p.parse_args()


def apply_overrides(cfg: dict, args: argparse.Namespace) -> dict:
    cfg = dict(cfg)
    cfg.setdefault('source', {})
    cfg.setdefault('object_detection', {})
    if args.mode:
        cfg['source']['type'] = args.mode
    if args.path:
        if (args.mode or cfg['source'].get('type')) == 'image_dir':
            cfg['source']['image_dir'] = args.path
        elif (args.mode or cfg['source'].get('type')) == 'video_file':
            cfg['source']['video_file'] = args.path
    if args.camera_index is not None:
        cfg['source']['camera_index'] = args.camera_index
        cfg['source']['camera_device'] = None
    if args.camera_device:
        cfg['source']['camera_device'] = args.camera_device
    if args.detector:
        cfg['object_detection']['backend'] = args.detector
    if args.device:
        cfg['object_detection']['device'] = args.device
    # v4.4 hard policy: no motion candidate.
    cfg.setdefault('motion_candidate', {})['enabled'] = False
    return cfg


def run_camera_test(cfg: dict, args: argparse.Namespace) -> int:
    cfg = apply_overrides(cfg, args)
    cfg['source']['type'] = 'camera'
    cfg.setdefault('source', {})['max_frames'] = max(int(cfg.get('source', {}).get('max_frames', 0) or 0), 10)
    out_dir = Path('./data/frames/camera_test')
    out_dir.mkdir(parents=True, exist_ok=True)
    print('[camera-test] available devices:', list_video_devices())
    try:
        src = make_source(cfg, 'camera')
        for i, pkt in enumerate(src.frames(), start=1):
            path = out_dir / f'camera_test_{i:03d}.jpg'
            cv2.imwrite(str(path), pkt.frame)
            print(f'[camera-test] captured frame {i}: shape={pkt.frame.shape} saved={path}')
            if i >= 10:
                break
        src.close()
        print('[camera-test] OK. If images are black, check lighting/exposure/device index.')
        return 0
    except Exception as exc:
        print(f'[camera-test] FAILED: {exc}', file=sys.stderr)
        return 2


def main() -> int:
    signal.signal(signal.SIGINT, _handle_signal)
    signal.signal(signal.SIGTERM, _handle_signal)
    args = parse_args()
    if args.list_cameras:
        print('\n'.join(list_video_devices()) or 'No /dev/video* devices found')
        return 0
    cfg = load_yaml(args.config)
    if args.camera_test:
        return run_camera_test(cfg, args)
    cfg = apply_overrides(cfg, args)

    source = make_source(cfg)
    detector = make_detector(cfg)
    detector_info = detector.info()
    trigger_engine = TriggerEngine(cfg)
    builder = PackageBuilder(cfg)
    uploader = EventUploader(cfg)
    status_writer = StatusWriter(cfg)
    policy_client = PolicyClient(cfg)
    stats = EdgeStats()

    runtime = cfg.get('runtime', {})
    heartbeat_interval = float(runtime.get('heartbeat_interval_sec', 10))
    upload_flush_interval = float(runtime.get('upload_flush_interval_sec', 5))
    policy_sync_interval = float(runtime.get('policy_sync_interval_sec', 30))
    status_interval = float(runtime.get('status_write_interval_sec', 3))
    sleep_sec = float(runtime.get('sleep_sec', 0.01))
    uploader_enabled = bool(cfg.get('uploader', {}).get('enabled', True)) and not args.dry_run

    last_hb = last_flush = last_policy = last_status = 0.0
    emitted = 0
    sequence = 0

    print('[edge] starting camera-first edge node')
    print('[edge] source:', cfg.get('source', {}))
    print('[edge] detector:', detector_info)
    print('[edge] dry_run:', args.dry_run)
    print('[edge] motion_candidate_enabled: false')

    try:
        for pkt in source.frames():
            if not RUNNING:
                break
            now = time.time()
            if now - last_policy >= policy_sync_interval:
                policy = policy_client.fetch()
                if policy:
                    policy_client.apply_to_config(policy)
                    print('[edge] policy synced')
                last_policy = now

            detections = detector.detect(pkt.frame)
            decision = trigger_engine.decide(detections)
            if args.force_event and not decision.should_emit:
                from core.triggers import TriggerDecision
                decision = TriggerDecision(True, 'L0', ['force_event diagnosis package'], 'force_event')

            if args.save_every_frame:
                raw_dir = Path('./data/frames/raw')
                raw_dir.mkdir(parents=True, exist_ok=True)
                cv2.imwrite(str(raw_dir / f'frame_{pkt.frame_id:06d}.jpg'), pkt.frame)

            if decision.should_emit:
                sequence += 1
                zip_path = builder.build(
                    frame=pkt.frame,
                    detections=detections,
                    frame_packet=pkt,
                    trigger=decision,
                    detector_info=detector_info,
                    sequence=sequence,
                )
                stats.created_count += 1
                stats.last_event_id = zip_path.stem
                stats.last_event_at = now_iso()
                emitted += 1
                print(f'[edge] package queued: {zip_path.name} detections={len(detections)} level={decision.level}')
            else:
                stats.skipped_count += 1

            if uploader_enabled and now - last_flush >= upload_flush_interval:
                res = uploader.flush_queue()
                stats.sent_count += res.get('sent', 0)
                stats.failed_count += res.get('failed', 0)
                if res.get('attempted'):
                    print('[edge] upload flush:', res)
                last_flush = now

            counts = uploader.counts()
            if now - last_hb >= heartbeat_interval:
                payload = status_writer.snapshot(stats=stats, detector_info=detector_info, queue_count=counts['queue'], failed_queue_count=counts['failed'])
                if uploader_enabled:
                    ok, err = uploader.heartbeat(payload)
                    if not ok:
                        stats.last_error = err
                        print('[edge] heartbeat failed:', err)
                last_hb = now

            if now - last_status >= status_interval:
                payload = status_writer.snapshot(stats=stats, detector_info=detector_info, queue_count=counts['queue'], failed_queue_count=counts['failed'])
                status_writer.write(payload)
                last_status = now

            if args.once and emitted >= 1:
                if uploader_enabled:
                    res = uploader.flush_queue()
                    stats.sent_count += res.get('sent', 0)
                    stats.failed_count += res.get('failed', 0)
                break
            time.sleep(sleep_sec)
    except CameraOpenError as exc:
        stats.last_error = str(exc)
        print('[edge] camera error:', exc, file=sys.stderr)
        return 3
    except Exception as exc:
        stats.last_error = str(exc)
        print('[edge] fatal error:', exc, file=sys.stderr)
        return 4
    finally:
        try:
            source.close()
        except Exception:
            pass
        counts = uploader.counts()
        payload = status_writer.snapshot(stats=stats, detector_info=detector_info, queue_count=counts['queue'], failed_queue_count=counts['failed'], status='stopped')
        status_writer.write(payload)
        print('[edge] stopped')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
