"""agent-vision 호출 — ⑦ 다음 단계 트리거. (transport 계층)

STT 자막을 DB 에 다 넣은 뒤, 영상 분석을 agent-vision 에 넘긴다:
  POST /api/v1/analyze  {v_id, force}

httpx.Client(sync) 외부 주입 — prep_stt 와 동일하게 공유 클라이언트를 쓴다.
"""
import httpx

import config
from lib.log import get_logger

log = get_logger(__name__)


def agent_vision(http: httpx.Client, v_id: int, force: bool = False) -> dict:
    """agent-vision 에 분석 요청. POST /api/v1/analyze {v_id, force} → 응답 JSON 반환."""
    r = http.post(
        f"{config.VISION_BASE_URL}/api/v1/analyze",
        json={"v_id": v_id, "force": force},
    )
    r.raise_for_status()
    data = r.json()
    log.info(f"vision analyze 트리거: v_id={v_id} force={force} → {data}")
    return data
