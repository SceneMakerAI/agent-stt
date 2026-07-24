"""stt 공정 오케스트레이터 — 순서와 실패 정책만 안다. 로직은 부품이 구현:
    prep_stt   ②③ prep(ffmpeg) + STT 호출
    corrector  ④ 교정 (vLLM 페이지 병렬)
    rdb        ⑤ 저장 + 상태 갱신
    vision     ⑦ 다음 단계 트리거 (agent-vision)

stt_svc(http 핸들러)는 run() 하나만 백그라운드로 띄운다. 접수 카운터 반납까지
여기 책임 (핸들러는 +1 만 하고 끝).
"""
import asyncio

import config
from lib import debug
from lib.client import vision
from lib.client.prep_stt import ffmpeg, stt, stt2
from lib.client.rdb import db_svc, t_video
from lib.log import get_logger
from lib.svc.stt.correct import corrector
from lib.svc.stt.hallucination import filter as hallu
from lib.svc.stt.search import web_search
from lib.svc.stt.stt_schema import SttInfo
from lib.svc.stt.summary import summarizer

log = get_logger(__name__)

STT_START, STT_END, STT_ERROR = 1005, 1006, -1   # t_video.status_code


# 보강(enrichment) 대상 카테고리 — 명단 검색 + whisper 2차 전사를 여기서만 돈다.
#   이 튜플 하나가 "어떤 영상을 보강할지"의 단일 기준. 카테고리 추가는 여기 한 줄.
#   (뉴스·다큐는 1차 STT 가 이미 정확 → 보강 이득 없이 환각 위험만. 스킵)
ENRICH_CATEGORIES = ("스포츠", "드라마")   # 사극은 "드라마-사극" 이라 startswith 로 포함


def _needs_enrichment(category: str) -> bool:
    """명단 검색·whisper 2차 대상 여부. roster 와 whisper 가 같은 이 판정을 공유한다
    (한쪽만 도는 불일치를 구조적으로 차단)."""
    return category.startswith(ENRICH_CATEGORIES)


async def run(state, req) -> None:
    """백그라운드 공정 (②~⑦). 단일 오케스트레이터 — 단계는 각 모듈이 구현.

    요청(SttRequest)을 SttInfo 로 옮겨(입력만) 단계마다 산출물을 채운다. 저장(db_svc)엔
    이 info 하나만 넘긴다. file_path 는 prep 전용이라 info 에 안 담고 req 로 바로 쓴다.
    prep/stt/DB/vision 은 블로킹 sync → asyncio.to_thread, 교정만 async → 직접 await.
    stage 로 어느 단계에서 실패했는지 로그에 남긴다.
    """
    v_id = req.v_id
    info = SttInfo(v_id=v_id, title=req.title, category=req.category, year=req.year)
    stage = "0_prep"

    # WEB 검색 — STT 와 독립(제목/카테고리/연도만 필요)이라 '먼저' 띄워 prep+STT 시간에 숨긴다.
    #   보강 대상(스포츠·드라마)이고 제목이 있을 때만. STT(5~10분) 도는 동안 백그라운드로 진행.
    
    if _needs_enrichment(req.category) and req.title:
        search_task = asyncio.create_task(
            web_search.search_web(state.vllm, req.title, req.year, req.category))
    else:
        search_task = None    

    try:
        async with state.stt_sem:
            # FFMPEG — 영상-음성 분리 (덤프할 결과 없음)
            prep_res = await asyncio.to_thread(ffmpeg.prep, state.http, v_id, req.file_path)

            # STT
            stage = "1_stt"
            await asyncio.to_thread(t_video.set_status, v_id, STT_START)
            info.dialogue = await asyncio.to_thread(stt.stt, state.http, v_id, prep_res.audio_path)

        debug.dump(v_id, stage, info.dialogue)

        # 명단 합류 — STT 도는 동안 이미 진행됨(검색 20초 vs STT 2분+ → 대기 0).
        #   whisper 보다 '먼저' 받아야 한다 — 등장인물 이름을 whisper 프롬프트로 넘기기 때문.
        #   비대상/실패/빈 결과면 명단 없이 진행 (whisper 프롬프트도 자동으로 빔)
        stage = "2_roster"
        if search_task:
            try:
                res = await search_task
                info.search_result = res["roster"]           # → t_video.search_result
                info.search_query = web_search.format_query(res)  # → t_video.search_query
                debug.dump(v_id, stage, web_search.format_dump(res))
                log.info(f"[bg] v_id={v_id} 명단 확보: {len(info.search_result)}자")
            except Exception:  # noqa: BLE001 — 명단 검색 실패는 스킵, 교정은 명단 없이
                log.exception(f"[bg] v_id={v_id} 명단 검색 실패 — 명단 없이 진행")

        # whisper 2차 전사 — 교정 때 대조할 '두 번째 의견'. roster 와 같은 대상(_needs_enrichment)만.
        #   명단에서 뽑은 등장인물을 initial_prompt 로 넘겨 이름 정확도를 올린다(stt2._prompt).
        #   실패해도 교정은 1차만으로 진행 (whisper 없으면 기존과 동일 동작)
        stage = "3_whisper"
        info.whisper_map = {}
        if _needs_enrichment(req.category):
            try:
                info.whisper_map = await asyncio.to_thread(
                    stt2.stt2, state.http, v_id, info.dialogue, info.search_result)
                debug.dump(v_id, stage, info.whisper_map)
                log.info(f"[bg] v_id={v_id} whisper 2차: {len(info.whisper_map)}건")
            except Exception:  # noqa: BLE001 — 2차 전사 실패는 스킵, 교정은 1차만으로
                log.exception(f"[bg] v_id={v_id} whisper 2차 실패 — 1차만으로 교정")

        # 교정 (refine) — 1차 텍스트를 기준으로, whisper 2차와 명단을 참고자료로 대조 교정.
        #   whisper_map 이 비어 있으면(비대상/실패) 기존과 동일하게 1차만 교정한다.
        stage = "4_correct"
        corrected = await corrector.correct(
            state.vllm, info.dialogue, info.search_result, req, info.whisper_map)
        debug.dump(v_id, stage, corrected)

        # 할루시 필터 — 언어이탈 후보 LLM 판정 → drop/relang + reindex. kept 가 이후 입력.
        stage = "5_hallu"
        filtered = await hallu.run(state.vllm, corrected)
        info.kept = filtered["kept"]
        debug.dump(v_id, stage, filtered)
        log.info(f"[bg] v_id={v_id} 할루시필터: {len(corrected)}→{len(info.kept)}줄 "
                 f"(drop {len(filtered['dropped'])})")

        # 요약 — 구간(1분, 직전N개 문맥) + 전체. kept(깨끗한 대사) 입력.
        stage = "6_summary"
        summary = await summarizer.summarize(state.vllm, info.kept, req)
        info.summary_stt = summary["overall"]        # → t_video.summary_stt
        info.segments = summary["segments"]          # → t_dialogue_summary
        debug.dump(v_id, stage, summary)
        log.info(f"[bg] v_id={v_id} 요약: 구간 {len(info.segments)}개")

        # 저장 — 대사·구간요약·t_video(요약/검색) + status(1006) 을 한 트랜잭션으로 (db_svc)
        stage = "7_save"
        await asyncio.to_thread(db_svc.save_result, info, STT_END)
        log.info(f"[bg] v_id={v_id} 완료: {len(info.kept)} dialogues")

        # ⑦ 다음 단계 트리거 — agent-vision 분석 요청.
        #   config.VISION_TRIGGER(.env) 가 on 일 때만. off 면 STT 만 하고 끝(vision 미연동 등).
        if config.VISION_TRIGGER:
            stage = "vision"
            await asyncio.to_thread(vision.agent_vision, state.http, v_id, True)
            log.info(f"[bg] v_id={v_id} vision 트리거 완료")

    except Exception:  # noqa: BLE001 — 백그라운드라 응답으로 못 알림, 로그 + DB 상태로 보고
        log.exception(f"[bg] v_id={v_id} 실패 (stage={stage})")
        try:
            await asyncio.to_thread(t_video.set_status, v_id, STT_ERROR)
        except Exception:  # noqa: BLE001 — DB 장애 자체가 원인일 수 있음, 로그만 남김
            log.exception(f"[bg] v_id={v_id} 실패 상태(-1) 기록도 실패")
    finally:
        # prep/STT 가 먼저 실패해 명단검색을 합류(await)하지 못했으면 떠 있는 task 정리
        if search_task and not search_task.done():
            search_task.cancel()
        state.current_req_cnt -= 1                         # 성공/실패 무관 접수 슬롯 반납
