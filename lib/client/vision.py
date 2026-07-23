"""agent-vision 호출 — ⑦ 다음 단계 트리거. (transport 계층)

STT 자막을 DB 에 다 넣은 뒤, 영상 분석을 agent-vision 에 넘긴다:
  POST /api/v1/analyze  {v_id, force}

httpx.Client(sync) 외부 주입 — prep_stt 와 동일하게 공유 클라이언트를 쓴다.
"""
import httpx
from pydantic import BaseModel

import config
from lib.log import get_logger

log = get_logger(__name__)

ANALYZE_URL = f"{config.VISION_BASE_URL}/api/v1/analyze"


# ── 요청 메시지 (POST ANALYZE_URL) — 보내는 필드는 여기가 전부
class AnalyzeRequest(BaseModel):
    v_id: int
    force: bool = False
    video_chunk_cnt: int = 0     # prep_svc 응답에서 옴
    video_chunk_last: str = ""   # prep_svc 응답에서 옴 (마지막 청크 파일명)


def agent_vision(http: httpx.Client, v_id: int, force: bool = False,
                 video_chunk_cnt: int = 0, video_chunk_last: str = "") -> dict:
    """agent-vision 에 분석 요청. POST ANALYZE_URL → 응답 JSON 반환.

    영상청크 정보(video_chunk_cnt/last)는 prep_svc 응답(PreResponse)에서 온다 — 호출자가 꺼내 넘김.
    """
    body = AnalyzeRequest(
        v_id=v_id,
        force=force,
        video_chunk_cnt=video_chunk_cnt,
        video_chunk_last=video_chunk_last,
    )
    r = http.post(ANALYZE_URL, json=body.model_dump())
    r.raise_for_status()
    data = r.json()
    log.info(f"vision analyze 트리거: {body} → {data}")
    return data
