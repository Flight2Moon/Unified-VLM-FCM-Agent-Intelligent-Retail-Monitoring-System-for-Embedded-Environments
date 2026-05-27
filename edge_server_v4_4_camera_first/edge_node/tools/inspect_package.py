from __future__ import annotations
import argparse, json, zipfile
from pathlib import Path
p = argparse.ArgumentParser()
p.add_argument('zip_path')
args = p.parse_args()
with zipfile.ZipFile(args.zip_path, 'r') as zf:
    print('FILES')
    for name in zf.namelist():
        print(' -', name)
    for name in ['metadata.json','detections.json','manifest.json']:
        if name in zf.namelist():
            print('\n##', name)
            print(json.dumps(json.loads(zf.read(name).decode('utf-8')), ensure_ascii=False, indent=2)[:4000])
