"""prep_stt 서버 호출 — ② prep_svc(ffmpeg)  ④ STT. (transport 계층)

같은 prep_stt 박스의 두 엔드포인트(url 만 다름)를 호출한다:
  POST /pre_svc/  {vid, file}      → { audio_path }   (영상→음성 추출 + 분할)
  POST /stt_svc/  {vid, file_path} → { segments }      (음성→자막)

설계 원칙:
  - httpx.Client(sync) 외부 주입 — 프로세스당 1개 공유. STT 는 한 번에 한 job 이라
    blocking(sync)으로 끝까지 기다린다. (교정 vLLM 만 async 병렬)
  - 단계 결과는 전부 "메모리"로 반환. 파일을 거치지 않는다 (파일 IO 금지).
"""
import httpx

import config
from lib.log import get_logger

log = get_logger(__name__)


def prep(http: httpx.Client, vid: int, file: str) -> str:
    """② prep_svc — POST /pre_svc/ {vid, file} 동기 호출 → audio_path 반환.

    영상 원본(file)을 받아 ffmpeg 로 음성 추출 + 분할. 결과의 audio_path 가 STT 입력.
    """
    r = http.post(
        f"{config.PREP_STT_BASE_URL}/pre_svc/",
        json={"vid": str(vid), "file": file},
        timeout=config.PREP_TIMEOUT_S,     # ffmpeg 가 client 기본 30s 보다 오래 걸림
    )
    r.raise_for_status()
    data = r.json()
    audio_path = data["audio_path"]
    log.info(f"prep ffmpeg done: job_id={data.get('job_id')} audio_path={audio_path}")
    return audio_path


def stt(http: httpx.Client, vid: int, file_path: str) -> list[dict]:
    """② STT — POST /stt_svc/ {vid, file_path} 동기 호출. 5~10분 블로킹 후 segments 반환.

    model_svc 가 파이프라인을 끝까지 돌려 결과를 바로 준다(폴링 없음). 그 한 요청만
    config.STT_TIMEOUT_S 를 줘서 기본 30s 타임아웃에 안 걸리게 한다.

    각 segment: { idx, start, end, text, lang, speaker }
    """
    r = http.post(
        f"{config.PREP_STT_BASE_URL}/stt_svc/",
        json={"vid": str(vid), "file_path": file_path},
        timeout=config.STT_TIMEOUT_S,
    )
    r.raise_for_status()
    data = r.json()
    if data.get("status") != "done":
        raise RuntimeError(f"stt {data.get('status')}: {data.get('error', '')}")
    segments = data.get("segments", [])
    log.info(f"stt done: job_id={data['job_id']} segments={len(segments)}")
    return segments
