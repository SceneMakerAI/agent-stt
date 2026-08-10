"""야구 프레임 추론 호출 — worker-img_models /sport/baseball. (transport)

  POST /sport/baseball  {v_id, img_path} → {Result, Reason, Video}

호출 방식은 **img_path** 하나로 고정한다. 워커는 img_b64 / img_files / img_path 를 다
받지만(우선순위 그 순서), 여기서는 경로만 보낸다 — 파일 목록을 만들 필요가 없고 요청이
수백 KB 로 커지지도 않는다. 경로가 없거나 jpg 가 0장이면 워커가 Result != 0 을 준다.

⚠ img_path 는 **워커의 IMG_PATH 기준 상대 경로**다. 우리 파일시스템 경로가 아니다.
   IMG_PATH="/stg/vod/" + "scenemaker/200/frames" → /stg/vod/scenemaker/200/frames
   그래서 프레임을 뽑아 두는 쪽과 여기서 넘기는 경로 규칙이 같아야 한다.

응답 DTO 가 곧 데이터 모델이다 — 워커가 준 걸 그대로 DB 에 넣는 게 이 갈래의 일이라,
따로 둘 도메인 모델이 없다.

    Video                    v_id, BOARD_DETECT_ADJUST
     └ FRAME[]               idx, idx_time, idx_sec, detect_major_obj
        ├ CLS                {normal, pitch, board_type}
        ├ BOARD_DETECT       {board, score, x, y, w, h}
        └ BOARD_DETAIL_DETECT{team, inning, count, out, base, etc} 각각 {detect, score, x,y,w,h}

⚠ 값 -1 은 '안 돌렸다'는 뜻이다. 세 상태를 구분한다:
   -1 안 돌림(광고 프레임의 pitch, 보드 없는 프레임의 세부 항목) / 0 돌렸는데 없음 / 1 있음.
   이 값을 담는 DB 컬럼은 **signed** 여야 한다 (unsigned 면 -1 이 안 들어간다).
"""
import httpx
from pydantic import BaseModel

from lib.client.img_detect import img_detect
from lib.log import get_logger

log = get_logger(__name__)

SPORT = "baseball"

NOT_RUN = -1   # '안 돌림' 표시 (위 ⚠ 참고)


# ── 요청 (보내는 필드는 이 둘이 전부)
class Request(BaseModel):
    v_id: int          # t_video.v_id — 결과가 이 번호로 저장된다
    img_path: str      # 워커 IMG_PATH 기준 상대 경로 (디렉터리. 안의 jpg 를 파일명 순으로 전부)


# ── 응답 본문 (워커 frame.py 와 1:1. 필드명·대소문자를 그대로 맞춘다)
class Cls(BaseModel):
    """프레임 분류 3종. 번호의 의미는 워커 쪽 모델 config.json 이 정한다."""
    normal: int = NOT_RUN        # 야구 vs 광고
    pitch: int = NOT_RUN         # 투구 여부 (야구 프레임만 돈다 → 광고는 -1)
    board_type: int = NOT_RUN    # 스코어보드 종류 KBO / INTERNATIONAL / NONE


class BoardDetect(BaseModel):
    """스코어보드 자체의 박스. 있음/없음 판단은 반드시 board 로 (좌표로 하지 말 것)."""
    board: int = 0               # 0=없음 / 1=있음
    score: float = 0.0
    x: int = 0
    y: int = 0                   # 원본 프레임 기준 절대 좌표
    w: int = 0
    h: int = 0


class Detect(BaseModel):
    """보드 안 항목 하나(team/inning/…). BoardDetect 와 모양은 같고 플래그 이름만 다르다."""
    detect: int = 0              # 0=못 찾음 / 1=찾음
    score: float = 0.0
    x: int = 0
    y: int = 0
    w: int = 0
    h: int = 0


class BoardDetailDetect(BaseModel):
    """보드 세부 항목 6개. 못 찾은 항목도 빠지지 않고 항상 다 온다
    (빠뜨리면 '검출 실패'와 '안 돌림'이 구분되지 않는다)."""
    team: Detect = Detect()
    inning: Detect = Detect()
    count: Detect = Detect()
    out: Detect = Detect()
    base: Detect = Detect()
    etc: Detect = Detect()


class Box(BaseModel):
    """고정 박스 하나. 검출 결과가 아니라 계산값이라 score/detect 가 없다."""
    x: int = NOT_RUN
    y: int = NOT_RUN
    w: int = NOT_RUN
    h: int = NOT_RUN


class BoardDetectAdjust(BaseModel):
    """영상 하나의 고정 박스 7개 (프레임마다 흔들리는 박스를 전 프레임에서 굳힌 것).

    프레임당이 아니라 영상당 1개라 Frame 이 아니라 Video 에 붙는다.
    """
    board: Box = Box()
    team: Box = Box()
    inning: Box = Box()
    count: Box = Box()
    out: Box = Box()
    base: Box = Box()
    etc: Box = Box()


class Frame(BaseModel):
    """프레임 하나의 결과 전부. idx 가 키다 (프레임 파일 번호 00123.jpg → 123)."""
    idx: int = NOT_RUN
    idx_time: str = "00:00:00.0"
    idx_sec: int = NOT_RUN

    # 이 프레임 하나로 경기 상황을 얼마나 읽을 수 있는가 — 필수 5항목(TEAM/INNING/COUNT/
    # OUT/BASE) 중 detect=1 인 개수(0~5). ETC 는 안 센다.
    # ⚠ 쿼리에서 5 를 상수로 박지 말 것 — 워커의 필수 항목이 늘면 조용히 틀린다.
    detect_major_obj: int = NOT_RUN

    # 중첩 객체는 대문자 — 응답 키가 그대로 대문자다 (워커가 dataclass 필드명으로 직렬화).
    CLS: Cls = Cls()
    BOARD_DETECT: BoardDetect = BoardDetect()
    BOARD_DETAIL_DETECT: BoardDetailDetect = BoardDetailDetect()


class Video(BaseModel):
    """영상 하나의 결과 전부. FRAME 길이 = 보낸 프레임 수."""
    v_id: int = NOT_RUN
    FRAME: list[Frame] = []
    BOARD_DETECT_ADJUST: BoardDetectAdjust = BoardDetectAdjust()


# ⚠ 별칭이 필요한 이유 — Response 의 필드명이 응답 키와 같은 'Video' 라, 클래스 본문에서
#   `Video: Video | None = None` 이라고 쓰면 값 대입(None)이 먼저 일어나 같은 이름의 클래스가
#   가려진다 (TypeError: unsupported operand |). 필드명은 응답 키라 못 바꾸므로 타입 쪽을
#   별칭으로 가리킨다. from __future__ import annotations 로는 안 풀린다 —
#   pydantic 이 클래스 네임스페이스를 localns 로 넘겨서 거기서도 None 이 먼저 잡힌다.
VideoResult = Video


class Response(BaseModel):
    """응답 껍데기. 본체는 Video 하나. 실패면 Video 는 None."""
    Result: int
    Reason: str = ""
    Video: VideoResult | None = None


def detect(http: httpx.Client, v_id: int, img_path: str) -> Response:
    """야구 프레임 추론 — POST /sport/baseball → Response.

    img_path : 워커 IMG_PATH 기준 상대 경로 (그 디렉터리의 jpg 전부).

    Result != 0 은 예외로 올리지 않는다 — 이미지 갈래는 옵션이라 호출부가 번호를 보고
    '이 영상은 이미지 결과 없음'으로 넘어갈 수 있어야 한다. 연결 실패·5xx 만 예외.
    블로킹 호출이므로 호출부가 to_thread 로 넘긴다.
    """
    body = Request(v_id=v_id, img_path=img_path)
    data = img_detect.post(http, SPORT, body.model_dump())
    res = Response(**data)

    if res.Result != img_detect.OK:
        log.warning(f"baseball detect 거절: v_id={v_id} path={img_path!r} "
                    f"Result={res.Result} ({res.Reason})")
        return res

    n = len(res.Video.FRAME) if res.Video else 0
    log.info(f"baseball detect 완료: v_id={v_id} path={img_path!r} → {n}프레임")
    return res
