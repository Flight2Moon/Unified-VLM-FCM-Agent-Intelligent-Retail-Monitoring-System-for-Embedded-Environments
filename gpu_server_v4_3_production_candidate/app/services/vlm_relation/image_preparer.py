from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List

from PIL import Image, ImageDraw, ImageFont

from .utils import union_bbox


class ImagePreparer:
    def __init__(self, cfg: Dict[str, Any]):
        self.cfg = cfg

    def find_image(self, event_dir: Path, candidates: list[str]) -> Path | None:
        for name in candidates:
            for p in event_dir.rglob(name):
                if p.is_file():
                    return p
        # fallback overlay first, then any jpg
        for p in event_dir.rglob("*overlay*.jpg"):
            return p
        for p in event_dir.rglob("*.jpg"):
            return p
        return None

    def make_overlay(self, image_path: Path, entities: List[dict[str, Any]], out_path: Path) -> Path:
        img = Image.open(image_path).convert("RGB")
        draw = ImageDraw.Draw(img)
        for e in entities:
            bbox = e.get("bbox") or []
            if len(bbox) < 4:
                continue
            x1, y1, x2, y2 = map(int, bbox[:4])
            color = (255, 0, 0) if e.get("label") == "person" else (0, 255, 0)
            draw.rectangle([x1, y1, x2, y2], outline=color, width=3)
            text = f"{e.get('id')}:{e.get('label')}"
            draw.rectangle([x1, max(0, y1-18), x1+max(80, 7*len(text)), y1], fill=(0,0,0))
            draw.text((x1+2, max(0, y1-16)), text, fill=(255,255,255))
        out_path.parent.mkdir(parents=True, exist_ok=True)
        img.save(out_path, quality=90)
        return out_path

    def make_union_crops(self, event_dir: Path, base_image: Path, entities: List[dict[str, Any]], pairs: List[dict[str, Any]]) -> dict[str, str]:
        ent = {e.get("id"): e for e in entities}
        img = Image.open(base_image).convert("RGB")
        w, h = img.size
        out_dir = event_dir / "evidence" / "union"
        out_dir.mkdir(parents=True, exist_ok=True)
        outputs: dict[str, str] = {}
        for pair in pairs:
            s = ent.get(pair.get("subject_id")); o = ent.get(pair.get("object_id"))
            if not s or not o:
                continue
            sb = s.get("bbox") or []; ob = o.get("bbox") or []
            if len(sb) < 4 or len(ob) < 4:
                continue
            x1, y1, x2, y2 = union_bbox(sb, ob, pad=30)
            x1 = max(0, x1); y1 = max(0, y1); x2 = min(w, x2); y2 = min(h, y2)
            if x2 <= x1 or y2 <= y1:
                continue
            crop = img.crop((x1, y1, x2, y2))
            # draw boxes adjusted
            d = ImageDraw.Draw(crop)
            for e, color in [(s, (255,0,0)), (o, (0,255,0))]:
                b = e.get("bbox")
                bx1, by1, bx2, by2 = [int(v) for v in b]
                d.rectangle([bx1-x1, by1-y1, bx2-x1, by2-y1], outline=color, width=3)
                d.text((bx1-x1+2, max(0, by1-y1+2)), f"{e.get('id')}:{e.get('label')}", fill=(255,255,255))
            fname = f"{pair['pair_id']}.jpg".replace("/", "_")
            out_path = out_dir / fname
            crop.save(out_path, quality=92)
            outputs[pair["pair_id"]] = str(out_path)
        return outputs
