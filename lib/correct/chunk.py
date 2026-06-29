"""segments → vLLM 교정용 '페이지' 로 분할.

페이지 = 연속된 segment 묶음 (기본 config.PAGE_MAX_SEGMENTS 개).
긴 자막을 통째로 보내면 모델이 줄을 빠뜨리거나 토큰 한계에 걸리므로 나눈다.
페이지끼리 독립이라 vLLM 에 병렬로 보낼 수 있다 (Map).

여기서는 '자르기'만 한다. 메타(start/speaker/lang)를 LLM 에 줄지 말지는
corrector/prompt 가 결정(idx + text 만 추출)하고, 메타 보존·재결합은 idx 로 merge 가 담당.
"""
import config


def split(segments: list[dict], size: int = 0) -> list[list[dict]]:
    """segments 를 size 개씩 연속 페이지로 분할 → 페이지 리스트.

    size 0 이면 config.PAGE_MAX_SEGMENTS 사용. 빈 입력 → 빈 리스트.
    각 segment 의 idx 는 그대로 유지(전역 인덱스) → 나중에 merge 가 idx 로 메타 복원.
    """
    size = size or config.PAGE_MAX_SEGMENTS
    return [segments[i:i + size] for i in range(0, len(segments), size)]
