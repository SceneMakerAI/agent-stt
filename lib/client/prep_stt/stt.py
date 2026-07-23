"""stt_svc 호출 — 1차 전사(Qwen3-ASR). (transport)

  POST STT_URL  SttRequest → segments

STT 는 한 번에 한 job 이라 blocking(sync)으로 끝까지 기다린다. 서버가 파이프라인을
끝까지 돌려 결과를 바로 준다(폴링 없음) — 그래서 그 한 요청만 긴 타임아웃을 준다.
"""
import httpx
from pydantic import BaseModel

import config
from lib.log import get_logger

log = get_logger(__name__)

STT_URL = f"{config.PREP_STT_BASE_URL}/stt_svc/"


class SttRequest(BaseModel):
    v_id: str
    file_path: str     # PreResponse.audio_path


class SttResponse(BaseModel):
    status: str = ""
    job_id: int | str | None = None
    error: str = ""
    segments: list[dict] = []        # 각 행: { idx, start, end, text, lang, speaker }


def stt(http: httpx.Client, vid: int, file_path: str) -> list[dict]:
    """STT — POST STT_URL 동기 호출. 5~10분 블로킹 후 segments 반환."""
    body = SttRequest(v_id=str(vid), file_path=file_path)
    r = http.post(STT_URL, json=body.model_dump(), timeout=config.STT_TIMEOUT_S)
    r.raise_for_status()
    data = r.json()
    if data.get("status") != "done":
        raise RuntimeError(f"stt {data.get('status')}: {data.get('error', '')}")
    res = SttResponse(**data)
    log.info(f"stt done: job_id={res.job_id} segments={len(res.segments)}")
    return res.segments
