"""agent-vision 호출 — ⑦ 다음 단계 트리거. (transport 계층)

STT 자막을 DB 에 다 넣은 뒤, 영상 분석을 agent-vision 에 넘긴다:
  POST /api/v1/analyze  {v_id, force}

httpx.Client(sync) 외부 주입 — prep_stt 와 동일하게 공유 클라이언트를 쓴다.
"""
import httpx

import config
from lib.log import get_logger

log = get_logger(__name__)


def agent_vision(http: httpx.Client, v_id: int, force: bool = False,
                 prep_res: dict | None = None) -> dict:
    """agent-vision 에 분석 요청. POST /api/v1/analyze → 응답 JSON 반환.

    prep_res 는 prep_svc 응답 dict — 영상청크 정보(video_chunk_cnt/last)를 꺼내 동봉한다.
    """
    prep_res = prep_res or {}
    video_chunk_cnt = prep_res.get("video_chunk_cnt", 0)
    video_chunk_last = prep_res.get("video_chunk_last", "")
    r = http.post(
        f"{config.VISION_BASE_URL}/api/v1/analyze",
        json={
            "v_id": v_id,
            "force": force,
            "video_chunk_cnt": video_chunk_cnt,
            "video_chunk_last": video_chunk_last,
        },
    )
    r.raise_for_status()
    data = r.json()
    log.info(f"vision analyze 트리거: v_id={v_id} force={force} "
             f"chunks={video_chunk_cnt} last={video_chunk_last} → {data}")
    return data
