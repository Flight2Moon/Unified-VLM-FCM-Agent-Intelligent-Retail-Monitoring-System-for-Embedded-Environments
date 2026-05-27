# Edge Server v4.4 Camera-First

This version is designed to make the camera work first, then detection/upload.
It does not create or transmit motion candidates.

## 1. Install

```bash
cd edge_node
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
# For real detection:
pip install ultralytics
```

## 2. Check cameras first

```bash
./run_edge.sh list-cameras
./run_edge.sh camera-test --camera-index 0
```

The camera test saves snapshots to:

```text
data/frames/camera_test/
```

If those images are black, the issue is camera device/exposure/lighting, not GPU Server.

## 3. Run with camera and no upload

```bash
./run_edge.sh dry-camera --camera-index 0 --detector none --force-event --once
```

This verifies capture and packaging without YOLO or server upload.

## 4. Run with camera + YOLO + upload

Edit `config.yaml`:

```yaml
server:
  base_url: "http://GPU_SERVER_IP:8008"
object_detection:
  backend: "ultralytics"
  model_path: "yolov8n.pt"
  device: "cuda:0"  # or cpu
```

Then:

```bash
export EDGE_API_KEY="same_key_as_gpu_server"
./run_edge.sh camera --camera-index 0
```

## 5. Replay video or image directory

```bash
./run_edge.sh video-file --path ./data/samples/sample.mp4 --once
./run_edge.sh image-dir --path ./data/samples/images --once
```

## Important behavior

- Default source is `camera`, not demo.
- There is no synthetic scene generator.
- Detector backend `none` only emits packages if trigger rules are satisfied; because no objects are detected, it is mainly for camera diagnosis.
- Motion candidates are always disabled in v4.4.
