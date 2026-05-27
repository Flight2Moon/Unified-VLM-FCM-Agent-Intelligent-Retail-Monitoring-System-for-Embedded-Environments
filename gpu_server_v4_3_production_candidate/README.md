# EAGER GPU Server v4

Evidence-Augmented Graph Event Reasoner for Edge-triggered scene understanding.

This server receives Edge v4.2 event packages, manages detection policies, builds datasets, and runs VLM-based semantic relation extraction using Ollama vision models. The default VLM is `gemma4:e4b`, but every model setting is configurable in `configs/server_config.yaml` or with environment variables.

## Main features

- FastAPI event receiver for Edge ZIP packages.
- Detection Policy Manager for Edge object filtering.
- Label statistics and crop preview APIs.
- Dataset Builder with quota/limit management.
- Review queue and label APIs.
- VLM-based semantic relation extractor.
- Chain-of-Evidence style relation cards.
- Eventlet and Dynamic Evidence Graph output.
- SQLite WAL storage.
- Basic dashboard at `/dashboard`.
- CPU/CUDA/Metal/low-VRAM launch profiles.

## Quick start

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
chmod +x run_server.sh scripts/*.sh
./scripts/pull_model.sh gemma4:e4b
./run_server.sh low_vram
```

Open:

```text
http://127.0.0.1:8008/dashboard
```

Health check:

```bash
curl http://127.0.0.1:8008/health | python3 -m json.tool
```

## Runtime profiles

```bash
./run_server.sh cpu
./run_server.sh cuda
./run_server.sh metal
./run_server.sh low_vram
```

The server controls Python-side profile settings and sends profile-aware Ollama options. Ollama itself must be installed and running separately.

## Edge integration endpoints

Edge v4.2 uses:

```text
POST /api/events
GET  /api/detection-policy
POST /api/edge/heartbeat
```

## Changing the VLM model

Edit:

```yaml
ollama:
  model: "gemma4:e4b"
```

or run:

```bash
OLLAMA_MODEL=qwen2.5vl:7b ./run_server.sh cuda
```

## Safety note

This server avoids hidden intent claims. Relations such as `stealing`, `malicious_intent`, or `wants_to` are prohibited and filtered. The VLM is treated as an evidence interpreter, not a final judge.
