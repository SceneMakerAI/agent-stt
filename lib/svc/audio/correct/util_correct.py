"""교정의 보조 함수 — 순수 함수만. (pipe_correct.py 가 쓴다)

LLM 도 외부 호출도 안 쓴다. 둘뿐:
  split()  대사 → 페이지(LLM 호출 단위)
  merge()  교정 결과를 원본에 되붙임 + 잘린 줄 되돌리기

원본은 안 건드린다 — merge 가 replace 로 새 줄을 만든다. 원문이 남아 있어야
'잘렸으면 되돌리기'(MIN_KEEP_RATIO)와 실패 페이지 폴백이 가능하다.
"""
from dataclasses import replace

from lib.svc.audio.stt_qwen.schema_dialogue import Dialogue

PAGE_MAX_SEGMENTS = 30   # 페이지당(=LLM 호출당) 최대 자막 줄 수

# 교정 결과가 원문 대비 이 비율 미만이면 '말이 잘렸다'로 보고 그 줄만 원문 유지.
# [B] 가 뒷부분을 흘린 구간에서 결합이 원문 꼬리까지 깎는 일이 남아 있어서(v1 0~3분 2~3곳)
# 코드로 막는다. 프롬프트로 막으면 그 문구 값만큼 교정을 덜 하게 된다(제동 1개당 GT −5 실측).
MIN_KEEP_RATIO = 0.7


def split(items: list[Dialogue], size: int = PAGE_MAX_SEGMENTS) -> list[list[Dialogue]]:
    """대사를 size 개씩 연속 페이지로 분할 → 페이지 리스트.

    긴 자막을 통째로 보내면 모델이 줄을 빠뜨리거나 토큰 한계에 걸리므로 나눈다.
    각 줄의 idx 는 그대로 유지(전역 인덱스) → 나중에 merge 가 idx 로 되붙인다.
    """
    return [items[i:i + size] for i in range(0, len(items), size)]


def merge(items: list[Dialogue], fixed_text: dict[int, str]) -> tuple[list[Dialogue], int]:
    """원본 줄에 교정 text 만 갈아끼움 (나머지 필드는 그대로) → (결과, 원문유지 줄 수).

    idx 가 fixed_text 에 없으면 원문 유지. 교정 결과가 MIN_KEEP_RATIO 미만으로 짧으면
    '말이 잘렸다'로 보고 그 줄만 원문으로 되돌린다.
    """
    out, truncated = [], 0
    for seg in items:
        text = fixed_text.get(seg.idx, seg.text)
        if len(text) < len(seg.text) * MIN_KEEP_RATIO:   # 말이 잘림 → 그 줄만 원문
            text = seg.text
            truncated += 1
        out.append(replace(seg, text=text))
    return out, truncated
