"""worker-img_models 호출 공통 — 종목이 늘어도 이 파일은 하나다. (transport)

  POST {IMG_MODELS_BASE_URL}/sport/<종목>  {v_id, img_path} → {Result, Reason, Video}

종목별 요청/응답 DTO 는 baseball.py / soccer.py 가 갖고, 여기는 셋만 둔다:
  url()       종목 → 엔드포인트 (경로에 종목이 박혀 있다)
  post()      POST + JSON
  OK/ERR_*    Result 번호 규약 — 종목 공용이라 여기 둔다
              (worker-img_models/lib/http/http_util.py 와 같은 값. 바뀌면 같이 고칠 것)

무엇을 예외로 볼지 나눈다:
  연결 안 됨 / 타임아웃 / 4xx / 5xx  → 예외. 요청 자체가 실패한 것
  Result != 0                       → 정상 응답. 부르는 쪽이 번호를 보고 판단
    이미지 갈래는 '옵션'이라 실패해도 음성 결과는 살아야 한다. 그래서 워커가 거절한 것
    (프레임 0장·처리중 상한)을 예외로 올리지 않고 번호로 돌려준다.

httpx.Client(sync) 외부 주입 — vision/prep_stt 와 동일하게 공유 클라이언트를 쓴다.
블로킹이므로 호출부(이미지 갈래)가 to_thread 로 넘긴다.
"""
import httpx

import config
from lib.log import get_logger

log = get_logger(__name__)

# Result 번호. worker 가 이 값으로 돌려준다.
OK = 0
ERR_INPUT = 1        # 요청이 잘못됨 (없는 경로, 셋 다 없음 등)
ERR_NO_FRAME = 2     # 경로는 왔는데 읽을 jpg 가 0장
ERR_BUSY = 10        # 워커가 처리 중 + 대기가 상한(MAX_INFLIGHT)에 걸림


def url(sport: str) -> str:
    """종목 → 엔드포인트. 워커는 종목마다 라우터가 따로다 (/sport/baseball, /sport/soccer)."""
    return f"{config.IMG_MODELS_BASE_URL}/sport/{sport}"


def post(http: httpx.Client, sport: str, payload: dict) -> dict:
    """POST → 응답 JSON(dict). 파싱은 종목 모듈이 한다.

    timeout 은 넉넉히 — 프레임 12,586장 추론이 4분대다 (config.IMG_MODELS_TIMEOUT_S).
    """
    r = http.post(url(sport), json=payload, timeout=config.IMG_MODELS_TIMEOUT_S)
    r.raise_for_status()
    return r.json()
