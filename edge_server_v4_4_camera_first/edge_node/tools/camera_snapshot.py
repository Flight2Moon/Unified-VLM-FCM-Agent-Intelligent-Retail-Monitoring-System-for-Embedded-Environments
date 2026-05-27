from __future__ import annotations
import argparse
from pathlib import Path
import cv2

p = argparse.ArgumentParser()
p.add_argument('--index', type=int, default=0)
p.add_argument('--device', default=None)
p.add_argument('--width', type=int, default=1280)
p.add_argument('--height', type=int, default=720)
p.add_argument('--count', type=int, default=10)
p.add_argument('--out', default='./data/frames/manual_snapshot')
args = p.parse_args()
Path(args.out).mkdir(parents=True, exist_ok=True)
src = args.device if args.device else args.index
cap = cv2.VideoCapture(src)
cap.set(cv2.CAP_PROP_FRAME_WIDTH, args.width)
cap.set(cv2.CAP_PROP_FRAME_HEIGHT, args.height)
if not cap.isOpened():
    raise SystemExit(f'Unable to open camera: {src!r}')
for i in range(1, args.count + 1):
    ok, frame = cap.read()
    if not ok or frame is None:
        print(f'frame {i}: failed')
        continue
    path = Path(args.out) / f'snapshot_{i:03d}.jpg'
    cv2.imwrite(str(path), frame)
    print(f'frame {i}: {frame.shape} -> {path}')
cap.release()
