# stt-agent

STT 자막 **교정 파이프라인 오케스트레이터** (FastAPI).

영상 1개(`v_id`)에 대해 음성 추출 → STT → 자막 교정 → DB 저장 → 다음 단계(agent-vision) 트리거까지를 한 요청으로 조립한다. 요청은 **즉시 접수 응답**하고, 실제 공정은 백그라운드에서 처리한다.

## 공정 흐름

```
POST /api/v1/stt_svc {v_id, file_path}
        │
        ├─ 1-1. DB 상태 '처리중'(1005) 갱신  → 결과 확인(없는 v_id면 즉시 응답)
        │
        └─ 즉시 "accepted" 응답  ───────────────┐
                                                 │ (백그라운드 process)
   ② prep    POST prep_stt /pre_svc/  → audio_path   (ffmpeg 추출/분할)
   ③ stt     POST prep_stt /stt_svc/  → segments     (whisper STT, 5~10분)
   ④ correct vLLM(Qwen) 페이지 병렬 교정 → corrected
   ⑤ save    DB t_dialogue INSERT + 상태 '완료'(1006)
   ⑦ vision  POST agent-vision /api/v1/analyze       (다음 단계 트리거)
```

- **prep/stt** 는 같은 서버(prep_stt). STT 는 whisper(GPU) 라 한 번에 1 job → 세마포어로 제한.
- **교정(④)** 만 async(페이지 병렬), 나머지 블로킹 호출은 `asyncio.to_thread` 로 이벤트루프를 막지 않는다.

## 설계 요점

- **단일 엔드포인트** `POST /api/v1/stt_svc` — 받자마자 응답, 공정은 `BackgroundTasks` 로 처리.
- **공유 리소스** (vLLM 클라이언트 / httpx / 세마포어 / 카운터)는 `lifespan` 에서 1회 생성해 `app.state` 로 공유. vLLM 의 `AsyncOpenAI` 는 uvicorn 이벤트루프에 바인딩된다.
- **동시성 제어** (세마포어):
  - `STT_CONCURRENCY` — prep+stt 동시 처리 상한 (GPU 보호)
  - `VLLM_CONCURRENCY` — 교정 페이지 동시 호출 상한 (vLLM `chat()` 내부 세마포어)
- **백프레셔** — 접수 대기열이 `MAX_REQ_CNT` 를 넘으면 **429** 로 거절(무한 대기열 방지).
- **단계 추적** — 백그라운드 실패 시 `stage`(prep/stt/correct/save/vision) 를 로그에 남긴다.

## 프로젝트 구조

```
main.py                 FastAPI app + lifespan(공유 리소스) + 라우터 등록
config.py               .env 로딩 + 설정값
test.sh                 로컬 curl 테스트
lib/
  http/
    stt_svc.py          라우터 + 요청 DTO + 백그라운드 process(공정 조립)
    http_util.py        요청/응답 로깅 미들웨어
  client/               외부 서비스 호출 (1 서비스 = 1 모듈)
    db.py               MariaDB (상태 갱신 + 자막 INSERT)
    prep_stt.py         prep_stt 서버 (pre_svc/ffmpeg, stt)
    vllm.py             vLLM(Qwen) 교정 클라이언트
    vision.py           agent-vision 트리거
  correct/              자막 교정 로직
    corrector.py        segments → corrected (페이지 병렬)
    chunk.py            segments → 페이지 분할
    prompt.py           교정 프롬프트
  debug.py              단계별 중간 결과 덤프 (검수용, write-only)
  log.py                공용 로거 (파일 + 콘솔)
```

## 설정 (.env)

`.env.example` 를 복사해 `.env` 로 만들고 값을 채운다.

| 키 | 설명 |
|---|---|
| `HOST` / `PORT` | 이 서버(FastAPI) 바인드 주소/포트 |
| `STT_HOST` / `STT_PORT` | prep_stt 서버 (pre_svc + stt) |
| `VLLM_HOST` / `VLLM_PORT` | vLLM(Qwen) 교정 서버 |
| `RDB_HOST` / `RDB_PORT` / `RDB_USER` / `RDB_PW` / `RDB_NAME` | MariaDB |
| `VISION_HOST` / `VISION_PORT` | agent-vision 서버 |
| `DEBUG_DIR` | 중간 결과 덤프 경로 |


## 실행

```bash
uv sync                                              # 의존성 설치
uv run uvicorn main:app --host 0.0.0.0 --port 8000   # 서버 실행 (--reload 로 개발)
```

## 테스트

```bash
./test.sh                          # 기본 v_id=1
./test.sh 3 output/3/audio.wav     # v_id, file_path 지정
BASE=http://localhost:8000 ./test.sh

# 한 줄 (복붙용)
curl -sS -X POST http://localhost:8000/api/v1/stt_svc \
  -H 'Content-Type: application/json' \
  -d '{"v_id":1,"file_path":"output/1/audio.wav"}'
```

응답:
```json
{"v_id": 1, "status": "accepted"}        // 접수됨 (공정은 백그라운드)
{"v_id": 1, "status": "Not found v_id"}  // t_video 에 없는 v_id
// 429 — 대기열 가득참 (Retry-After 헤더)
```

## 요구사항

- Python >= 3.13
- [uv](https://docs.astral.sh/uv/)
- 외부 서비스: prep_stt, vLLM(Qwen), MariaDB, agent-vision

## 라이선스

[MIT](LICENSE)
