"""2차 전사 산출물 — 값만 담는다. 함수는 두지 않는다.

만드는 쪽은 pipe_stt_whisper. 읽는 쪽은 교정뿐이다 — 1차 대사의 idx 로 찾아 [B] 로 병기한다.

워커 응답(client 의 Stt2Result)에는 flag/error 가 같이 오지만 여기엔 없다 —
게이트를 통과한 것만 담으므로 그 둘은 항상 빈 값이다.
"""
from dataclasses import dataclass, field


@dataclass
class Whisper:
    """창 하나의 2차 전사 결과 (게이트 통과분)."""
    idx: int                # 1차 대사의 idx — 교정이 이걸로 찾는다
    text: str = ""


@dataclass
class Whispers:
    """영상 하나의 2차 전사 결과.

    **전체가 아니라 부분이다** — 보낼 만한 구간만 골라 보내고, 그중 게이트를 통과한 것만
    담는다. 없는 idx 는 '2차 없음'이고, 교정이 1차 텍스트를 그대로 쓴다.
    """
    items: list[Whisper] = field(default_factory=list)
