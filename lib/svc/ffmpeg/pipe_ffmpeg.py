"""준비 스텝 (ffmpeg) — 원본 영상 → 음성 파일 경로.

이 디렉토리의 **진입점**이다. 바깥(pipeline)은 이 파일만 부른다.

  ffmpeg.prep (client, 블로킹) → 경로 확인 → audio_path

**음성 갈래의 스텝이 아니라 두 갈래의 공통 선행 작업이다.** 음성(audio.wav)뿐 아니라
이미지 갈래가 읽을 프레임(frames/)도 이 단계에서 나와야 한다 — 그래서 pipeline 이
이걸 먼저 끝내고 나서 갈래를 띄운다.

지금은 얇다 — 워커가 추출까지 다 하고 우리는 경로만 받는다. 그래도 스텝을 두는 이유는
파이프가 **모든 스텝을 svc 로만 부르게** 하기 위해서다. 여기가 없으면 pipeline 이
이 한 스텝만 client 를 직접 부르게 되고, 나중에 붙을 것들(추출 옵션 선택, 결과 검증,
람다 전환 시 호출 방식 분기)이 갈 곳이 없어진다.

⚠ prep 을 람다로 빼면 바뀌는 건 **이 아래 client 뿐**이다 — pipeline 은 그대로다.
"""
import asyncio

import httpx

from lib.client.prep_stt import ffmpeg
from lib.log import get_logger

log = get_logger(__name__)


async def run(http: httpx.Client, v_id: int, file_path: str) -> str:
    """원본 → 음성 파일 경로(audio_path). 추출은 블로킹(수분)이라 스레드로 넘긴다.

    워커가 status!=OK 를 주면 client 가 이미 예외를 던진다. 여기선 OK 인데 경로가
    비어 오는 경우를 잡는다 — 그대로 두면 STT 가 빈 경로로 돌다 엉뚱한 데서 터진다.

    상태 코드는 여기서 안 찍는다 — 스텝을 부르는 쪽(pipeline)이 찍는다.
    """
    res = await asyncio.to_thread(ffmpeg.prep, http, v_id, file_path)
    if not res.audio_path:
        raise RuntimeError(f"prep 성공인데 audio_path 가 비었다: v_id={v_id} {res}")

    log.info(f"ffmpeg v_id={v_id} → {res.audio_path}")
    return res.audio_path
