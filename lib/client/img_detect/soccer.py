"""축구 프레임 추론 호출 — worker-img_models /sport/soccer. (transport)

⚠ **아직 껍데기다.** 워커에 축구 모델(lib/model_soccer/)과 /sport/soccer 라우터가 없다.
   detect() 는 NotImplementedError 를 던진다 — 프로파일에 축구가 켜져 있는데 여기로
   들어오면 조용히 빈 결과를 주는 대신 시끄럽게 실패해야 한다.

호출 규약(엔드포인트 모양·Result 번호·img_path 상대경로)은 종목 무관이라 야구와 같다.
그래서 요청 DTO 는 지금 확정할 수 있다. 남은 건 응답뿐:

   ❓ 축구 응답이 야구와 같은 스키마인가?
     같다면  → baseball.Video 를 그대로 재사용하고, 이 파일은 detect() 만 채우면 끝.
     다르다면 → 축구 전용 Video/Frame 을 여기에 두고, **저장 로직도 종목별로 갈린다**
                (야구는 스코어보드 4테이블 기준). 프로파일에 detector 키 하나 넣는 걸로
                안 끝나므로, 축구 모델이 나오기 전에 이걸 먼저 정해야 한다.
"""
import httpx
from pydantic import BaseModel

from lib.log import get_logger

log = get_logger(__name__)

SPORT = "soccer"


# ── 요청 — 야구와 동일 (워커의 HTTP 계층이 종목 무관이라 여기는 확정)
class Request(BaseModel):
    v_id: int          # t_video.v_id
    img_path: str      # 워커 IMG_PATH 기준 상대 경로


def detect(http: httpx.Client, v_id: int, img_path: str) -> None:
    """축구 프레임 추론 — 미구현. 시그니처만 야구와 맞춰 둔다.

    워커에 /sport/soccer 가 생기면 baseball.detect 와 같은 모양으로 채운다
    (img_detect.post → Response 파싱 → Result 검사 → 로그).
    """
    raise NotImplementedError(
        f"축구 검출 미구현: v_id={v_id} path={img_path!r} — "
        "worker-img_models 에 /sport/soccer 가 아직 없다")
