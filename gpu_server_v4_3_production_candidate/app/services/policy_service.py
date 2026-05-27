from __future__ import annotations

import copy
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict

from app.core.db import Database, dumps


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class PolicyService:
    def __init__(self, db: Database, config_policy: Dict[str, Any], storage_root: str):
        self.db = db
        self.policy_path = Path(storage_root) / "detection_policy.json"
        self.default_policy = copy.deepcopy(config_policy)
        if not self.policy_path.exists():
            self.save_policy(self.default_policy, record_history=True)

    def get_policy(self) -> Dict[str, Any]:
        if self.policy_path.exists():
            try:
                return json.loads(self.policy_path.read_text(encoding="utf-8"))
            except Exception:
                pass
        return copy.deepcopy(self.default_policy)

    def save_policy(self, policy: Dict[str, Any], record_history: bool = True) -> Dict[str, Any]:
        policy = copy.deepcopy(policy)
        policy["version"] = int(policy.get("version", 0))
        policy["updated_at"] = now_iso()
        self.policy_path.parent.mkdir(parents=True, exist_ok=True)
        self.policy_path.write_text(json.dumps(policy, ensure_ascii=False, indent=2), encoding="utf-8")
        if record_history:
            with self.db.session() as conn:
                conn.execute(
                    "INSERT INTO detection_policy_history(version, updated_at, policy_json) VALUES (?, ?, ?)",
                    (policy.get("version"), policy["updated_at"], dumps(policy)),
                )
        return policy

    def update_policy(self, patch: Dict[str, Any]) -> Dict[str, Any]:
        policy = self.get_policy()
        policy.update(patch)
        policy["version"] = int(policy.get("version", 0)) + 1
        return self.save_policy(policy)

    def set_label_state(self, label: str, state: str) -> Dict[str, Any]:
        if label == "person" and state == "ignore":
            raise ValueError("person label is locked and cannot be ignored")
        policy = self.get_policy()
        for key in ["always_keep_labels", "important_labels", "ignore_labels"]:
            vals = list(dict.fromkeys(policy.get(key, [])))
            if label in vals:
                vals.remove(label)
            policy[key] = vals
        if state == "always_keep":
            policy.setdefault("always_keep_labels", []).append(label)
        elif state == "important":
            policy.setdefault("important_labels", []).append(label)
        elif state == "ignore":
            policy.setdefault("ignore_labels", []).append(label)
        elif state == "keep":
            pass
        else:
            raise ValueError(f"unknown state: {state}")
        policy["version"] = int(policy.get("version", 0)) + 1
        return self.save_policy(policy)

    def history(self, limit: int = 20) -> list[dict[str, Any]]:
        with self.db.session() as conn:
            rows = conn.execute(
                "SELECT id, version, updated_at, policy_json FROM detection_policy_history ORDER BY id DESC LIMIT ?",
                (limit,),
            ).fetchall()
        out = []
        for r in rows:
            out.append({"id": r["id"], "version": r["version"], "updated_at": r["updated_at"], "policy": json.loads(r["policy_json"])})
        return out
