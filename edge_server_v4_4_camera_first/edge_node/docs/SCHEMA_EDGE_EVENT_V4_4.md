# Edge Event Schema v4.4

ZIP structure:

```text
event.zip
├── metadata.json
├── detections.json
├── roi_hints.json
├── manifest.json
├── frame_t.jpg
├── context_t.jpg
├── overlay/edge_overlay_t.jpg
└── crops/*.jpg
```

No `motion_candidate` entities are generated. All detections are YOLO/Ultralytics objects.

Detection object:

```json
{
  "id": "person_1",
  "type": "person",
  "label": "person",
  "bbox": [x1, y1, x2, y2],
  "confidence": 0.91,
  "source": "edge_yolo_ultralytics",
  "class_id": 0,
  "crop_path": "crops/person_1_person.jpg",
  "motion_candidate": false
}
```

BBox coordinate system: `xyxy_original_frame_pixels`.
