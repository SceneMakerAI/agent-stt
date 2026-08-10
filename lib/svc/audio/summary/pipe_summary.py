"""요약 오케스트레이터 (청크 병렬) — 대사 → 구간 summary들 + 전체 summary.

이 디렉토리의 **진입점**이다. 바깥(process)은 이 파일만 import 한다.

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

파일 셋으로 나뉜다 — 이 파일은 순서와 병렬 구조만 안다:
  vllm_summary.py   LLM 콜 2종 + 프롬프트
  util_summary.py   순수 — 영상정보 / 윈도우 분할 / 덩이 경계
"""
import asyncio

import config
from lib.client.vllm import VLLMClient
from lib.log import get_logger
from lib.svc.audio.stt_qwen.schema_dialogue import Dialogues
from lib.svc.audio.summary import util_summary, vllm_summary
from lib.svc.audio.summary.schema_summary import Section, Summary

log = get_logger(__name__)


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
            seg = await vllm_summary.segment(vllm, ctx, done[-prev_n:], w["lines"])
        else:                                            # 덩이 첫 줄 → 원본 대사로 시딩
            seed = [windows[j]["lines"] for j in range(max(0, start - prev_n), start)]
            seg = await vllm_summary.segment(vllm, ctx, [], w["lines"], prev_raw="\n".join(seed))
        done.append(seg)
    return done


async def run(vllm: VLLMClient, dialogues: Dialogues, req=None) -> Summary:
    """대사 → Summary(구간 요약 + 전체 요약).

    2단계:
      1) 구간 요약 — SUMMARY_CHUNKS 덩이로 나눠 병렬. 덩이 안은 직전 요약 N개로 순차.
      2) 전체 요약 — 구간요약 전부를 모아 마지막에 1콜.
    """
    window_sec = config.SUMMARY_WINDOW_SEC
    ctx = util_summary.video_ctx(req)
    windows = util_summary.windows(dialogues.items, window_sec)
    prev_n = config.SUMMARY_PREV_N
    starts = util_summary.split(windows, config.SUMMARY_CHUNKS)
    log.info(f"summarize: {len(dialogues.items)} dialogues → {len(windows)} windows "
             f"({window_sec}s) / {len(starts)} chunks, ctx={ctx!r}")

    # 1단계: 덩이별 코루틴을 한꺼번에 띄움 (실제 동시 호출 수는 vllm 내부 Semaphore 가 제한)
    bounds = list(zip(starts, starts[1:] + [len(windows)]))
    results = await asyncio.gather(
        *[_chunk(vllm, ctx, windows, a, b, prev_n) for a, b in bounds])

    texts = [t for chunk in results for t in chunk]      # 덩이 순서 = 시간 순서
    sections = [
        Section(start_sec=w["start_sec"], end_sec=w["end_sec"], summary=t)
        for w, t in zip(windows, texts)
    ]

    # 2단계: 전체 요약 (구간요약 전부 → 1콜)
    overall = await vllm_summary.overall(vllm, ctx, [s.summary for s in sections])

    return Summary(overall=overall, sections=sections)
