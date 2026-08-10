"""할루시 필터의 규칙 판정 — 순수 함수만. (pipe_hallu.py 가 쓴다)

LLM 도 외부 호출도 안 쓴다. 셋뿐:
  main_lang()  주언어 결정 (최빈 lang) — 후보 추출의 기준
  too_fast()   발화 속도로 환각 판정 — LLM 과 무관하게 먼저 치는 규칙
  renumber()   drop 후 idx 재매김
"""
from collections import Counter
from dataclasses import replace

from lib.svc.audio.stt_qwen.schema_dialogue import Dialogue

# 발화 속도 상한(글자/초). 넘으면 '사람이 말한 게 아님' = 배경음악·반복 환각 → 무조건 drop.
#   사람 최대 ~10자/초(빠른 아나운서), 정상 대사 실측 최대 35자/초(0.2초로 짧게 끊긴 경우).
#   그 3배인 100 은 물리적으로 불가능한 값이라 오탐 없이 환각만 잡는다. v4 실측:
#     "Pass the mic…"(음악) 4143 / "가볍다 가벼워…"(반복) 1050 / "경상도 경상도"(반복) 460 → drop
#   언어 무관(한국어 반복 환각도 대상)이라 LLM 언어판정과 별개로 여기서 먼저 친다.
MAX_CHARS_PER_SEC = 100


def main_lang(items: list[Dialogue]) -> str:
    """최빈 lang 을 주언어로 (한국 방송이면 대개 'Korean')."""
    c = Counter(s.lang for s in items if s.lang)
    return c.most_common(1)[0][0] if c else ""


def too_fast(seg: Dialogue) -> bool:
    """발화 속도가 사람 한계(MAX_CHARS_PER_SEC)를 넘으면 True = 환각(배경음악·반복).

    dur<=0(타임스탬프 이상)이면 판정 불가라 False(=LLM 판정에 맡김). 공백은 글자수에서 뺀다.
    """
    dur = seg.end_sec - seg.start_sec
    if dur <= 0:
        return False
    return len("".join(seg.text.split())) / dur > MAX_CHARS_PER_SEC


def renumber(items: list[Dialogue]) -> list[Dialogue]:
    """drop 으로 생긴 구멍을 메워 idx 를 0,1,2… 다시 매긴다."""
    return [replace(s, idx=i) for i, s in enumerate(items)]
