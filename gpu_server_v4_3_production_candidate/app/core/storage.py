from __future__ import annotations

import hashlib
import os
import shutil
from pathlib import Path
from typing import Iterable


def safe_name(name: str) -> str:
    keep = []
    for ch in name:
        if ch.isalnum() or ch in ('-', '_', '.', ':'):
            keep.append(ch)
        else:
            keep.append('_')
    return ''.join(keep)[:180]


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open('rb') as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b''):
            h.update(chunk)
    return h.hexdigest()


def dir_size_bytes(path: Path) -> int:
    total = 0
    if not path.exists():
        return 0
    for p in path.rglob('*'):
        if p.is_file():
            try:
                total += p.stat().st_size
            except OSError:
                pass
    return total


def copy_file(src: Path, dst: Path) -> None:
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dst)


def newest_file(paths: Iterable[Path]) -> Path | None:
    files = [p for p in paths if p.exists() and p.is_file()]
    if not files:
        return None
    return max(files, key=lambda p: p.stat().st_mtime)
