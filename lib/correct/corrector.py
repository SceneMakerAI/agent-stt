"""자막 교정 프로세스 — segments → 교정된 segments. (하나의 '프로세스')

pipeline 은 이 correct() 하나만 호출한다. 내부에서 셋을 묶는다:
  1. chunk.split   : segments 를 페이지로 나눔
  2. 페이지별 병렬  : prompt.build → vllm.chat  (asyncio.gather, Semaphore 가 동시성 제한)
  3. 취합          : 응답 JSON 파싱 → idx 로 원본의 text 만 교체 (메타는 그대로)

실패한 페이지(호출 오류·JSON 깨짐·idx 불일치)는 '원문 유지'로 안전하게 fallback.
자막은 한 줄도 빠지면 안 되므로, 교정 실패 < 원문 보존.
"""
import asyncio
import json

from lib.client.vllm import VLLMClient
from lib.correct import chunk, prompt
from lib.log import get_logger

log = get_logger(__name__)


async def correct(vllm: VLLMClient, segments: list[dict]) -> list[dict]:
    """segments 전체 교정 → 같은 구조의 corrected segments (text 만 교정, 메타 유지)."""
    pages = chunk.split(segments)
    log.info(f"correct: {len(segments)} segments → {len(pages)} pages")

    # 페이지별 교정을 한꺼번에 띄움. 실제 동시 호출 수는 vllm 내부 Semaphore 가 제한.
    page_fixes = await asyncio.gather(*[_correct_page(vllm, p) for p in pages])

    # 취합: 모든 페이지의 { idx: 교정 text } 를 하나로 합침.
    fixed_text: dict[int, str] = {}
    for m in page_fixes:
        fixed_text.update(m)

    # 원본 segment 에 text 만 갈아끼움 (메타는 그대로). idx 없으면 원문 유지.
    out = []
    for seg in segments:
        new = dict(seg)
        new["text"] = fixed_text.get(seg["idx"], seg["text"])
        out.append(new)
    return out


async def _correct_page(vllm: VLLMClient, page: list[dict]) -> dict[int, str]:
    """페이지 1개 교정 → { idx: 교정 text }. 실패 시 원문 맵 그대로 반환."""
    original = {seg["idx"]: seg["text"] for seg in page}
    span = f"[{page[0]['idx']}~{page[-1]['idx']}]"

    try:
        text, ms = await vllm.chat(
            messages=prompt.build(page),
            response_format={"type": "json_object"},
            extra_body={"chat_template_kwargs": {"enable_thinking": False}},
        )
        result = {ln["idx"]: ln["text"] for ln in json.loads(text)["lines"]}
    except Exception as e:  # noqa: BLE001 — 페이지 단위 격리(호출/파싱 실패)
        log.warning(f"page {span} 교정 실패 → 원문 유지: {e}")
        return original

    # 검증: idx 집합이 입력과 정확히 일치해야 신뢰. 다르면(누락/추가) 원문 유지.
    if set(result) != set(original):
        log.warning(f"page {span} idx 불일치 → 원문 유지")
        return original

    log.info(f"page {span} 교정 완료 ({ms}ms)")
    return result
