"""이미지 갈래 — 영상 1건의 프레임 공정. 종목별 검출 워커를 부른다.

이 디렉토리의 **진입점**이다. 바깥(pipeline)은 이 파일만 부른다.

  프레임 경로 → img_detect 워커(종목별) → Video

음성 갈래와 병렬로 돈다 (워커 GPU 가 다르다). **음성과 이미지 둘 다 중요하므로 실패는
예외로 올린다** — pipeline 이 받아 나머지 갈래를 접고 그 영상을 실패로 남긴다. 반쪽만
저장하면 그 영상이 완료인지 아닌지 알 수 없게 된다.

예외: 미지원 종목만 아직 빈 결과로 넘어간다 (축구 워커가 아직 없다 — 생기면 이것도 실패로).

검출 워커는 자기 IMG_PATH 아래에 **이미 있는** jpg 를 읽을 뿐이다. 프레임을 거기 떨구는 건
선행 스텝(ffmpeg)이라, frame_path() 의 규칙이 그쪽과 어긋나면 '디렉터리가 아니다'로 거절된다.
"""
import asyncio

from lib.client.img_detect import baseball, img_detect, soccer
from lib.log import get_logger
from lib.svc.image.schema_image import ImageOut

log = get_logger(__name__)

# 종목 → 호출할 client. 종목이 늘면 여기 한 줄. 표에 없으면 검출을 건너뛴다.
DETECT = {
    "baseball": baseball.detect,
    "soccer": soccer.detect,
}

def frame_path(v_id: int) -> str:
    """v_id → 워커 IMG_PATH 기준 상대 경로. 프레임을 떨구는 쪽과 이 규칙이 같아야 한다.

    ffmpeg 워커가 영상 디렉토리 바로 아래에 프레임을 깐다 (/mnt/nvme/vod/203/00000.jpg).
    source.mp4·audio.wav 와 같은 자리다 — 검출 워커는 그중 jpg 만 읽는다.
    """
    return f"{v_id}"


async def run(state, v_id: int, sport: str) -> ImageOut:
    """프레임 검출 → ImageOut. 실패는 예외로 올린다 (pipeline 이 전체 실패로 처리).

    sport : 프로파일이 고른 종목 키("baseball"/"soccer"). "" 면 호출측이 이 갈래를 안 띄운다.
    추론은 블로킹(프레임 12,586장 ≈ 4분)이라 스레드로 넘긴다. 동시 호출 수는 접수 상한
    (MAX_REQ_CNT)이 이미 잡고 있다 — 요청 1건이 이 워커를 한 번만 부르기 때문이다.

    워커 거절(Result != 0)도 실패다 — 프레임이 0장이거나 경로가 틀린 것이라, 그대로 두면
    '이미지 없는 완료'가 되어 나중에 뭐가 빠졌는지 알 수 없다.
    """
    detect = DETECT.get(sport)
    if detect is None:
        log.warning(f"[image] v_id={v_id} 미지원 종목 {sport!r} — 검출 건너뜀")
        return ImageOut()

    path = frame_path(v_id)
    res = await asyncio.to_thread(detect, state.http, v_id, path)   # 연결 실패·5xx 는 그대로 올라간다
    if res.Result != img_detect.OK:
        raise RuntimeError(f"이미지 검출 거절 v_id={v_id} {sport} path={path!r}: "
                           f"Result={res.Result} ({res.Reason})")

    n = len(res.Video.FRAME) if res.Video else 0
    log.info(f"[image] v_id={v_id} {sport} 완료: {n}프레임")
    return ImageOut(video=res.Video)
