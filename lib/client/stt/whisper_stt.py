"""2차 전사 (whisper) — worker-prep_stt 의 stt2_svc 호출. (transport)

  POST STT2_URL  {v_id, windows[], prompt} → results[]

같은 서버의 1차 전사(Qwen3-ASR)는 qwen_stt.py — 둘이 base URL 을 공유한다.

1차가 뽑은 구간 중 '보낼 만한 것'을 워커에 던지면, 워커가 그 구간만 seek-read 해서
whisper 로 다시 받아쓴다. 화자·시각은 1차 것을 쓰므로 텍스트만 받는다.

여기는 부르는 법만 안다. **무엇을 보낼지(구간 선정)·무엇을 채택할지(flag 게이트)는
정책이라 svc/stt_whisper 가 정한다.** 그래서 results 를 거르지 않고 그대로 돌려준다.
"""
import httpx
from pydantic import BaseModel

import config
from lib.log import get_logger

log = get_logger(__name__)

STT2_URL = f"{config.PREP_STT_BASE_URL}/stt2_svc/"


class Window(BaseModel):
    idx: int                # 창 식별자 — 워커가 그대로 되돌려줌
    start: float            # 구간 시작 (초)
    end: float              # 구간 끝 (초)
    language: str = "ko"    # 강제 언어 (자동감지 X)


class Stt2Request(BaseModel):
    v_id: str
    windows: list[Window]
    prompt: str = ""        # whisper initial_prompt (등장인물 편향). 빈 문자열이면 미적용


class Stt2Result(BaseModel):
    """창 하나의 2차 전사 결과. 보낸 windows 와 같은 순서·개수로 온다.

    flag 는 워커가 붙이는 게이트 판정이다 — 붙었으면 그 창은 신뢰할 수 없다:
      ""        신뢰 (채택 대상)
      lowconf   최저 logprob 미달 → 환각
      repeat    압축률 초과 → 반복 루프
      fallback  온도 폴백 끝까지 실패
      echo      initial_prompt 어휘를 되뱉음 (프롬프트 부작용)
      empty     whisper 가 세그먼트를 하나도 안 냄
      error     그 창 전사가 예외로 죽음 (error 에 사유)
    ⚠ 무엇을 채택할지는 정책이라 여기서 거르지 않는다 — svc/stt_whisper 가 판정한다.

    문장별 raw 지표(logprob/compress/nospeech/temp)는 응답에 안 실린다.
    워커가 stt2.json 덤프에만 남긴다 (게이트 임계 재튜닝용).
    """
    idx: int                # 보낸 창 idx 그대로 (매핑 키)
    text: str = ""          # 2차 전사 텍스트. 실패/무전사면 ""
    flag: str = ""          # 위 게이트 판정
    error: str = ""         # 그 창만 실패한 사유 (성공 시 "")


class Stt2Response(BaseModel):
    """응답 껍데기. 본체는 창별 결과 목록 하나다 (Stt2Request 와 짝)."""
    results: list[Stt2Result] = []   # 보낸 windows 와 같은 순서·개수, idx 로 매핑


def transcribe(http: httpx.Client, vid: int, windows: list[dict],  prompt: str = "") -> Stt2Response:
    """2차 전사 — POST STT2_URL → 응답 그대로 (거르지 않는다).

    windows : [{idx, start(초), end(초), language}, ...]
    """
    body = Stt2Request(v_id=str(vid), windows=[Window(**w) for w in windows], prompt=prompt)
    r = http.post(STT2_URL, json=body.model_dump(), timeout=config.STT_TIMEOUT_S)
    r.raise_for_status()
    res = Stt2Response(**r.json())
    log.info(f"stt2 응답: 요청 {len(windows)}창 → 결과 {len(res.results)}")
    return res
