from __future__ import annotations

import glob
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator

import cv2
import numpy as np

from .utils import now_iso


@dataclass
class FramePacket:
    frame: np.ndarray
    frame_id: int
    timestamp: str
    source_type: str
    source_ref: str


class CameraOpenError(RuntimeError):
    pass


class BaseSource:
    def frames(self) -> Iterator[FramePacket]:
        raise NotImplementedError

    def close(self) -> None:
        pass


def list_video_devices() -> list[str]:
    return sorted(glob.glob('/dev/video*'))


class CameraSource(BaseSource):
    def __init__(self, cfg: dict):
        source = cfg.get('source', {})
        self.camera_device = source.get('camera_device')
        self.camera_index = int(source.get('camera_index', 0))
        self.width = int(source.get('width', 1280) or 0)
        self.height = int(source.get('height', 720) or 0)
        self.fps = int(source.get('fps', 15) or 0)
        self.warmup_frames = int(source.get('warmup_frames', 5) or 0)
        self.max_frames = int(source.get('max_frames', 0) or 0)
        self.cap = None

    def open(self) -> None:
        src = self.camera_device if self.camera_device else self.camera_index
        self.cap = cv2.VideoCapture(src)
        if self.width:
            self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, self.width)
        if self.height:
            self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, self.height)
        if self.fps:
            self.cap.set(cv2.CAP_PROP_FPS, self.fps)
        if not self.cap.isOpened():
            raise CameraOpenError(f'Unable to open camera source: {src!r}. Available devices: {list_video_devices()}')
        for _ in range(max(self.warmup_frames, 0)):
            self.cap.read()
            time.sleep(0.03)

    def frames(self) -> Iterator[FramePacket]:
        if self.cap is None:
            self.open()
        assert self.cap is not None
        idx = 0
        src = self.camera_device if self.camera_device else str(self.camera_index)
        while True:
            ok, frame = self.cap.read()
            if not ok or frame is None:
                time.sleep(0.1)
                continue
            idx += 1
            yield FramePacket(frame=frame, frame_id=idx, timestamp=now_iso(), source_type='camera', source_ref=src)
            if self.max_frames and idx >= self.max_frames:
                break

    def close(self) -> None:
        if self.cap is not None:
            self.cap.release()
            self.cap = None


class VideoFileSource(BaseSource):
    def __init__(self, cfg: dict, path: str | Path | None = None):
        source = cfg.get('source', {})
        self.path = Path(path or source.get('video_file', ''))
        self.loop = bool(source.get('loop', False))
        self.max_frames = int(source.get('max_frames', 0) or 0)
        if not self.path.exists():
            raise FileNotFoundError(f'video_file not found: {self.path}')

    def frames(self) -> Iterator[FramePacket]:
        idx = 0
        while True:
            cap = cv2.VideoCapture(str(self.path))
            if not cap.isOpened():
                raise CameraOpenError(f'Unable to open video file: {self.path}')
            while True:
                ok, frame = cap.read()
                if not ok or frame is None:
                    break
                idx += 1
                yield FramePacket(frame=frame, frame_id=idx, timestamp=now_iso(), source_type='video_file', source_ref=str(self.path))
                if self.max_frames and idx >= self.max_frames:
                    cap.release()
                    return
            cap.release()
            if not self.loop:
                return


class ImageDirSource(BaseSource):
    def __init__(self, cfg: dict, path: str | Path | None = None):
        source = cfg.get('source', {})
        self.path = Path(path or source.get('image_dir', ''))
        self.loop = bool(source.get('loop', False))
        self.max_frames = int(source.get('max_frames', 0) or 0)
        if not self.path.exists():
            raise FileNotFoundError(f'image_dir not found: {self.path}')
        exts = ('*.jpg', '*.jpeg', '*.png', '*.bmp', '*.webp')
        self.files = []
        for ext in exts:
            self.files.extend(self.path.glob(ext))
        self.files = sorted(self.files)
        if not self.files:
            raise FileNotFoundError(f'No images found in {self.path}')

    def frames(self) -> Iterator[FramePacket]:
        idx = 0
        while True:
            for p in self.files:
                frame = cv2.imread(str(p))
                if frame is None:
                    continue
                idx += 1
                yield FramePacket(frame=frame, frame_id=idx, timestamp=now_iso(), source_type='image_dir', source_ref=str(p))
                if self.max_frames and idx >= self.max_frames:
                    return
            if not self.loop:
                return


class VideoDirSource(BaseSource):
    def __init__(self, cfg: dict):
        source = cfg.get('source', {})
        self.path = Path(source.get('video_dir', ''))
        self.loop = bool(source.get('loop', False))
        if not self.path.exists():
            raise FileNotFoundError(f'video_dir not found: {self.path}')
        exts = ('*.mp4', '*.avi', '*.mov', '*.mkv')
        self.files = []
        for ext in exts:
            self.files.extend(self.path.glob(ext))
        self.files = sorted(self.files)
        if not self.files:
            raise FileNotFoundError(f'No videos found in {self.path}')
        self.cfg = cfg

    def frames(self) -> Iterator[FramePacket]:
        while True:
            for p in self.files:
                src = VideoFileSource(self.cfg, p)
                yield from src.frames()
            if not self.loop:
                return


def make_source(cfg: dict, override_type: str | None = None, override_path: str | None = None) -> BaseSource:
    source_type = override_type or cfg.get('source', {}).get('type', 'camera')
    if source_type == 'camera':
        return CameraSource(cfg)
    if source_type == 'video_file':
        return VideoFileSource(cfg, override_path)
    if source_type == 'video_dir':
        return VideoDirSource(cfg)
    if source_type == 'image_dir':
        return ImageDirSource(cfg, override_path)
    raise ValueError(f'Unsupported source.type: {source_type}')
