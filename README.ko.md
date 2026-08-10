# stt-agent

영상 1건의 **자막 공정 오케스트레이터** (FastAPI). `v_id` 하나를 받아 음성 갈래와 이미지 갈래를
병렬로 돌리고, 둘 다 끝나면 DB 에 저장한다. HTTP 는 즉시 `accepted` 로 응답하고 실제 공정은
백그라운드에서 돈다.

[English README](README.md)

## 카테고리마다 공정이 다르다

핵심 개념은 **카테고리 표**(`lib/svc/profile.py`)다. 스텝 순서는 어느 카테고리든 같고,
**무엇을 켜고 무슨 재료를 줄지**만 표가 정한다.

| 카테고리 | 웹검색 | 2차 전사 | 용어집 | 요약 | 이미지 검출 |
|---|---|---|---|---|---|
| 스포츠-야구 | O | O | 야구 | ✕ | baseball |
| 스포츠-축구 | O | O | 축구 | ✕ | soccer |
| 드라마 | O | O | — | O | — |
| 다큐 · 뉴스 | ✕ | ✕ | — | O | — |

표에 없는 카테고리는 대분류(`드라마-사극` → `드라마`)로, 그것도 없으면 기본값으로 떨어진다.
**카테고리 문자열을 해석하는 곳은 이 표 하나**이고, 파이프라인과 스텝들은 표가 넘긴 스위치만 본다.

## 파이프라인

```
POST /api/v1/stt_svc {v_id, file_path, title, category, year}
        │  상태 1001(접수) + 즉시 "accepted" 응답
        │
        └─ 백그라운드 (svc/pipeline)
             profile.resolve(category)
             (ffmpeg) 원본 → 음성(audio.wav) + 프레임(frames/)     ← 두 갈래 공통 선행
                    ├── 음성 갈래  (검색) → STT → (2차 전사) → 교정 → 할루시 → (요약)
                    └── 이미지 갈래 검출 워커(종목별)
                              ↓ join
                          한 트랜잭션 저장 → 상태 1006(완료) → agent-vision 트리거
```

- **ffmpeg 는 갈래가 아니다** — 두 갈래의 재료를 모두 만들므로 먼저 끝내고 나서 갈래를 띄운다.
  갈래 안에 넣으면 프레임이 없는 채로 검출 워커를 불러 거절당한다.
- 두 갈래는 **서로 다른 서버의 GPU** 를 쓰므로 실제로 병렬로 돈다.
- **둘 다 중요하다** — 어느 쪽이 실패하든 나머지를 취소하고 통째 rollback, 상태 `-1`.
  반쪽만 저장하면 그 영상이 완료인지 알 수 없기 때문.
- 블로킹 호출(워커 HTTP, DB)은 전부 `asyncio.to_thread` 로 넘겨 이벤트루프를 막지 않는다.
- 마지막 **agent-vision 트리거**는 `.env` 의 `VISION_TRIGGER` 가 on 일 때만. 저장이 끝난 뒤라
  실패해도 완료를 뒤집지 않고 로그만 남긴다.

## 소스 구조 (대략)

```
main.py / config.py
lib/
  http/      접수 라우터 — 백프레셔·상태 1001 만 하고 공정은 svc 로 넘긴다
  svc/       공정. pipeline.py(전체) + profile.py(카테고리 표)
             ffmpeg/ audio/ image/ rdb/ — 갈래와 스텝. 디렉토리마다 진입점은 pipe_*.py 하나
  client/    외부 호출만 (STT·검색엔진·검출워커·vLLM·MariaDB). 정책은 안 갖는다
```

파일명은 `<기능>_<모듈>.py` 규칙이다 — `pipe_search.py` / `vllm_hallu.py` / `util_correct.py` /
`schema_dialogue.py`. 공정을 흐르는 값은 전부 dataclass 로 정의돼 있다(`svc/**/schema_*.py`).

## 설계 요점

- **단일 엔드포인트** `POST /api/v1/stt_svc` — 받자마자 응답, 공정은 `BackgroundTasks`.
- **공유 리소스**(vLLM 클라이언트 / httpx / 세마포어 / 카운터)는 `lifespan` 에서 1회 생성해 `app.state` 로.
- **동시성** — `MAX_REQ_CNT` 하나로 접수 상한과 워커별 세마포어를 함께 잡는다(초과 접수는 429).
  vLLM 만 `VLLM_CONCURRENCY` 로 따로 제한.
- **저장 원자성** — 트랜잭션은 `svc/rdb/save_svc.py` 한 곳에서만 연다. 실패는 예외로 올려 rollback.
- **단계 추적** — 실패 시 `stage`(ffmpeg/stt/correct/…)를 로그에 남긴다.

## 설정 (.env)

`.env.example` 를 복사해 `.env` 로 만들고 값을 채운다.

| 키 | 설명 |
|---|---|
| `HOST` / `PORT` | 이 서버 바인드 주소/포트 |
| `STT_HOST` / `STT_PORT` | prep_stt 워커 (ffmpeg + 1·2차 전사) |
| `VLLM_HOST` / `VLLM_PORT` | vLLM(Qwen) — 검색·교정·할루시·요약 |
| `IMG_MODELS_HOST` / `IMG_MODELS_PORT` | 프레임 검출 워커 (worker-img_models) |
| `RDB_*` | MariaDB |
| `VISION_HOST` / `VISION_PORT` / `VISION_TRIGGER` | 다음 단계(agent-vision) 트리거 |
| `DUMP_DIR` / `DUMP_STEPS_*` | 단계별 중간 결과 덤프 (검수용, write-only) |

> ⚠ `.env` 는 DB 비밀번호를 포함하므로 커밋하지 않는다 (`.gitignore` 에 포함됨).

## 실행

```bash
uv sync
uv run uvicorn main:app --host 0.0.0.0 --port 19010   # --reload 로 개발
```

## 테스트

```bash
curl -sS -X POST http://localhost:19010/api/v1/stt_svc \
  -H 'Content-Type: application/json' \
  -d '{"v_id":1,"file_path":"vod/1/1.mp4","title":"코리안시리즈 KIA vs SK",
       "category":"스포츠-야구","year":2009}'
```

응답:
```json
{"v_id": 1, "status": "accepted"}        // 접수됨 (공정은 백그라운드)
{"v_id": 1, "status": "Not found v_id"}  // t_video 에 없는 v_id
// 429 — 대기열 가득참 (Retry-After 헤더)
```

## 요구사항

- Python >= 3.13, [uv](https://docs.astral.sh/uv/)
- 외부 서비스: prep_stt 워커, vLLM(Qwen), worker-img_models, MariaDB, agent-vision(선택)

## 라이선스

[MIT](LICENSE)
