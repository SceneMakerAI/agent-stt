"""대사 한 줄 — 공정이 주고받는 값. 값만 담는다. 함수는 두지 않는다.

아무것도 import 하지 않는다(dataclasses 제외). 만드는 것도 고치는 것도 바깥이 한다.

만드는 쪽은 pipe_stt_qwen.to_dialogue (워커 dict → 이 객체). 이후 파이프 전체가 이걸로 흐른다:
  correct   text 를 바꾼다
  hallu     lang(relang)·idx 를 바꾼다
  summary   start_sec / speaker / text 를 읽는다
  rdb       t_dialogue 로 넣는다 (import 하지 않고 속성만 읽는다 — 덕타이핑)

고칠 때는 새 객체를 만든다 — dataclasses.replace(seg, text=...).
제자리에서 바꾸면(seg.text = ...) 같은 객체를 들고 있는 다른 단계가 같이 바뀐다.
"""
from dataclasses import dataclass, field


@dataclass
class Dialogue:
    """대사 한 줄. 워커(Qwen3-ASR)가 만들고 t_dialogue 로 들어간다.

    시각을 두 형태로 들고 다닌다 — 워커는 문자열로만 주는데 실제 계산은 초로 하기 때문:
      start_time/end_time  'HH:MM:SS.s' 문자열. DB 컬럼(start_time/end_time)에 그대로 들어간다.
                           to_dialogue 를 거친 뒤로는 SS 가 항상 0~59다 — 워커가 59.96 을
                           '60.0' 으로 반올림해 보내는 경우가 있어 거기서 보정한다.
      start_sec/end_sec    초(소수 1자리). 만들 때 한 번 계산해 둔다.

    둘 다 두는 이유 — 안 그러면 쓰는 쪽마다 문자열을 매번 다시 파싱한다. 발화속도 판정(hallu)·
    구간 나누기(summary)·2차 전사 대상 선정(whisper)이 전부 start_sec 을 그대로 쓴다.

    ⚠ 두 형태는 항상 같은 시각이어야 한다. 시각을 고칠 일이 생기면 넷을 같이 바꿀 것.
    """
    idx: int
    start_time: str
    end_time: str
    start_sec: float
    end_sec: float
    text: str
    lang: str = ""        # 'Korean' 등
    speaker: str = ""     # 'S001'


@dataclass
class Dialogues:
    """영상 하나의 대사 전체. 스텝들이 주고받는 단위다.

    줄을 고치는 스텝(교정·할루시)은 새 Dialogues 를 만들어 돌려준다:
        replace(dialogues, items=[...])
    """
    items: list[Dialogue] = field(default_factory=list)
