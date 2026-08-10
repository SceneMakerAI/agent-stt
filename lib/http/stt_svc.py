"""stt_svc 핸들러 — 1차 공정(prep → STT → 교정 → 저장) 접수. 받는 URL 1개.

여기는 전송 계층 — 상태 '접수'(1001) 갱신과 즉시 응답만 하고, 공정은 svc 에 넘긴다:
  lib/svc/pipeline.run  (프로파일 해석 → 음성/이미지 병렬 → 저장 → 상태, 카운터 반납까지 책임)
상태 흐름: 1001(접수) → 1005(처리중) → 1006(완료) / 실패 시 -1.
"""
from fastapi import APIRouter, BackgroundTasks, Request
from pydantic import BaseModel

import config
from lib.client.rdb import t_video
from lib.http import http_util
from lib.log import get_logger
from lib.svc import pipeline

router = APIRouter(prefix="/api/v1", tags=["stt_svc"])
log = get_logger(__name__)

ACCEPTED = 1001   # t_video.status_code — 접수 시 표시 (이후 상태는 svc/pipeline 이 관리)


# ── 요청/응답 메시지 쌍 (POST /stt_svc)
class SttRequest(BaseModel):
    v_id: int              # 영상 id — t_video FK 겸 output/{v_id}/ 디렉토리
    file_path: str         # 이 공정의 입력 파일. ffmpeg 켜짐=원본 영상(prep_svc 입력),
                           #   꺼짐=이미 뽑힌 오디오(STT 입력). 어느 쪽인지는 프로파일이 정한다
    title: str             # 제목 — 명단 검색(search_web) 입력
    category: str          # 카테고리 — 명단 검색·교정 분기 키
    year: int              # 방송연도 — 명단 검색 정확도(로스터·동명이 구분)


class SttResponse(BaseModel):
    v_id: int
    status: str        # "accepted" | "Not found v_id" | "busy, retry later"


@router.post("/stt_svc", response_model=SttResponse)
async def stt_svc(req: SttRequest, bg: BackgroundTasks, request: Request):
    log.info(f"stt_svc 접수: v_id={req.v_id} file_path={req.file_path} "
             f"title={req.title!r} category={req.category!r} year={req.year}")
    state = request.app.state

    # 백프레셔 — 대기열이 꽉 차면 받지 않고 거절 (set_status 전에 체크).
    #   단일 루프라 'check → +=1' 사이에 await 가 없어 race 없음 (lock 불필요).
    if state.current_req_cnt >= config.MAX_REQ_CNT:
        log.warning(f"대기열 초과 ({state.current_req_cnt}/{config.MAX_REQ_CNT}) → 429: v_id={req.v_id}")
        return http_util.busy_response(SttResponse(v_id=req.v_id, status="busy, retry later"))

    # 1-1. 상태 '접수'(1001) 갱신 — 빠른 UPDATE 라 직접 호출. 결과(행 수)로 검증.
    rows = t_video.set_status(req.v_id, ACCEPTED)
    if rows != 1:                                  # 1행이어야 정상. 0 → t_video 에 없는 v_id
        return SttResponse(v_id=req.v_id, status="Not found v_id")   # 200 + 본문으로 결과 전달

    state.current_req_cnt += 1                 # 접수 카운트 — 반납은 pipeline.run 의 finally
    bg.add_task(pipeline.run, state, req)      # 요청 객체 그대로 넘김 (pipeline 이 속성만 읽음)
    return SttResponse(v_id=req.v_id, status="accepted")
