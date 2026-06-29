# stt-agent

Subtitle **correction pipeline orchestrator** (FastAPI) — the post-STT stage of the video pipeline.
For one video (`v_id`), it chains audio extraction → STT → subtitle correction → DB write → next-stage trigger into a single request, replies immediately, and runs the work in the background.

[한국어 README](README.ko.md)

## Overview

Given a `v_id` and a source `file_path`, `stt-agent` orchestrates the full correction
flow across external services and writes the final subtitles to the database. The HTTP
request is **accepted instantly**; the actual work runs in a background task.

The service exposes a single endpoint:

- **`POST /api/v1/stt_svc`** `{v_id, file_path}` — marks the video "processing", returns `accepted`, and dispatches the background pipeline.

## Pipeline

```
POST /api/v1/stt_svc {v_id, file_path}
        │
        ├─ 1-1. DB status → 'processing' (1005)   → validate v_id (unknown → reply immediately)
        │
        └─ reply "accepted" immediately  ───────────┐
                                                     │ (background process)
   [2] prep    POST prep_stt /pre_svc/  → audio_path   (ffmpeg extract / chunk)
   [3] stt     POST prep_stt /stt_svc/  → segments     (whisper STT, 5–10 min)
   [4] correct vLLM (Qwen) per-page parallel correction → corrected
   [5] save    DB t_dialogue INSERT + status → 'done' (1006)
   [7] vision  POST agent-vision /api/v1/analyze        (trigger next stage)
```

- **prep/stt** live on the same server (prep_stt). STT is whisper (GPU), one job at a time → bounded by a semaphore.
- Only **correction (4)** is async (per-page parallel); the other blocking calls go through `asyncio.to_thread` so they never block the event loop.

## Design notes

- **Single endpoint** `POST /api/v1/stt_svc` — replies on arrival, processes via `BackgroundTasks`.
- **Shared resources** (vLLM client / httpx / semaphore / counter) are created once in `lifespan` and shared via `app.state`. The vLLM `AsyncOpenAI` client binds to the uvicorn event loop.
- **Concurrency control** (semaphores):
  - `STT_CONCURRENCY` — max concurrent prep+stt jobs (protects the GPU)
  - `VLLM_CONCURRENCY` — max concurrent correction calls (semaphore inside vLLM `chat()`)
- **Backpressure** — when the pending queue exceeds `MAX_REQ_CNT`, new requests are rejected with **429** (avoids an unbounded queue).
- **Stage tracking** — background failures log the `stage` (prep/stt/correct/save/vision).

## Project layout

```
main.py                 FastAPI app + lifespan (shared resources) + router registration
config.py               .env loading + settings
test.sh                 local curl test
lib/
  http/
    stt_svc.py          router + request DTO + background process (pipeline assembly)
    http_util.py        request/response logging middleware
  client/               external service calls (1 service = 1 module)
    db.py               MariaDB (status update + subtitle INSERT)
    prep_stt.py         prep_stt server (pre_svc/ffmpeg, stt)
    vllm.py             vLLM (Qwen) correction client
    vision.py           agent-vision trigger
  correct/              subtitle correction logic
    corrector.py        segments → corrected (per-page parallel)
    chunk.py            segments → page split
    prompt.py           correction prompt
  debug.py              per-step dump (inspection, write-only)
  log.py                shared logger (file + console)
```

## Configuration (.env)

Copy `.env.example` to `.env` and fill in the values.

| Key | Description |
|---|---|
| `HOST` / `PORT` | this server's (FastAPI) bind address/port |
| `STT_HOST` / `STT_PORT` | prep_stt server (pre_svc + stt) |
| `VLLM_HOST` / `VLLM_PORT` | vLLM (Qwen) correction server |
| `RDB_HOST` / `RDB_PORT` / `RDB_USER` / `RDB_PW` / `RDB_NAME` | MariaDB |
| `VISION_HOST` / `VISION_PORT` | agent-vision server |
| `DEBUG_DIR` | dump path for intermediate results |

## Run

```bash
uv sync                                              # install dependencies
uv run uvicorn main:app --host 0.0.0.0 --port 8000   # run (--reload for dev)
```

## Test

```bash
./test.sh                          # defaults to v_id=1
./test.sh 3 output/3/audio.wav     # specify v_id, file_path
BASE=http://localhost:8000 ./test.sh

# one-liner
curl -sS -X POST http://localhost:8000/api/v1/stt_svc \
  -H 'Content-Type: application/json' \
  -d '{"v_id":1,"file_path":"output/1/audio.wav"}'
```

Responses:
```json
{"v_id": 1, "status": "accepted"}        // accepted (processed in background)
{"v_id": 1, "status": "Not found v_id"}  // v_id not in t_video
// 429 — queue full (Retry-After header)
```

## Requirements

- Python >= 3.13
- [uv](https://docs.astral.sh/uv/)
- External services: prep_stt, vLLM (Qwen), MariaDB, agent-vision

## License

[MIT](LICENSE)
