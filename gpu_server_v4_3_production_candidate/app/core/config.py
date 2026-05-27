from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Dict

import yaml


class Settings:
    def __init__(self, config_path: str | None = None):
        self.config_path = config_path or os.environ.get("EAGER_CONFIG", "configs/server_config.yaml")
        self.data = self._load_yaml(self.config_path)
        self._apply_env_overrides()

    @staticmethod
    def _load_yaml(path: str) -> Dict[str, Any]:
        p = Path(path)
        if not p.exists():
            raise FileNotFoundError(f"Config not found: {path}")
        with p.open("r", encoding="utf-8") as f:
            return yaml.safe_load(f) or {}

    def _apply_env_overrides(self) -> None:
        profile = os.environ.get("EAGER_RUNTIME_PROFILE")
        if profile:
            self.data.setdefault("runtime", {})["profile"] = profile
        model = os.environ.get("OLLAMA_MODEL")
        if model:
            self.data.setdefault("ollama", {})["model"] = model
        base_url = os.environ.get("OLLAMA_BASE_URL")
        if base_url:
            self.data.setdefault("ollama", {})["base_url"] = base_url
        provider = os.environ.get("VLM_PROVIDER")
        if provider:
            self.data.setdefault("vlm", {})["provider"] = provider
        gemini_model = os.environ.get("GEMINI_MODEL")
        if gemini_model:
            self.data.setdefault("gemini", {})["model"] = gemini_model

    def get(self, path: str, default: Any = None) -> Any:
        cur: Any = self.data
        for part in path.split("."):
            if not isinstance(cur, dict) or part not in cur:
                return default
            cur = cur[part]
        return cur

    def section(self, name: str) -> Dict[str, Any]:
        value = self.data.get(name, {})
        return value if isinstance(value, dict) else {}

    @property
    def storage_root(self) -> Path:
        return Path(self.get("storage.root_dir", "./storage"))


def ensure_storage_dirs(settings: Settings) -> None:
    for key in ["events_dir", "logs_dir", "cache_dir", "datasets_dir", "models_dir"]:
        path = settings.get(f"storage.{key}")
        if path:
            Path(path).mkdir(parents=True, exist_ok=True)
    settings.storage_root.mkdir(parents=True, exist_ok=True)
