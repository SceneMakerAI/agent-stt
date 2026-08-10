"""요약 산출물 — 값만 담는다. 함수는 두지 않는다.

만드는 쪽은 pipe_summary. 읽는 쪽은 저장(rdb)뿐이다:
  Section → t_dialogue_summary 한 행
  Summary.overall → t_video.summary_stt
"""
from dataclasses import dataclass, field


@dataclass
class Section:
    """구간 요약 하나. 요약할 내용이 없으면 summary 가 ""."""
    start_sec: int
    end_sec: int
    summary: str = ""


@dataclass
class Summary:
    """영상 하나의 요약 전체. overall 은 영상당 1개라 구간이 아니라 여기 둔다."""
    overall: str = ""
    sections: list[Section] = field(default_factory=list)
