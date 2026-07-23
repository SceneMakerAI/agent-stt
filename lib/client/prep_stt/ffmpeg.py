"""prep_svc 호출 — 영상 원본 → 음성(audio.wav) 추출. (transport)

  POST PRE_URL  PreRequest → PreResponse

httpx.Client(sync)를 외부 주입받는다 — 프로세스당 1개 공유. 결과는 메모리로만 반환.
"""
import httpx
from pydantic import BaseModel

import config
from lib.log import get_logger

log = get_logger(__name__)

PRE_URL = f"{config.PREP_STT_BASE_URL}/pre_svc/"


class PreRequest(BaseModel):
    v_id: str               # 서버가 문자열을 받음 — 호출부에서 str(vid)
    file_path: str          # 원본 영상 경로/키


class PreResponse(BaseModel):
    job_id: str                      # 서버가 v_id 를 job_id 로 되돌림
    status: str = "OK"               # 성공 "OK", 실패 시 에러 원인 메시지
    video_path: str = ""             # NVMe 원본 경로 (output/{vid}/source.*)
    audio_path: str = ""             # 전체 오디오 (output/{vid}/audio.wav) — STT 입력


def prep(http: httpx.Client, vid: int, file: str) -> PreResponse:
    """prep_svc — POST PRE_URL 동기 호출 → PreResponse.

    영상 원본(file)을 받아 ffmpeg 로 음성(audio.wav) 추출.
    """
    body = PreRequest(v_id=str(vid), file_path=file)
    r = http.post(
        PRE_URL,
        json=body.model_dump(),
        timeout=config.PREP_TIMEOUT_S,     # ffmpeg 가 client 기본 30s 보다 오래 걸림
    )
    r.raise_for_status()
    data = r.json()
    if str(data.get("status", "")).upper() != "OK":   # 서버가 'OK'/'ok' 혼용. 실패 시 에러 원인 메시지
        raise RuntimeError(f"prep failed: {data.get('status')}")
    res = PreResponse(**data)
    log.info(f"prep ffmpeg done: {res}")
    return res
