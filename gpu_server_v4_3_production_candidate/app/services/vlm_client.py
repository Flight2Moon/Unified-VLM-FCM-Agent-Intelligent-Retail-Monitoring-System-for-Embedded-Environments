from __future__ import annotations

import base64
import json
import os
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

import requests


class BaseVLMProvider:
    name = "base"

    def __init__(self, cfg: Dict[str, Any], runtime_profile: str = "low_vram"):
        self.cfg = cfg
        self.runtime_profile = runtime_profile
        self.model = cfg.get("model", "unknown")
        self.timeout = float(cfg.get("timeout_sec", 120))

    def health(self) -> dict[str, Any]:
        return {"ok": True, "provider": self.name, "model": self.model}

    def generate(self, prompt: str, image_paths: Optional[List[str | Path]] = None, schema: Optional[dict[str, Any]] = None, model: Optional[str] = None) -> dict[str, Any]:
        raise NotImplementedError

    @staticmethod
    def encode_image(path: str | Path) -> str:
        data = Path(path).read_bytes()
        return base64.b64encode(data).decode("ascii")


class OffVLMProvider(BaseVLMProvider):
    name = "off"

    def __init__(self, cfg: Dict[str, Any], runtime_profile: str = "low_vram"):
        super().__init__(cfg, runtime_profile)
        self.model = "off"

    def health(self) -> dict[str, Any]:
        return {"ok": True, "provider": self.name, "model": self.model, "message": "VLM disabled; geometry-only mode"}

    def generate(self, prompt: str, image_paths: Optional[List[str | Path]] = None, schema: Optional[dict[str, Any]] = None, model: Optional[str] = None) -> dict[str, Any]:
        return {"ok": False, "provider": self.name, "model": self.model, "response": "", "error": "VLM provider is off"}


class OllamaProvider(BaseVLMProvider):
    name = "ollama"

    def __init__(self, cfg: Dict[str, Any], runtime_profile: str = "low_vram"):
        super().__init__(cfg, runtime_profile)
        self.base_url = cfg.get("base_url", "http://localhost:11434").rstrip("/")
        self.model = cfg.get("model", "gemma4:e4b")

    def health(self) -> dict[str, Any]:
        try:
            r = requests.get(self.base_url + "/api/tags", timeout=8)
            return {"ok": r.ok, "provider": self.name, "status_code": r.status_code, "model": self.model, "data": r.json() if r.content else None}
        except Exception as e:
            return {"ok": False, "provider": self.name, "model": self.model, "error": str(e)}

    def _options(self) -> Dict[str, Any]:
        options = {
            "temperature": float(self.cfg.get("temperature", 0.0)),
            "num_predict": int(self.cfg.get("num_predict", 512)),
            "num_ctx": int(self.cfg.get("num_ctx", 4096)),
        }
        if self.runtime_profile == "cpu":
            options.update(self.cfg.get("cpu_options", {}) or {})
        elif self.runtime_profile in {"cuda", "low_vram"}:
            options.update(self.cfg.get("low_vram_options", {}) or {})
        return options

    def generate(self, prompt: str, image_paths: Optional[List[str | Path]] = None, schema: Optional[dict[str, Any]] = None, model: Optional[str] = None) -> dict[str, Any]:
        images = []
        for p in image_paths or []:
            try:
                images.append(self.encode_image(p))
            except Exception:
                continue
        payload: Dict[str, Any] = {
            "model": model or self.model,
            "prompt": prompt,
            "stream": False,
            "options": self._options(),
        }
        if images:
            payload["images"] = images
        payload["format"] = schema if schema else "json"
        started = time.time()
        try:
            r = requests.post(self.base_url + "/api/generate", json=payload, timeout=self.timeout)
            latency = time.time() - started
            text = ""
            data = None
            if r.content:
                data = r.json()
                text = data.get("response", "") if isinstance(data, dict) else ""
            return {"ok": r.ok, "provider": self.name, "status_code": r.status_code, "latency_sec": latency, "response": text, "raw": data, "model": payload["model"]}
        except Exception as e:
            return {"ok": False, "provider": self.name, "latency_sec": time.time() - started, "error": str(e), "model": payload["model"]}


class GeminiProvider(BaseVLMProvider):
    name = "gemini"

    def __init__(self, cfg: Dict[str, Any], runtime_profile: str = "api"):
        super().__init__(cfg, runtime_profile)
        self.model = cfg.get("model", "gemini-2.5-flash")
        self.api_key_env = cfg.get("api_key_env", "GEMINI_API_KEY")
        self.api_key = cfg.get("api_key") or os.environ.get(self.api_key_env)
        self.base_url = cfg.get("base_url", "https://generativelanguage.googleapis.com/v1beta").rstrip("/")
        self.temperature = float(cfg.get("temperature", 0.0))
        self.max_output_tokens = int(cfg.get("max_output_tokens", cfg.get("num_predict", 512)))

    def health(self) -> dict[str, Any]:
        return {
            "ok": bool(self.api_key),
            "provider": self.name,
            "model": self.model,
            "api_key_env": self.api_key_env,
            "message": "ready" if self.api_key else f"Missing API key. Set {self.api_key_env}.",
        }

    @staticmethod
    def _mime(path: str | Path) -> str:
        suffix = Path(path).suffix.lower()
        if suffix in {".jpg", ".jpeg"}:
            return "image/jpeg"
        if suffix == ".png":
            return "image/png"
        if suffix == ".webp":
            return "image/webp"
        return "image/jpeg"

    def generate(self, prompt: str, image_paths: Optional[List[str | Path]] = None, schema: Optional[dict[str, Any]] = None, model: Optional[str] = None) -> dict[str, Any]:
        if not self.api_key:
            return {"ok": False, "provider": self.name, "model": self.model, "response": "", "error": f"Missing API key. Set {self.api_key_env}."}
        parts: list[dict[str, Any]] = [{"text": prompt}]
        for p in image_paths or []:
            try:
                parts.append({
                    "inline_data": {
                        "mime_type": self._mime(p),
                        "data": self.encode_image(p),
                    }
                })
            except Exception:
                continue
        generation_config: dict[str, Any] = {
            "temperature": self.temperature,
            "maxOutputTokens": self.max_output_tokens,
            "responseMimeType": "application/json",
        }
        if schema:
            # Gemini's responseSchema is similar to OpenAPI JSON schema. If the model/API rejects it,
            # the catch block will preserve the raw error and the pipeline will fallback to geometry.
            generation_config["responseSchema"] = schema
        payload = {"contents": [{"role": "user", "parts": parts}], "generationConfig": generation_config}
        url = f"{self.base_url}/models/{model or self.model}:generateContent?key={self.api_key}"
        started = time.time()
        try:
            r = requests.post(url, json=payload, timeout=self.timeout)
            latency = time.time() - started
            raw = r.json() if r.content else None
            text = ""
            if isinstance(raw, dict):
                candidates = raw.get("candidates") or []
                if candidates:
                    content = candidates[0].get("content") or {}
                    for part in content.get("parts") or []:
                        if "text" in part:
                            text += part.get("text") or ""
            return {"ok": r.ok, "provider": self.name, "status_code": r.status_code, "latency_sec": latency, "response": text, "raw": raw, "model": model or self.model}
        except Exception as e:
            return {"ok": False, "provider": self.name, "latency_sec": time.time() - started, "error": str(e), "model": model or self.model}


class OllamaClient:
    """Backward-compatible wrapper used by the existing relation extractor.

    runtime.profile controls provider selection:
      - api: use Gemini API
      - cpu/cuda/low_vram: use Ollama unless cfg.provider overrides it
      - off: disable VLM and keep geometry fallback only
    """

    def __init__(self, cfg: Dict[str, Any], runtime_profile: str = "low_vram", gemini_cfg: Optional[Dict[str, Any]] = None, provider: Optional[str] = None):
        self.cfg = cfg
        self.runtime_profile = runtime_profile
        selected = provider or cfg.get("provider") or ("gemini" if runtime_profile == "api" else "ollama")
        if runtime_profile == "off" or selected == "off":
            self.provider = OffVLMProvider({}, runtime_profile)
        elif selected == "gemini":
            self.provider = GeminiProvider(gemini_cfg or {}, runtime_profile)
        else:
            self.provider = OllamaProvider(cfg, runtime_profile)
        self.provider_name = self.provider.name
        self.model = self.provider.model

    def health(self) -> dict[str, Any]:
        return self.provider.health()

    def generate(self, prompt: str, image_paths: Optional[List[str | Path]] = None, schema: Optional[dict[str, Any]] = None, model: Optional[str] = None) -> dict[str, Any]:
        return self.provider.generate(prompt, image_paths=image_paths, schema=schema, model=model)


def parse_json_response(text: str) -> tuple[bool, Any, str | None]:
    if not text:
        return False, None, "empty response"
    try:
        return True, json.loads(text), None
    except Exception:
        pass
    start = text.find("{")
    end = text.rfind("}")
    if start >= 0 and end > start:
        try:
            return True, json.loads(text[start:end + 1]), None
        except Exception as e:
            return False, None, f"json extraction failed: {e}"
    return False, None, "no JSON object found"
