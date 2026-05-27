# Edge-to-Server Vision Intelligence System

> Edge 장치에서 수집한 카메라 프레임을 객체 탐지 기반 이벤트 패키지로 구성하고, GPU Server에서 관계 그래프·VLM 추론·처리 상태 Dashboard를 제공하는 Edge-to-Server 기반 실시간 시각 분석 시스템입니다.

---

## 1. 프로젝트 개요

본 프로젝트는 **Edge Server**와 **GPU Server**를 분리하여, 카메라 기반 객체 탐지 이벤트를 안정적으로 수집하고 서버에서 고도화된 분석을 수행하는 구조를 목표로 합니다.

Edge 장치는 카메라 또는 GStreamer 기반 stream directory에서 프레임을 읽고, YOLO 기반 객체 탐지를 수행한 뒤, 이벤트 단위로 이미지·탐지 결과·crop·overlay·metadata를 압축 패키지로 생성합니다. GPU Server는 이 패키지를 수신하여 처리 상태를 추적하고, 객체 관계 그래프, VLM 기반 관계 추론, scoring 결과, evidence image를 웹 Dashboard에서 확인할 수 있도록 제공합니다.

---

## 2. Repository 구성

GitHub에는 다음과 같은 형태로 업로드하는 것을 권장합니다.

```text
edge-to-server-vision-system/
├── README.md
├── gpu_server_v4_3_production_candidate/
│   ├── app/
│   ├── configs/
│   ├── storage/
│   ├── requirements.txt
│   └── run_server.sh
│
├── edge_device_v4_3_gpu_compatible_preserve_camera/
│   └── edge_node/
│       ├── core/
│       ├── tools/
│       ├── scripts/
│       ├── docs/
│       ├── config.yaml
│       ├── requirements.txt
│       ├── run_edge.py
│       └── run_edge.sh
│
└── docs/
    ├── architecture.md
    ├── edge_event_schema.md
    └── troubleshooting.md
```

---

## 3. 전체 시스템 구조

```text
[Camera / GStreamer Stream]
          ↓
[Edge Server]
  - frame reader
  - YOLO object detection
  - overlay / crop generation
  - event package creation
  - upload queue / retry
          ↓
[GPU Server]
  - event zip ingestion
  - processing status tracking
  - relation graph building
  - VLM provider: off / Ollama / Gemini
  - scoring
  - dashboard visualization
          ↓
[Web Dashboard]
  - received / processing / completed events
  - event detail
  - graph node crop preview
  - VLM evidence / raw response
  - recovery / stale event handling
```

---

## 4. 핵심 설계 원칙

### 4.1 Edge Server는 카메라 입력 방식을 보존한다

Edge Server에서는 기존 프로젝트의 카메라 사용 방식을 새로 바꾸지 않습니다.  
기존 `gst_stream_dir` 기반 방식, 즉 `data/stream/frame_*.jpg`를 읽는 구조를 유지합니다.

현재 프로젝트에서 확인된 설정은 다음과 같습니다.

```yaml
camera:
  gst_stream_dir:
    stream_dir: data/stream
    frame_glob: frame_*.jpg
    max_frame_age_sec: 5.0
```

즉, Edge Server의 메인 루프는 카메라를 직접 여는 대신, GStreamer 또는 기존 카메라 프로세스가 생성한 `frame_*.jpg` 파일을 읽습니다.

### 4.2 Motion Candidate는 사용하지 않는다

초기 버전에서는 frame difference 기반 Motion Candidate를 별도로 만들었지만, 현재 구조에서는 해당 기능을 사용하지 않습니다.

현재 방향은 다음과 같습니다.

```text
YOLO 객체 탐지 결과만 GPU Server로 전달
Motion Candidate는 event package에서 제외
GPU Server는 YOLO detection 기반으로 graph / VLM / scoring 수행
```

이렇게 한 이유는 Motion Candidate가 별도 근거 없이 혼합될 경우, Dashboard에서 객체 관계를 해석하기 어려워지고, 실제 YOLO 기반 관계 분석 결과와 혼동될 수 있기 때문입니다.

### 4.3 GPU Server는 분석과 시각화에 집중한다

GPU Server는 Edge에서 올라온 이벤트를 다음 방식으로 처리합니다.

```text
event zip 수신
→ 안전한 압축 해제
→ metadata / detections / roi_hints 로딩
→ 처리 상태 기록
→ graph 생성
→ VLM provider 호출
→ scoring
→ result.json 저장
→ Dashboard 표시
```

---

## 5. Edge Server

### 5.1 역할

Edge Server는 다음 역할을 담당합니다.

| 기능 | 설명 |
|---|---|
| Frame Reader | 기존 카메라/GStreamer stream directory에서 frame 읽기 |
| Object Detector | Ultralytics YOLO 기반 객체 탐지 |
| Package Builder | frame, overlay, crops, metadata, detections를 zip으로 구성 |
| Uploader | GPU Server `/api/events`로 이벤트 업로드 |
| Queue/Retry | 네트워크 장애 시 zip 재전송 |
| Heartbeat | Edge 상태를 GPU Server에 보고 |

---

### 5.2 입력 프레임 방식

현재 Edge Server는 다음 경로를 감시합니다.

```text
data/stream/frame_*.jpg
```

따라서 Edge Server 실행 전, 먼저 GStreamer 프레임 생성 프로세스를 실행해야 합니다.

```bash
python tools/start_gst_stream.py --config config.yaml
```

이 도구는 `data/stream/frame_%06d.jpg` 형식의 파일을 생성합니다. 예를 들면:

```text
data/stream/frame_000001.jpg
data/stream/frame_000002.jpg
data/stream/frame_000003.jpg
```

GStreamer의 `multifilesink`는 입력 데이터를 순차적인 파일명으로 저장하는 element이므로, 카메라 frame을 JPEG 파일 시퀀스로 저장하는 데 사용할 수 있습니다.

---

### 5.3 Edge 실행 순서

#### 1단계: 의존성 설치

```bash
cd edge_device_v4_3_gpu_compatible_preserve_camera/edge_node

conda activate GRAD
pip install -r requirements.txt
pip install ultralytics
```

#### 2단계: GPU Server 주소 설정

`config.yaml`에서 GPU Server 주소를 수정합니다.

```yaml
server:
  base_url: "http://GPU_SERVER_IP:8008"
```

예:

```yaml
server:
  base_url: "http://100.xxx.xxx.xxx:8008"
```

#### 3단계: stream directory 정리

```bash
mkdir -p data/stream
find data/stream -name '*.jpg' -delete
```

또는 제공된 service script를 사용하는 경우:

```bash
./scripts/edge_service.sh clean-stream
```

#### 4단계: GStreamer frame 생성 시작

터미널 1:

```bash
python tools/start_gst_stream.py --config config.yaml
```

정상 동작 확인:

```bash
watch -n 1 'ls -lt data/stream | head -20'
```

#### 5단계: Edge main loop 실행

터미널 2:

```bash
./run_edge.sh run
```

또는:

```bash
python run_edge.py --config config.yaml
```

---

### 5.4 Edge에서 생성하는 이벤트 패키지

GPU Server v4.3과 호환되는 이벤트 zip 구조는 다음과 같습니다.

```text
event_id.zip
├── metadata.json
├── detections.json
├── roi_hints.json
├── manifest.json
├── frame_t.jpg
├── context_t.jpg
├── frame_t_minus_1.jpg        # optional
├── frame_t_plus_1.jpg         # optional
├── overlay/
│   └── edge_overlay_t.jpg
└── crops/
    ├── person_1_person.jpg
    └── object_1_laptop.jpg
```

### 5.5 `detections.json` 예시

```json
{
  "schema_version": "edge_event_v4.3",
  "event_id": "cam01_20260530_000000_000001_L2",
  "detections": [
    {
      "id": "person_1",
      "type": "person",
      "label": "person",
      "bbox": [100, 50, 200, 300],
      "bbox_format": "xyxy",
      "frame_width": 640,
      "frame_height": 360,
      "confidence": 0.90,
      "source": "edge_yolo_all_classes",
      "crop_path": "crops/person_1_person.jpg",
      "motion_candidate": false
    }
  ],
  "object_counts": {
    "person": 1
  }
}
```

---

## 6. GPU Server

### 6.1 역할

GPU Server는 Edge에서 받은 이벤트 패키지를 수신하고, 이를 분석 가능한 결과로 변환합니다.

| 기능 | 설명 |
|---|---|
| Event Ingestion | Edge zip 수신 및 압축 해제 |
| Status Tracking | 입력 / 처리중 / 완료 / 실패 상태 관리 |
| Recovery | 오래 멈춘 event를 stale로 처리하거나 재처리 |
| VLM Provider | off / Ollama / Gemini API 모드 지원 |
| Graph Builder | 객체와 관계를 node-edge graph로 구성 |
| Node Preview | graph node 클릭 시 해당 객체 crop 표시 |
| Dashboard | 전체 처리 흐름과 결과를 Web에서 확인 |

---

### 6.2 GPU Server 실행

```bash
cd gpu_server_v4_3_production_candidate

conda activate GRAD
pip install -r requirements.txt
chmod +x run_server.sh
```

#### VLM 없이 실행

```bash
./run_server.sh off prod
```

#### Ollama 기반 실행

```bash
./run_server.sh cuda prod
```

#### Google AI Studio / Gemini API 기반 실행

```bash
export GEMINI_API_KEY="YOUR_GOOGLE_AI_STUDIO_API_KEY"
export VLM_PROVIDER=gemini

./run_server.sh api prod
```

Gemini API는 text, image, audio, video data를 포함한 multimodal prompting을 지원하므로, GPU Server에서 evidence image와 prompt를 함께 보내 관계 추론에 사용할 수 있습니다.

---

### 6.3 Dashboard 접속

```text
http://GPU_SERVER_IP:8008/dashboard
```

Dashboard에서는 다음을 확인할 수 있습니다.

```text
입력받은 파일
처리하고 있는 파일
처리가 끝난 파일
실패/복구 필요 이벤트
Edge node 상태
Event detail
Dynamic evidence graph
Graph node crop preview
VLM prompt / response / evidence
Scoring breakdown
```

---

## 7. VLM Provider 구조

GPU Server는 다음 VLM provider를 지원합니다.

| Provider | 설명 |
|---|---|
| `off` | VLM 없이 geometry / rule 기반 처리 |
| `ollama` | 로컬 Ollama VLM 사용 |
| `gemini` | Google AI Studio API Key 기반 Gemini API 사용 |

### 7.1 왜 Gemini API 모드가 필요한가?

로컬 Ollama VLM은 GPU VRAM, CUDA, ggml runner 문제로 실패할 수 있습니다. Gemini API 모드를 사용하면 로컬 GPU 리소스에 의존하지 않고, 이미지 기반 relation extraction을 테스트할 수 있습니다.

### 7.2 API Key 구분

| Key | 위치 | 목적 |
|---|---|---|
| `GEMINI_API_KEY` | GPU Server | Google Gemini API 호출 |
| `EDGE_API_KEY` | Edge Server → GPU Server | Edge 장치 인증용 선택 옵션 |

개발 단계에서는 `EDGE_API_KEY`를 사용하지 않아도 됩니다.  
단, GPU Server의 `/api/events` endpoint를 외부에 노출할 경우에는 최소한의 업로드 인증을 위해 사용하는 것이 좋습니다.

---

## 8. 현재까지 해결한 주요 문제

### 8.1 Dashboard 500 Error

초기 GPU Server에서는 Jinja2 template path 또는 `TemplateResponse` 호출 방식 문제로 `/dashboard` 접속 시 500 error가 발생했습니다.

해결 방향:

```python
templates = Jinja2Templates(directory=str(TEMPLATE_DIR))

return templates.TemplateResponse(
    request=request,
    name="dashboard.html",
    context={}
)
```

---

### 8.2 로그 파일 권한 문제

GPU Server 실행 시 다음 에러가 발생했습니다.

```text
PermissionError: [Errno 13] Permission denied: storage/logs/server.log
```

해결:

```bash
sudo chown -R devuser:devuser storage
chmod -R u+rwX storage
```

---

### 8.3 Ollama VLM 모델 로딩 실패

Ollama 기반 VLM 실행 시 모델 로딩 또는 ggml runner 오류가 발생했습니다.  
해결 방향:

```text
1. OLLAMA_CONTEXT_LENGTH=4096으로 낮추기
2. OLLAMA_NUM_PARALLEL=1로 제한
3. CPU 모드 또는 low_vram 모드 사용
4. Gemini API provider fallback 추가
```

---

### 8.4 Edge Reader timeout

Edge Server에서 다음 로그가 반복되었습니다.

```text
GstStreamDirReader timeout stream_dir=data/stream glob=frame_*.jpg
```

원인:

```text
data/stream/frame_*.jpg 최신 프레임이 생성되지 않음
```

확인 결과, 프로젝트에는 `tools/start_gst_stream.py`가 있으며, 이 파일은 `frame_%06d.jpg` 형식으로 stream frame을 생성하도록 구성되어 있습니다.

실행 순서:

```bash
python tools/start_gst_stream.py --config config.yaml
watch -n 1 'ls -lt data/stream | head -20'
./run_edge.sh run
```

---

## 9. Troubleshooting

### 9.1 `GstStreamDirReader timeout`

확인:

```bash
ls -al data/stream
watch -n 1 'ls -lt data/stream | head -20'
```

해결:

```bash
python tools/start_gst_stream.py --config config.yaml
```

또는 제공된 shell script 확인:

```bash
./scripts/edge_service.sh help
```

### 9.2 YOLO 모델은 초기화되지만 이벤트가 생성되지 않음

가능한 원인:

```text
프레임 입력 없음
confidence threshold가 너무 높음
trigger 조건 미충족
stream frame이 오래되어 max_frame_age_sec 초과
```

확인:

```bash
unzip -p latest_event.zip detections.json | jq
```

### 9.3 GPU Server Dashboard에 이벤트가 안 보임

확인:

```bash
curl http://GPU_SERVER_IP:8008/api/health
find data -name "*.zip" | tail
ls -al data/queue data/sent data/failed
```

### 9.4 Gemini API가 작동하지 않음

확인:

```bash
echo $GEMINI_API_KEY
echo $VLM_PROVIDER
```

실행:

```bash
export GEMINI_API_KEY="YOUR_KEY"
export VLM_PROVIDER=gemini
./run_server.sh api prod
```

---

## 10. 보안 및 운영 고려사항

### 10.1 File Upload 보안

GPU Server는 Edge에서 zip 파일을 수신합니다. 따라서 다음이 필요합니다.

```text
zip slip 방지
파일 개수 제한
압축 해제 크기 제한
허용 확장자 확인
선택적 EDGE_API_KEY 인증
```

OWASP는 파일 업로드 기능에서 파일 크기 제한, 파일명 제어, 확장자 검증, 인증된 사용자만 업로드 가능하게 하는 등의 방어를 권장합니다.

### 10.2 API Key 관리

`GEMINI_API_KEY`는 절대 GitHub에 커밋하지 않습니다.

`.env` 또는 shell 환경변수로 관리합니다.

```bash
export GEMINI_API_KEY="..."
```

`.gitignore`에는 다음을 포함하는 것을 권장합니다.

```gitignore
.env
storage/
data/
*.log
*.zip
*.pt
```

---

## 11. 기술 스택

| 영역 | 사용 기술 |
|---|---|
| Edge Object Detection | Ultralytics YOLO |
| Edge Frame Stream | GStreamer / multifilesink / stream directory |
| Server Framework | FastAPI |
| Realtime Dashboard | WebSocket |
| VLM Local Mode | Ollama |
| VLM API Mode | Google Gemini API |
| Storage | SQLite / filesystem |
| Visualization | HTML / CSS / JavaScript graph UI |

---

## 12. 참고 문서

- FastAPI WebSocket Documentation: https://fastapi.tiangolo.com/advanced/websockets/
- Ultralytics YOLO Python Usage: https://docs.ultralytics.com/usage/python/
- GStreamer multifilesink Documentation: https://gstreamer.freedesktop.org/documentation/multifile/multifilesink.html
- Google Gemini API Image Understanding: https://ai.google.dev/gemini-api/docs/image-understanding
- OWASP File Upload Cheat Sheet: https://cheatsheetseries.owasp.org/cheatsheets/File_Upload_Cheat_Sheet.html

---

## 13. 현재 프로젝트 상태 요약

현재까지의 핵심 진척은 다음과 같습니다.

```text
GPU Server:
- 입력 / 처리중 / 완료 / 실패 lane 기반 Dashboard 구성
- Event Detail 페이지 구성
- Graph node crop preview 추가
- VLM provider 분리: off / ollama / gemini
- Recovery 로직 추가
- Safe zip extraction 및 SQLite 안정성 보강

Edge Server:
- 기존 카메라/GStreamer 입력 방식 보존
- YOLO detection 중심 event package 생성
- Motion Candidate 비활성화
- detections.json / metadata.json / crops / overlay 구조 정리
- heartbeat 및 upload queue 보강
- GPU Server v4.3과 호환되는 event schema 구성
```

---

## 14. 향후 개선 계획

```text
1. edge_service.sh를 중심으로 실행 명령 통합
2. Dashboard에서 Edge frame stream 상태 표시
3. VLM result quality flag 강화
4. Graph memory 누적 관계 시각화 개선
5. Gemini API 호출량 최적화
6. Edge upload retry 상태를 Dashboard에서 확인
7. README와 docs를 GitHub 기준으로 계속 정리
```

---

## 15. 한 줄 요약

> 이 프로젝트는 Edge에서 수집한 카메라 기반 객체 탐지 결과를 GPU Server로 전송하고, 서버에서 실시간 처리 상태·객체 관계 그래프·VLM 근거·scoring 결과를 Dashboard로 확인하는 Edge-to-Server 기반 시각 지능 시스템입니다.
