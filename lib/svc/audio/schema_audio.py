"""음성 갈래의 설정과 산출물 — 값만 담는다. 함수는 두지 않는다.

Audio    는 프로파일 표(svc/profile)가 채우고 pipe_audio 가 읽는다.
AudioOut 은 pipe_audio 가 채우고 저장(svc/rdb)이 읽는다.

갈래가 자기 스위치를 정의하고(스텝이 늘면 필드가 는다), 카테고리별 값은 표가 정한다.
"""
from dataclasses import dataclass, field

from lib.svc.audio.stt_qwen.schema_dialogue import Dialogues
from lib.svc.audio.stt_whisper.schema_whisper import Whispers
from lib.svc.audio.summary.schema_summary import Summary


@dataclass(frozen=True)
class Audio:
    """음성 갈래 프로파일 — 스텝 on/off.

    correct_glossary 는 '용어집을 쓸지'만 정한다. 어느 종목 목록인지는 카테고리가 정하므로
    (프로파일 표가 조회한다) 여기엔 스위치만 둔다.
    """
    search: bool = False            # WEB Search
    stt_qwen: bool = True           # 1차 전사
    stt_whisper: bool = False       # 2차 전사
    correct: bool = True            # 1차 2차 전사 교정
    correct_glossary: bool = False  # 스포츠 기본 용어집 (축구, 야구)
    hallu: bool = True              # 할루시 의심 메시지 제외
    summary: bool = False           # 중간/전체 summary 수집


@dataclass
class AudioOut:
    """음성 갈래 산출물 — 각 스텝이 돌려준 것을 그대로 담는다. 저장(svc/rdb)이 꺼내 쓴다.

    스텝이 꺼져 있으면 그 필드는 기본값(빈 것)으로 남는다.
    """
    dialogue: Dialogues = field(default_factory=Dialogues)     # 1차 STT
    whisper: Whispers = field(default_factory=Whispers)        # 2차 전사 (게이트 통과분)
    dialogue_clean: Dialogues = field(default_factory=Dialogues)  # 할루시 통과 → t_dialogue
    summary: Summary = field(default_factory=Summary)          # → t_video.summary_stt
                                                               #   + t_dialogue_summary
    search_query: str = ""     # 검색 질의   → t_video.search_query
    search_result: str = ""    # 검색 명단   → t_video.search_result
