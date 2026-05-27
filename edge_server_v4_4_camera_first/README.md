# Edge Server v4.4 Camera-First Production Candidate

This project is an Edge-side event packager for GPU Server v4.3+.

Main goals:
- Camera-first operation: verify camera, capture real frames, then run detection.
- YOLO-only event packaging: no motion candidate generation.
- GPU Server compatible event ZIP schema.
- Heartbeat + upload retry queue.
- Video file / video directory / image directory replay modes are still supported.

See `edge_node/README_EDGE.md` for setup and commands.
