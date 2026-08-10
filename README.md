# stt-agent

A **subtitle pipeline orchestrator** (FastAPI) for one video. Takes a `v_id`, runs the audio branch
and the image branch in parallel, and saves to DB once both finish. HTTP replies `accepted`
immediately; the work runs in the background.

[한국어 README](README.ko.md)

## The pipeline differs per category

The core idea is the **category table** (`lib/svc/profile.py`). Step order is the same for every
category — the table only decides **which steps run and what material they get**.

| Category | Web search | 2nd pass ASR | Glossary | Summary | Frame detection |
|---|---|---|---|---|---|
| Sports-Baseball | O | O | baseball | ✕ | baseball |
| Sports-Soccer | O | O | soccer | ✕ | soccer |
| Drama | O | O | — | O | — |
| Documentary · News | ✕ | ✕ | — | O | — |

Unlisted categories fall back to their prefix (`드라마-사극` → `드라마`), then to a default.
**This table is the only place that interprets the category string** — the pipeline and the steps
only see the switches it hands them.

## Flow

```
POST /api/v1/stt_svc {v_id, file_path, title, category, year}
        │  status 1001 (accepted) + immediate "accepted" response
        │
        └─ background (svc/pipeline)
             profile.resolve(category)
             (ffmpeg) source → audio.wav + frames/          ← shared prep for both branches
                    ├── audio branch  (search) → ASR → (2nd pass) → correct → hallu → (summary)
                    └── image branch  detection worker (per sport)
                              ↓ join
                          one transaction → status 1006 (done) → agent-vision trigger
```

- **ffmpeg is not a branch** — it produces the material for both, so it finishes before the
  fan-out. Inside a branch, detection would be called before any frame exists and get rejected.
- The two branches hit **GPUs on different boxes**, so they really do run in parallel.
- **Both matter** — if either fails, the other is cancelled and everything rolls back (status `-1`).
  A half-saved video can't be told apart from a finished one.
- Blocking calls (worker HTTP, DB) go through `asyncio.to_thread` so the event loop stays free.
- The final **agent-vision trigger** only fires when `VISION_TRIGGER` is on in `.env`. It runs after
  the save, so a failure there is logged but never flips a finished video back to failed.

## Source layout (rough)

```
main.py / config.py
lib/
  http/      intake router — backpressure + status 1001 only; hands the work to svc
  svc/       the pipeline. pipeline.py (whole run) + profile.py (category table)
             ffmpeg/ audio/ image/ rdb/ — branches and steps; one pipe_*.py entry per directory
  client/    outbound calls only (ASR, search engine, detection worker, vLLM, MariaDB) — no policy
```

Files are named `<function>_<module>.py` — `pipe_search.py` / `vllm_hallu.py` / `util_correct.py` /
`schema_dialogue.py`. Everything flowing through the pipeline is a dataclass (`svc/**/schema_*.py`).

## Design notes

- **Single endpoint** `POST /api/v1/stt_svc` — respond on arrival, run via `BackgroundTasks`.
- **Shared resources** (vLLM client / httpx / semaphores / counter) are built once in `lifespan`
  and shared through `app.state`.
- **Concurrency** — `MAX_REQ_CNT` caps both intake and the per-worker semaphores (429 beyond it).
  Only vLLM has its own limit (`VLLM_CONCURRENCY`).
- **Save atomicity** — the transaction is opened in exactly one place (`svc/rdb/save_svc.py`);
  failures raise so the whole thing rolls back.
- **Stage tracking** — failures log the `stage` (ffmpeg/stt/correct/…).

## Configuration (.env)

Copy `.env.example` to `.env` and fill it in.

| Key | Description |
|---|---|
| `HOST` / `PORT` | bind address/port for this server |
| `STT_HOST` / `STT_PORT` | prep_stt worker (ffmpeg + 1st/2nd pass ASR) |
| `VLLM_HOST` / `VLLM_PORT` | vLLM (Qwen) — search, correction, hallucination filter, summary |
| `IMG_MODELS_HOST` / `IMG_MODELS_PORT` | frame detection worker (worker-img_models) |
| `RDB_*` | MariaDB |
| `VISION_HOST` / `VISION_PORT` / `VISION_TRIGGER` | next-stage (agent-vision) trigger |
| `DUMP_DIR` / `DUMP_STEPS_*` | per-step dumps for inspection (write-only) |

> ⚠ `.env` holds the DB password — never commit it (it is in `.gitignore`).

## Running

```bash
uv sync
uv run uvicorn main:app --host 0.0.0.0 --port 19010   # add --reload for development
```

## Testing

```bash
curl -sS -X POST http://localhost:19010/api/v1/stt_svc \
  -H 'Content-Type: application/json' \
  -d '{"v_id":1,"file_path":"vod/1/1.mp4","title":"코리안시리즈 KIA vs SK",
       "category":"스포츠-야구","year":2009}'
```

Responses:
```json
{"v_id": 1, "status": "accepted"}        // queued (pipeline runs in background)
{"v_id": 1, "status": "Not found v_id"}  // no such v_id in t_video
// 429 — queue full (Retry-After header)
```

## Requirements

- Python >= 3.13, [uv](https://docs.astral.sh/uv/)
- External services: prep_stt worker, vLLM (Qwen), worker-img_models, MariaDB, agent-vision (optional)

## License

[MIT](LICENSE)
