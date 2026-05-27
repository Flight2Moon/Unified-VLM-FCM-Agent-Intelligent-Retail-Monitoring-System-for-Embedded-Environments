# EAGER GPU Server v4.3 Production Candidate

## 주요 변경

- Dashboard 첫 화면에 `입력받은 파일 / 처리하고 있는 파일 / 처리가 끝난 파일 / 실패·복구 필요` lane을 추가했습니다.
- `/api/events/status-summary` API를 추가했습니다.
- `/api/events/recover-stale` API와 서버 시작 시 stale event recovery를 추가했습니다.
- Event Detail 그래프에서 노드를 클릭하면 해당 객체 crop 이미지, bbox, confidence를 확인할 수 있습니다.
- `runtime.profile=api` 또는 `vlm.provider=gemini` 설정 시 Google AI Studio에서 발급받은 `GEMINI_API_KEY`로 Gemini API VLM을 호출합니다.
- 기존 Ollama 모드는 유지합니다. `low_vram`, `cpu`, `cuda`, `off`, `api` 모드를 지원합니다.
- GPU 서버 관계 추론에서는 별도 Edge Motion Candidate entity를 제외하고 YOLO/detector 결과만 사용합니다.
- Zip Slip 방지를 위한 safe extraction, SQLite WAL/busy_timeout을 보강했습니다.
- Geometry relation의 `touching` 과대판단을 줄이기 위해 기본 relation을 `touching_candidate`로 낮추고 IoU threshold를 0.12로 높였습니다.

## 실행

```bash
chmod +x run_server.sh
./run_server.sh low_vram prod
```

접속:

```text
http://GPU_SERVER_IP:8008/dashboard
```

## Google AI Studio / Gemini API 모드

```bash
export GEMINI_API_KEY="발급받은_API_KEY"
export VLM_PROVIDER=gemini
./run_server.sh api prod
```

또는 `configs/server_config.yaml`에서:

```yaml
runtime:
  profile: "api"
vlm:
  provider: "gemini"
gemini:
  model: "gemini-2.5-flash"
```

무료 사용량 보호를 위해 처음에는 아래 설정을 권장합니다.

```yaml
vlm_relation:
  mode: "scene_only"
  max_pairwise_checks: 0
```

## Ollama CPU 모드

```bash
./run_server.sh cpu prod
```

별도 터미널에서 Ollama를 CPU로 강제하려면:

```bash
CUDA_VISIBLE_DEVICES=-1 OLLAMA_CONTEXT_LENGTH=4096 OLLAMA_NUM_PARALLEL=1 OLLAMA_KEEP_ALIVE=0 ollama serve
```

## Recovery

Dashboard에서 `Recover stale` 버튼을 누르거나:

```bash
curl -X POST 'http://127.0.0.1:8008/api/events/recover-stale?action=mark_failed'
```

재처리까지 하고 싶으면:

```bash
curl -X POST 'http://127.0.0.1:8008/api/events/recover-stale?action=requeue'
```

## Edge Motion Candidate 정책

GPU 서버는 `label=motion_candidate`, `type=motion_candidate`, `source=edge_frame_difference` entity를 관계 추론 대상에서 제외합니다. 따라서 Edge Server가 기존처럼 Motion Candidate를 포함해 보내더라도 GPU 서버는 YOLO/detector entity만 graph/VLM relation에 사용합니다.
