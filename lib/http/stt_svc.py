"""stt_svc 핸들러 (HTTP 라우터) + 요청 DTO. 받는 URL 1개.

요청 받고 → DB 상태 '처리중'(1005) 갱신 → 결과 확인 후 바로 응답.
나머지 공정(prep_svc → stt → 교정 → DB 저장)은 응답 후 내부(백그라운드)에서 처리.
"""
import asyncio

from fastapi import APIRouter, BackgroundTasks, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

import config
from lib import debug
from lib.client import db, prep_stt, vision
from lib.correct import corrector
from lib.log import get_logger

router = APIRouter(prefix="/api/v1", tags=["stt_svc"])
log = get_logger(__name__)


class SttRequest(BaseModel):
    v_id: int          # 영상 id — t_video FK 겸 output/{v_id}/ 디렉토리
    file_path: str     # 원본 파일 경로/키 (prep_svc 입력)


@router.post("/stt_svc")
async def stt_svc(req: SttRequest, bg: BackgroundTasks, request: Request):
    log.info(f"stt_svc 접수: v_id={req.v_id} file_path={req.file_path}")
    state = request.app.state

    # 백프레셔 — 대기열이 꽉 차면 받지 않고 거절 (set_status 전에 체크).
    #   단일 루프라 'check → +=1' 사이에 await 가 없어 race 없음 (lock 불필요).
    if state.current_req_cnt >= config.MAX_REQ_CNT:
        log.warning(f"대기열 초과 ({state.current_req_cnt}/{config.MAX_REQ_CNT}) → 429: v_id={req.v_id}")
        return JSONResponse(
            status_code=429,
            content={"v_id": req.v_id, "status": "busy, retry later"},
            headers={"Retry-After": "60"},
        )

    # 1-1. 상태 '처리중'(1005) 갱신 — 빠른 UPDATE 라 직접 호출. 결과(행 수)로 검증.
    rows = db.set_status(req.v_id, 1005)
    if rows != 1:                                  # 1행이어야 정상. 0 → t_video 에 없는 v_id
        return {"v_id": req.v_id, "status": "Not found v_id"}   # 200 + 본문으로 결과 전달

    # 나머지(prep_svc → stt → 교정 → DB 저장)는 응답 후 백그라운드에서 처리.
    # 공유 클라이언트(vllm/http)가 필요하므로 app.state 를 같이 넘긴다.
    state.current_req_cnt += 1                             # 접수 카운트 (process finally 에서 반납)
    bg.add_task(process, state, req.v_id, req.file_path)
    return {"v_id": req.v_id, "status": "accepted"}


async def process(state, v_id: int, file_path: str) -> None:
    """응답 후 백그라운드 공정 (②~⑦). 단일 오케스트레이터 — 단계는 각 모듈이 구현.

    prep/stt/DB/vision 은 블로킹 sync → asyncio.to_thread, 교정만 async → 직접 await.
    stage 로 어느 단계에서 실패했는지 로그에 남긴다.
    """
    stage = "prep"
    try:
        # prep+stt 는 같은 서버(GPU 1개) — 서비스 개수를 제한
        async with state.stt_sem:
            # FFMPEG
            audio_path = await asyncio.to_thread(prep_stt.prep, state.http, v_id, file_path)

            stage = "stt"
            segments = await asyncio.to_thread(prep_stt.stt, state.http, v_id, audio_path)

        debug.dump(v_id, "stt", segments)

        stage = "correct"
        corrected = await corrector.correct(state.vllm, segments)

        stage = "save"
        await asyncio.to_thread(db.save_result, v_id, corrected, 1006)
        log.info(f"[bg] v_id={v_id} 완료: {len(corrected)} dialogues")

        # ⑦ 다음 단계 트리거 — agent-vision 분석 요청
        stage = "vision"
        await asyncio.to_thread(vision.agent_vision, state.http, v_id, False)
        
    except Exception:  # noqa: BLE001 — 백그라운드라 응답으로 못 알림, 로그로 남김
        log.exception(f"[bg] v_id={v_id} 실패 (stage={stage})")
    finally:
        state.current_req_cnt -= 1                         # 성공/실패 무관 접수 슬롯 반납
