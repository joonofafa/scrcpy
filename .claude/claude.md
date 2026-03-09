# scrcpy 프로젝트 Context

## 프로젝트 개요

scrcpy(Screen Copy) 3.3.4 기반 포크. 원본 기능(Android 미러링/제어) 위에 **AI 에이전트** + **웹 릴레이 서버** + **Python 프론트엔드** 기능을 추가했다.

## 커스텀 기능 (app/src/ai/)

### 1. AI Vision Agent

LLM(OpenRouter API)이 Android 화면을 보고 자율적으로 조작하는 시스템.

- **ai_agent.c/h** — 에이전트 코어. 대화 히스토리 관리, worker 스레드에서 LLM 호출, CLIP 임베딩 매칭, tree-based 자동화
- **ai_frame_sink.c/h** — `sc_frame_sink` 구현. 디코딩된 비디오 프레임을 PNG로 캡처
- **screenshot.c/h** — FFmpeg AVFrame → PNG 인코딩 (libavcodec png encoder)
- **openrouter.c/h** — OpenRouter/OpenAI 호환 Chat Completions API 클라이언트 (libcurl)
- **ai_tools.c/h** — Function calling 도구 정의 및 실행 (터치, 스와이프, 키 입력, 텍스트 입력, 대기 등)

CLI 옵션: `--ai-panel`, `--ai-api-key <key>`

### 2. Web Relay Server (C 백엔드, 포트 18080)

리눅스 서버에서 scrcpy를 헤드리스 데몬으로 실행, H.264 비디오 스트리밍 + 터치/키 원격 조작을 WebSocket으로 제공.

- **web_server.c/h** — Mongoose 7.20 기반 HTTP/WebSocket 서버
  - `GET /ws/video` — H.264 비디오 스트림 (바이너리 WebSocket). 연결 시 SPS/PPS config + 캐시된 키프레임 즉시 전송
  - `GET /ws/control` — 터치/키 입력 수신 (JSON WebSocket)
  - CLIP 관련 API 엔드포인트 (`/api/clip/*`)
  - 디바이스 회전 시 자동 해상도 변경 브로드캐스트
- **web_video_sink.c/h** — `sc_packet_sink` 구현. 디먹서 H.264 패킷 → 링버퍼 큐
  - `ensure_annexb()` — 모든 패킷을 Annex-B 포맷(00 00 00 01 start code)으로 변환
  - merged 패킷(config+키프레임) 분리 처리
  - **키프레임 캐싱** — 마지막 IDR 프레임 저장, 새 클라이언트 접속 시 즉시 전송 (빠른 비디오 로딩)
  - **SPS/PPS 변경 감지** — config 변경 시 캐시된 키프레임 자동 무효화 (앱 전환 안전성)
- **web_ui.h** — C 임베디드 웹 UI (레거시, Python 프론트엔드로 대체 중)

CLI 옵션: `--ai-web-port <port>`

### 3. Python 프론트엔드 (app/python/, 포트 8080)

FastAPI 기반 웹 프론트엔드. Apache 리버스 프록시를 통해 C 백엔드의 WebSocket과 통합.

- **main.py** — FastAPI 앱 진입점
- **web/routes.py** — API 라우트 (AI 에이전트, 게임 규칙 등)
- **static/index.html** — 웹 UI (jmuxer 2.1.0 H.264→MSE 디코딩)
  - jmuxer 에러 자동 복구 (InvalidStateError 시 재초기화, 최대 3회 재시도)
  - 터치 좌표 변환: object-fit:contain 보정, 회전 대응
  - 로딩 스피너 (video timeupdate 이벤트로 실제 재생 시 숨김)
- **agent/agent.py** — Python AI 에이전트 래퍼
- **clip/matcher.py** — CLIP 임베딩 기반 화면 매칭
- **device/client.py** — C 백엔드 통신 클라이언트
- **pipeline/recorder.py** — Record/Train/Play 파이프라인

### 4. 배포 아키텍처

```
브라우저 → Apache (443/SSL)
  ├─ /ws/video, /ws/control → C 백엔드 (ws://127.0.0.1:18080)
  └─ / (나머지) → Python FastAPI (http://127.0.0.1:8080)
```

- systemd 서비스: `/etc/systemd/system/scrcpy-web.service`
- `--video-codec-options=i-frame-interval=2` (2초 키프레임 간격, 빠른 초기 로딩)

실행 예시: `scrcpy --no-window --no-audio --ai-panel --ai-web-port 18080 --video-bit-rate=4M --video-codec-options=i-frame-interval=2 --max-size=1280 -s <device>`

## 빌드

```bash
# 증분 빌드
ninja -C release/work/build-linux-x86_64

# 배포
sudo systemctl stop scrcpy-web
cp release/work/build-linux-x86_64/app/scrcpy release/work/build-linux-x86_64/dist/scrcpy
sudo systemctl start scrcpy-web
```

빌드 옵션: `meson_options.txt`의 `ai_panel` (default: false)

## 주요 설계 결정

- **MAX_SINKS=3**: `app/src/trait/packet_source.h`에서 2→3. 디먹서에 decoder + recorder + web_video_sink 연결
- **Mongoose c->data[0]**: WebSocket 타입 마킹('V'=video, 'C'=control)은 반드시 `mg_ws_upgrade()` 호출 **전에** 설정
- **Annex-B 변환은 C에서**: JS가 아닌 서버 측 `ensure_annexb()`에서 처리
- **키프레임 캐시 무효화**: SPS/PPS config가 변경되면(앱 전환 등) 캐시된 키프레임 즉시 삭제
- **jmuxer 에러 복구**: buffer error 시 자동 재초기화 (3회 제한 후 WebSocket 재연결)
- **바인딩 0.0.0.0**: 외부 네트워크 접속 허용 (Apache 프록시 뒤에서 동작)

## 의존성 (추가분)

| 라이브러리 | 용도 | 경로 |
|-----------|------|------|
| Mongoose 7.20 | HTTP/WebSocket 서버 | app/deps/mongoose/ |
| cJSON | JSON 파싱 | app/deps/cjson/ |
| libcurl | OpenRouter API + CLIP 서버 호출 | 시스템 패키지 |
| jmuxer.js 2.1.0 | 브라우저 H.264→MSE | CDN (index.html에서 로드) |
| FastAPI | Python 웹 프레임워크 | pip (app/python/) |
