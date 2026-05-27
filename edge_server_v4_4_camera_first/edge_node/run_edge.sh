#!/usr/bin/env bash
set -euo pipefail

MODE="${1:-camera}"
shift || true

case "$MODE" in
  camera)
    python run_edge.py --mode camera "$@"
    ;;
  camera-test)
    python run_edge.py --camera-test "$@"
    ;;
  list-cameras)
    python run_edge.py --list-cameras
    ;;
  video-file)
    python run_edge.py --mode video_file "$@"
    ;;
  video-dir)
    python run_edge.py --mode video_dir "$@"
    ;;
  image-dir)
    python run_edge.py --mode image_dir "$@"
    ;;
  dry-camera)
    python run_edge.py --mode camera --dry-run "$@"
    ;;
  *)
    echo "Usage: $0 {camera|camera-test|list-cameras|video-file|video-dir|image-dir|dry-camera} [options]" >&2
    exit 2
    ;;
esac
