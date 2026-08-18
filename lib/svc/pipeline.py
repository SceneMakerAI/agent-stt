"""공정 오케스트레이터 — 요청 1건의 생애를 관리한다. 순서와 실패 정책만 안다.

  profile.resolve → ffmpeg → 음성/이미지 갈래 병렬 → 둘 다 끝나면 저장 → 상태 → 다음 단계 트리거

카테고리를 해석하는 건 profile 하나뿐이고, 여기는 그 결과(prof)만 보고 갈래를 띄운다.
갈래 안에서 무슨 스텝이 도는지는 pipe_audio / pipe_image 가 안다.

**ffmpeg 는 갈래가 아니라 둘의 공통 선행 작업이라 여기서 먼저, 혼자 돈다.**
음성(audio.wav)과 프레임(frames/)을 둘 다 ffmpeg 가 만들기 때문이다. 갈래 안에
넣으면 아직 프레임이 없는 채로 검출 워커를 불러 거절당한다.

실패 정책 — 음성·이미지 둘 다 중요하다:
  어느 쪽이 실패하든 → 나머지 갈래를 취소하고 이 영상 실패 (status=-1, 저장 자체를 안 함).
    반쪽만 저장하면 그 영상이 '완료'인지 아닌지 알 수 없게 된다.

상태 코드는 여기서만 찍는다 — '완료'의 기준이 하나여야 다운스트림이 반쯤 처리된 영상을
완료로 보지 않는다. 접수 카운터 반납(finally)도 여기 책임이다 (핸들러는 +1 만 한다).
"""
import asyncio

import config
from lib import def_code
from lib.client import vision
from lib.client.rdb import t_video
from lib.log import get_logger
from lib.svc import profile
from lib.svc.audio import pipe_audio
from lib.svc.ffmpeg import pipe_ffmpeg
from lib.svc.image import pipe_image
from lib.svc.rdb import save_svc

log = get_logger(__name__)


async def _mark(v_id: int, code: int) -> None:
    await asyncio.to_thread(t_video.set_status, v_id, code)


async def run(state, req) -> None:
    """백그라운드 공정 전체. 예외를 밖으로 내지 않는다 — 이미 응답을 보낸 뒤라
    알릴 곳이 없다. 실패는 로그와 status_code(-1)로만 보고한다."""
    v_id = req.v_id
    prof = profile.resolve(req.category)
    log.info(f"[pipe] v_id={v_id} category={req.category!r} → "
             f"image={prof.image or '없음'}")

    stage = def_code.CODE_FFMPEG   # 실패 코드 계산용. None 이면 저장 구간
    try:
        # ① 준비 — 원본에서 음성과 프레임을 뽑는다. 두 갈래의 재료를 모두 여기서 만드므로
        #    **끝날 때까지 기다린 뒤** 갈래를 띄운다. 끄면 요청이 준 file_path 를 그대로
        #    쓴다 (람다 등 바깥에서 이미 준비해 둔 경우 — 프레임도 이미 있다고 본다).
        audio_path = req.file_path
        if prof.ffmpeg:
            await _mark(v_id, def_code.CODE_FFMPEG)
            audio_path = await pipe_ffmpeg.run(state.http, v_id, req.file_path)

        # ② fan-out — 두 갈래는 워커 GPU 가 달라 실제로 병렬로 돈다.
        #   프로파일에 종목이 없으면(드라마·다큐) 이미지 task 자체를 안 만든다.
        audio_task = asyncio.create_task(pipe_audio.run(state, req, prof.audio, audio_path))
        image_task = (asyncio.create_task(pipe_image.run(state, v_id, prof.image))
                      if prof.image else None)

        # join — 둘 다 중요하다. 어느 쪽이 먼저 실패하든 나머지를 접고 전체 실패로 간다
        #   (반쪽만 저장하면 그 영상이 '완료'인지 아닌지 알 수 없게 된다).
        tasks = [t for t in (audio_task, image_task) if t]
        done, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_EXCEPTION)

        # 남은 갈래 접기 — ⚠ 취소해도 워커 추론과 스레드는 안 멈춘다(요청이 이미 나갔고
        #   스레드는 못 죽인다). 여기서 얻는 건 '4분짜리 추론을 끝까지 기다리지 않는 것'뿐이다.
        #   gather 한 줄은 CancelledError 를 흡수해 'never retrieved' 경고를 막는다.
        for t in pending:
            t.cancel()
        if pending:
            await asyncio.gather(*pending, return_exceptions=True)

        # 하나라도 실패했으면 그대로 올린다. 음성 갈래는 자기가 어느 스텝이었는지 예외에
        #   붙여 보내므로, 여기서는 이미지 갈래만 코드를 매긴다.
        for t in done:
            exc = t.exception()
            if exc:
                if t is image_task:
                    exc.status_code = def_code.error_code(def_code.CODE_ERROR_IMAGE, exc)
                raise exc

        audio_out = audio_task.result()
        image_out = image_task.result() if image_task else None

        stage = None
        await asyncio.to_thread(save_svc.save, v_id, audio_out, image_out, def_code.CODE_OK)
        log.info(f"[pipe] v_id={v_id} 완료")

        # 다음 단계 트리거 — .env 의 VISION_TRIGGER 가 on 일 때만 (미연동이면 off).
        if config.VISION_TRIGGER:
            try:
                await asyncio.to_thread(vision.agent_vision, state.http, v_id, True)
            except Exception:  # noqa: BLE001 — 트리거 실패는 로그만
                log.exception(f"[pipe] v_id={v_id} vision 트리거 실패 — 결과는 저장됨")

    except Exception as e:  # noqa: BLE001 — 백그라운드라 응답으로 못 알린다
        code = getattr(e, "status_code", None) or (
            def_code.CODE_ERROR_DB if stage is None else def_code.error_code(stage, e))
        log.exception(f"[pipe] v_id={v_id} 실패 (code={code})")
        try:
            await _mark(v_id, code)
        except Exception:  # noqa: BLE001 — DB 장애 자체가 원인일 수 있다
            log.exception(f"[pipe] v_id={v_id} 실패 상태({code}) 기록도 실패")
    finally:
        state.current_req_cnt -= 1               # 성공·실패 무관 접수 슬롯 반납
