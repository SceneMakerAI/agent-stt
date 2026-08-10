"""1차 전사 스텝 (Qwen3-ASR) — 오디오 → 대사 줄. 파이프에 내보내기 전까지를 책임진다.

이 디렉토리의 **진입점**이다. 바깥(pipe_audio)은 이 파일만 부른다.
2차 전사(whisper)는 성격이 완전히 달라 별도다 — 입력(구간 목록)도 출력(부분 맵)도 다르고
공유하는 로직이 없다.

  qwen_stt.transcribe (client, 블로킹) → 변환·검증(to_dialogue) → Dialogues

client 는 '부르는 법'만 안다(URL·DTO·타임아웃). **워커 출력을 파이프가 쓸 수 있는 값으로
만드는 건 여기 일이다** — 시각 정규화가 늦어지면 그 사이 스텝들이 깨진 값으로 계산하고
(할루시 필터의 발화속도 판정), 키 누락은 저장 직전에야 터진다.

Dialogue 는 svc 의 자료구조라 변환도 여기서 한다. client 가 이걸 알면 transport 가 svc 를
import 하는 역방향이 된다.
"""
import asyncio

import httpx

from lib.client.stt import qwen_stt
from lib.log import get_logger
from lib.svc.audio.stt_qwen.schema_dialogue import Dialogue, Dialogues
from lib.svc.audio.stt_qwen.util import norm_time, time_to_sec

log = get_logger(__name__)

# 없으면 구조가 깨진 것 — 뒤 스텝이 idx 로 병합·재색인하고 text 를 교정한다.
REQUIRED = ("idx", "start", "end", "text")


def to_dialogue(segments: list[dict]) -> list[Dialogue]:
    """워커 응답(dict) → Dialogue 목록.

    1) 필수 키 검사 — 없으면 예외. 워커 계약이 깨진 것이라 조용히 넘기면 5분 뒤
       DB INSERT 에서 터진다.
    2) 시각 정규화 — 워커가 s=59.96 을 '60.0' 으로 반올림해 보내는 경우가 있다
       ('01:39:60.0'). MariaDB TIME 이 거부하고 초 계산도 틀어진다 → '01:40:00.0'
    3) 초 계산 — 정규화된 문자열에서 뽑는다. 두 형태가 항상 같은 시각이어야 하므로
       원본이 아니라 **정규화 결과**에서 계산할 것.
    4) lang/speaker 는 없으면 "" (Dialogue 기본값). rdb 가 그대로 INSERT 한다.
    """
    out = []
    for i, s in enumerate(segments):
        missing = [k for k in REQUIRED if k not in s]
        if missing:
            raise ValueError(f"STT 결과 {i}번째 줄에 필수 키 없음: {missing} (keys={list(s)})")
        start, end = norm_time(s["start"]), norm_time(s["end"])
        out.append(Dialogue(
            idx=s["idx"],
            start_time=start,
            end_time=end,
            start_sec=time_to_sec(start),
            end_sec=time_to_sec(end),
            text=s["text"],
            lang=s.get("lang", ""),
            speaker=s.get("speaker", ""),
        ))
    return out


def reversed_count(segments: list[Dialogue]) -> int:
    """end < start 인 줄 수 (타임스탬프 역전). 고치지는 않고 세기만 한다 —
    무엇이 맞는지 알 수 없어 손대면 오히려 틀린다. 품질 신호로만 남긴다."""
    return sum(1 for s in segments if s.end_sec < s.start_sec)


async def run(http: httpx.Client, v_id: int, audio_path: str) -> Dialogues:
    """오디오 → 영상 하나의 대사 전체(Dialogues). 전사는 블로킹(5~10분)이라 스레드로 넘긴다.

    client 가 준 워커 표현(dict)을 여기서 우리 자료구조로 바꾼다 — 이 뒤로 파이프에는
    dict 가 흐르지 않는다. 구조가 깨진 게 발견되면(필수 키 없음) 여기서 예외가 난다.
    """
    segments = await asyncio.to_thread(qwen_stt.transcribe, http, v_id, audio_path)

    items = to_dialogue(segments)
    if not items:
        log.warning(f"stt v_id={v_id} 대사 0줄 — 무음이거나 전사 실패")
    rev = reversed_count(items)
    if rev:
        log.warning(f"stt v_id={v_id} 타임스탬프 역전 {rev}줄 (end<start) — 그대로 진행")
    log.info(f"stt v_id={v_id} {len(items)}줄")
    return Dialogues(items=items)
