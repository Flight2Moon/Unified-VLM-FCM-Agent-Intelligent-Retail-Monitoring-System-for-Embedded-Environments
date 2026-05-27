from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator


SCHEMA = r"""
CREATE TABLE IF NOT EXISTS events (
  event_id TEXT PRIMARY KEY,
  created_at TEXT NOT NULL,
  status TEXT NOT NULL,
  source_type TEXT,
  camera_id TEXT,
  trigger_level TEXT,
  event_dir TEXT NOT NULL,
  zip_path TEXT,
  result_path TEXT,
  score REAL DEFAULT 0,
  decision TEXT DEFAULT 'UNKNOWN',
  metadata_json TEXT DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS label_stats (
  label TEXT PRIMARY KEY,
  count INTEGER DEFAULT 0,
  avg_conf REAL DEFAULT 0,
  last_seen_at TEXT
);

CREATE TABLE IF NOT EXISTS detection_policy_history (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  version INTEGER,
  updated_at TEXT NOT NULL,
  policy_json TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS dataset_samples (
  sample_id TEXT PRIMARY KEY,
  task TEXT NOT NULL,
  label TEXT DEFAULT 'unknown',
  pseudo_label TEXT,
  verified INTEGER DEFAULT 0,
  trainable INTEGER DEFAULT 0,
  image_path TEXT NOT NULL,
  event_id TEXT,
  source_type TEXT,
  camera_id TEXT,
  video_name TEXT,
  bbox_json TEXT DEFAULT '[]',
  confidence REAL DEFAULT 0,
  quality_json TEXT DEFAULT '{}',
  hash TEXT,
  created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS review_queue (
  sample_id TEXT PRIMARY KEY,
  priority REAL DEFAULT 0,
  reason TEXT,
  created_at TEXT NOT NULL,
  FOREIGN KEY(sample_id) REFERENCES dataset_samples(sample_id)
);

CREATE TABLE IF NOT EXISTS edge_nodes (
  edge_id TEXT PRIMARY KEY,
  camera_id TEXT,
  status TEXT,
  policy_version INTEGER,
  source_type TEXT,
  queue_count INTEGER DEFAULT 0,
  sent_count INTEGER DEFAULT 0,
  failed_count INTEGER DEFAULT 0,
  last_event_at TEXT,
  last_heartbeat_at TEXT,
  payload_json TEXT DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS graph_memory (
  key TEXT PRIMARY KEY,
  subject_label TEXT,
  relation TEXT,
  object_label TEXT,
  count INTEGER DEFAULT 0,
  last_seen_at TEXT
);

CREATE TABLE IF NOT EXISTS model_versions (
  model_id TEXT PRIMARY KEY,
  task TEXT NOT NULL,
  version TEXT NOT NULL,
  path TEXT NOT NULL,
  metrics_json TEXT DEFAULT '{}',
  is_current INTEGER DEFAULT 0,
  created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS event_logs (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  event_id TEXT NOT NULL,
  stage TEXT NOT NULL,
  message TEXT,
  payload_json TEXT DEFAULT '{}',
  created_at TEXT NOT NULL
);
"""


class Database:
    def __init__(self, path: str):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.init()

    def connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.execute("PRAGMA synchronous=NORMAL;")
        conn.execute("PRAGMA busy_timeout=5000;")
        return conn

    def init(self) -> None:
        with self.connect() as conn:
            conn.executescript(SCHEMA)
            conn.commit()

    @contextmanager
    def session(self) -> Iterator[sqlite3.Connection]:
        conn = self.connect()
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()


def row_to_dict(row: sqlite3.Row | None) -> dict[str, Any] | None:
    if row is None:
        return None
    return {k: row[k] for k in row.keys()}


def dumps(obj: Any) -> str:
    return json.dumps(obj, ensure_ascii=False, default=str)


def loads(s: str | None, default: Any = None) -> Any:
    if not s:
        return default
    try:
        return json.loads(s)
    except Exception:
        return default
