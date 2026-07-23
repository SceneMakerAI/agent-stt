"""자막 교정 프로세스 — segments → 교정된 segments. (하나의 '프로세스')

pipeline 은 이 correct() 하나만 호출한다. 내부에서 셋을 묶는다:
  1. _split        : segments 를 페이지로 나눔
  2. 페이지별 병렬  : prompt.build → vllm.chat  (asyncio.gather, Semaphore 가 동시성 제한)
  3. 취합          : 응답 JSON 파싱 → idx 로 원본의 text 만 교체 (메타는 그대로)

실패한 페이지(호출 오류·JSON 깨짐·idx 불일치)는 '원문 유지'로 안전하게 fallback.
자막은 한 줄도 빠지면 안 되므로, 교정 실패 < 원문 보존.
"""
import asyncio
import json

from lib.client.vllm import VLLMClient
from lib.svc.stt.correct import prompt_common as prompt
from lib.log import get_logger

log = get_logger(__name__)

PAGE_MAX_SEGMENTS = 30   # 페이지당(=LLM 호출당) 최대 자막 줄 수

# 교정 결과가 원문 대비 이 비율 미만이면 '말이 잘렸다'로 보고 그 줄만 원문 유지.
# [B] 가 뒷부분을 흘린 구간에서 결합이 원문 꼬리까지 깎는 일이 남아 있어서(v1 0~3분 2~3곳)
# 코드로 막는다. 프롬프트로 막으면 그 문구 값만큼 교정을 덜 하게 된다(제동 1개당 GT −5 실측).
MIN_KEEP_RATIO = 0.7


def _split(segments: list[dict], size: int = PAGE_MAX_SEGMENTS) -> list[list[dict]]:
    """segments 를 size 개씩 연속 페이지로 분할 → 페이지 리스트.

    긴 자막을 통째로 보내면 모델이 줄을 빠뜨리거나 토큰 한계에 걸리므로 나눈다.
    각 segment 의 idx 는 그대로 유지(전역 인덱스) → 나중에 merge 가 idx 로 메타 복원.
    """
    return [segments[i:i + size] for i in range(0, len(segments), size)]


async def correct(vllm: VLLMClient, segments: list[dict], roster: str = "", req=None,
                  whisper_map: dict[int, str] | None = None) -> list[dict]:
    """segments 전체 교정 → 같은 구조의 corrected segments (text 만 교정, 메타 유지).

    참고자료 셋을 각 페이지 프롬프트에 싣는다 (없으면 해당 섹션 생략 → 기존 동작):
      roster      : 등장인물·선수 명단 — 인물 이름 표기의 근거
      req         : 영상 정보(제목/카테고리/방송연도) + 카테고리 용어집
      whisper_map : 2차 전사 {idx: text} — 같은 오디오의 '두 번째 의견'. 이름 아닌
                    오인식(자치계→좌측에)을 대조로 잡는다. 없는 idx 는 1차만으로 교정.
    """
    whisper_map = whisper_map or {}
    pages = _split(segments)
    log.info(f"correct: {len(segments)} segments → {len(pages)} pages "
             f"(roster {len(roster)}자, whisper {len(whisper_map)}건)")

    # 페이지별 교정을 한꺼번에 띄움. 실제 동시 호출 수는 vllm 내부 Semaphore 가 제한.
    page_fixes = await asyncio.gather(
        *[_correct_page(vllm, p, roster, req, whisper_map) for p in pages])

    # 취합: 모든 페이지의 { idx: 교정 text } 를 하나로 합침.
    fixed_text: dict[int, str] = {}
    for m in page_fixes:
        fixed_text.update(m)

    # 원본 segment 에 text 만 갈아끼움 (메타는 그대로). idx 없으면 원문 유지.
    out, truncated = [], 0
    for seg in segments:
        new = dict(seg)
        text = fixed_text.get(seg["idx"], seg["text"])
        if len(text) < len(seg["text"]) * MIN_KEEP_RATIO:   # 말이 잘림 → 그 줄만 원문
            text = seg["text"]
            truncated += 1
        new["text"] = text
        out.append(new)
    if truncated:
        log.info(f"correct: 길이 미달로 원문 유지 {truncated}줄 (<{MIN_KEEP_RATIO:.0%})")
    return out


async def _correct_page(vllm: VLLMClient, page: list[dict], roster: str = "", req=None,
                        whisper_map: dict[int, str] | None = None) -> dict[int, str]:
    """페이지 1개 교정 → { idx: 교정 text }. 실패 시 원문 맵 그대로 반환."""
    original = {seg["idx"]: seg["text"] for seg in page}
    span = f"[{page[0]['idx']}~{page[-1]['idx']}]"

    try:
        text, ms = await vllm.chat(
            messages=prompt.build(page, roster, req, whisper_map),
            temperature=0.1,   # 이름 교정 recall 확보용. 과교정은 카테고리 용어집이 막아줌
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
