"""2차 전사 대상 선정에 쓰는 텍스트 측정 — 순수 함수만. (pipe_stt_whisper.py 가 쓴다)

값을 재기만 한다. 그 값으로 보낼지 말지 정하는 기준(MIN_CHARS/MIN_KO)은 pipe 가 갖는다.
"""
import re


def chars(text: str) -> int:
    """공백·문장부호 뺀 글자수 (내용 밀도)."""
    return len(re.sub(r"[\s.,!?~·'\"]", "", text))


def ko_ratio(text: str) -> float:
    """글자 중 한글 비율. 분모 = 한글+라틴+한자+가나 (숫자·기호 제외).

    숫자를 분모에서 빼는 게 핵심 — "126 구톰슨의 킹머신이 1.2" 같은 통계 문장이
    숫자 때문에 외국어로 오판되면 안 된다 (구톰슨은 한글이므로 한국어).
    """
    ko = sum('가' <= c <= '힣' for c in text)
    other = sum(('一' <= c <= '鿿') or ('぀' <= c <= 'ヿ') or (c.isascii() and c.isalpha())
                for c in text)
    return ko / max(1, ko + other)
