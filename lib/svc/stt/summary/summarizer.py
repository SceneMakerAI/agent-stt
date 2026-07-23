"""요약 오케스트레이터 (청크 병렬) — 대사 → 구간 summary들 + 전체 summary.

  1. 윈도우 분할 : 대사를 start 타임스탬프 기준 SUMMARY_WINDOW_SEC 초 구간으로 묶음
  2. 청크 병렬   : 윈도우를 SUMMARY_CHUNKS 덩이로 잘라 덩이끼리 동시 실행.
                  덩이 '안'은 순차 — 직전 요약 N개를 넘겨 흐름을 잇는다(문맥 유지).
  3. 산출       : 구간별 summary 리스트(시간순) + 전체 summary 1콜

왜 이 구조인가 (v1 실측):
  - 순차 115콜 = 3분56초. 콜당 2초인데 줄줄이 기다리는 게 전부라 대기가 곧 비용.
  - 여러 구간을 한 프롬프트에 묶어 8콜로 던지면 43초로 줄지만 품질이 깨진다 —
    요약 길이 −30%, 빈 요약 6개, 구간 간 내용 오염("구톰슨의 퀵모션"→"한기주의 퀵모션").
  - 청크 병렬은 콜 하나하나가 순차 때와 동일(=품질 동일)한 채로 8줄기가 동시에 흐른다.

덩이 첫 윈도우는 앞 덩이 요약이 아직 없다 → 직전 윈도우들의 '원본 대사'로 대신 문맥을 준다
(요약과 달리 원본은 처음부터 다 있으므로 순차 의존이 없다). process(run) 가 vllm 을 넘겨 호출.
"""
import asyncio

import config
from lib.client.vllm import VLLMClient
from lib.log import get_logger
from lib.svc.stt.summary import prompt
from lib.util import time_to_sec

log = get_logger(__name__)


def _ctx(req) -> str:
    """영상 정보(제목/카테고리/방송연도) 컨텍스트 문자열. req 없으면 빈 줄."""
    if req is None:
        return "(정보 없음)"
    parts = []
    for label, key in (("제목", "title"), ("카테고리", "category"), ("방송연도", "year")):
        val = getattr(req, key, None)
        if val:
            parts.append(f"{label}: {val}")
    return " / ".join(parts) if parts else "(정보 없음)"


def _windows(segments: list[dict], window_sec: int) -> list[dict]:
    """대사를 start 초 기준 window_sec 구간으로 묶음.

    반환: [{"start_sec", "end_sec", "lines"}] — lines 는 'S002: 텍스트' 줄들.
    """
    if not segments:
        return []
    buckets: dict[int, list[dict]] = {}
    for s in segments:
        w = int(time_to_sec(s["start"]) // window_sec)   # 구간 인덱스
        buckets.setdefault(w, []).append(s)

    windows = []
    for w in sorted(buckets):
        rows = buckets[w]
        lines = "\n".join(f'{r.get("speaker","?")}: {r["text"]}' for r in rows)
        windows.append({
            "start_sec": w * window_sec,
            "end_sec": (w + 1) * window_sec,
            "lines": lines,
        })
    return windows


def _split(windows: list[dict], k: int) -> list[int]:
    """windows 를 k 덩이로 나눌 때 각 덩이의 '시작 인덱스' 목록. 앞 덩이부터 1개씩 더 갖는다."""
    n = len(windows)
    if n == 0:
        return []
    k = max(1, min(k, n))                     # 윈도우보다 덩이가 많을 순 없다
    size, rest = divmod(n, k)
    starts, i = [], 0
    for c in range(k):
        starts.append(i)
        i += size + (1 if c < rest else 0)
    return starts


async def _chunk(vllm: VLLMClient, ctx: str, windows: list[dict],
                 start: int, end: int, prev_n: int) -> list[str]:
    """windows[start:end] 를 순차 요약 → 요약 텍스트 리스트 (덩이 하나 = 코루틴 하나).

    덩이 안은 순차(직전 요약 N개를 넘겨 흐름 유지). 첫 윈도우만 앞 덩이 요약이 없으므로
    직전 윈도우들의 원본 대사를 문맥으로 대신 준다.
    """
    done: list[str] = []
    for i in range(start, end):
        w = windows[i]
        if not w["lines"].strip():                       # 대사 0줄 → LLM 콜 스킵
            done.append("")
            continue
        if any(done) or start == 0:                      # 이 덩이에서 만든 직전 요약 사용
            seg = await prompt.segment(vllm, ctx, done[-prev_n:], w["lines"])
        else:                                            # 덩이 첫 줄 → 원본 대사로 시딩
            seed = [windows[j]["lines"] for j in range(max(0, start - prev_n), start)]
            seg = await prompt.segment(vllm, ctx, [], w["lines"], prev_raw="\n".join(seed))
        done.append(seg)
    return done


async def summarize(vllm: VLLMClient, segments: list[dict],
                    req=None, window_sec: int | None = None) -> dict:
    """대사 → {window_sec, segments:[구간요약], overall}.

    2단계:
      1) 구간 요약 — SUMMARY_CHUNKS 덩이로 나눠 병렬. 덩이 안은 직전 요약 N개로 순차.
      2) 전체 요약 — 구간요약 전부를 모아 마지막에 1콜.
    """
    window_sec = window_sec or config.SUMMARY_WINDOW_SEC
    ctx = _ctx(req)
    windows = _windows(segments, window_sec)
    prev_n = config.SUMMARY_PREV_N
    starts = _split(windows, config.SUMMARY_CHUNKS)
    log.info(f"summarize: {len(segments)} dialogues → {len(windows)} windows "
             f"({window_sec}s) / {len(starts)} chunks, ctx={ctx!r}")

    # 1단계: 덩이별 코루틴을 한꺼번에 띄움 (실제 동시 호출 수는 vllm 내부 Semaphore 가 제한)
    bounds = list(zip(starts, starts[1:] + [len(windows)]))
    results = await asyncio.gather(
        *[_chunk(vllm, ctx, windows, a, b, prev_n) for a, b in bounds])

    texts = [t for chunk in results for t in chunk]      # 덩이 순서 = 시간 순서
    seg_summaries = [
        {"start_sec": w["start_sec"], "end_sec": w["end_sec"], "summary": t}
        for w, t in zip(windows, texts)
    ]

    # 2단계: 전체 요약 (구간요약 전부 → 1콜)
    overall = await prompt.overall(vllm, ctx, [s["summary"] for s in seg_summaries])

    return {"window_sec": window_sec, "segments": seg_summaries, "overall": overall}
