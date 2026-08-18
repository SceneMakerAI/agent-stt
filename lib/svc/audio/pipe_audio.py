"""음성 갈래 — 영상 1건의 오디오 공정. 스텝 순서와 스텝별 실패 정책만 안다.

  (검색) → stt → (whisper) → 교정 → 할루시 → (요약)

ffmpeg 는 여기 없다 — 이미지 갈래와 공통 선행 작업이라 pipeline 이 먼저 돌리고
그 결과(audio_path)를 넘겨준다. 이 갈래는 들을 파일이 이미 있다고 본다.

괄호는 카테고리에 따라 꺼질 수 있는 스텝이다. **순서는 어느 카테고리든 같다** —
카테고리가 바꾸는 건 '무엇을 켜고 무슨 재료를 주느냐'뿐이라, 파이프라인은 이 파일 하나다.
(스포츠는 요약 off, 다큐·뉴스는 검색·whisper off — 표는 profile 이 갖는다)

이 파일은 **카테고리 문자열을 보지 않는다.** prof(Audio) 가 이미 해석된 결과다.

순서는 데이터 의존이라 바꿀 수 없다:
  검색 → whisper : 명단에서 뽑은 이름이 whisper initial_prompt 로 들어간다(이름 정확도↑)
  whisper → 교정 : 2차 전사가 교정의 [B] 대조본이 된다
  할루시 → 요약  : 요약은 걸러낸 대사(kept)만 본다

검색만 '띄우고 나중에 합류'한다 — 제목·연도만 있으면 되니 STT(2~10분) 뒤에 숨긴다.
합류 지점은 whisper 직전(명단이 프롬프트 재료라 그 전에 있어야 한다).

스텝 하나의 실패를 어떻게 볼지는 스텝 성질이지 카테고리가 아니다:
  검색·whisper 실패 → 삼킨다 (없으면 없는 대로 교정)
  나머지 실패      → 올린다 (호출측이 갈래 실패로 처리)
"""
import asyncio

from lib import def_code
from lib.client.rdb import t_video
from lib.log import get_logger
from lib.svc import debug
from lib.svc.audio.correct import glossary_correct, pipe_correct
from lib.svc.audio.hallu import pipe_hallu
from lib.svc.audio.schema_audio import Audio, AudioOut
from lib.svc.audio.search import pipe_search
from lib.svc.audio.stt_qwen import pipe_stt_qwen
from lib.svc.audio.stt_whisper import pipe_stt_whisper
from lib.svc.audio.summary import pipe_summary

log = get_logger(__name__)


async def _mark(v_id: int, code: int) -> None:
    await asyncio.to_thread(t_video.set_status, v_id, code)


async def run(state, req, prof: Audio, audio_path: str) -> AudioOut:
    """음성 갈래 전체. 실패하면 stage 를 로그에 남기고 예외를 그대로 올린다.

    audio_path : pipeline 이 준비해 넘긴 들을 파일. ffmpeg 산출물이거나, ffmpeg 를
                 껐다면 요청이 준 file_path 그대로다.
    """
    v_id = req.v_id
    out = AudioOut()
    stage, code = "1_search", def_code.CODE_SEARCH
    search_task = None

    try:
        # ① 검색 — 여기서 '띄우기만' 한다. 합류는 whisper 직전(③).
        #    제목이 없으면 검색할 게 없다.
        if prof.search and req.title:
            await _mark(v_id, code)
            search_task = asyncio.create_task(
                pipe_search.run(state.vllm, req.title, req.year, req.category))

        # ② STT 1차 — 전사 + 정규화·검증(pipe_stt_qwen)
        stage, code = "2_stt", def_code.CODE_QWEN
        if prof.stt_qwen:
            await _mark(v_id, code)
            out.dialogue = await pipe_stt_qwen.run(state.http, v_id, audio_path)
        debug.dump(v_id, stage, out.dialogue)

        # ③ 검색 합류 — STT 도는 동안 이미 끝나 있다(검색 20초 vs STT 2분+ → 대기 0).
        #    실패/빈 결과면 명단 없이 진행 (whisper 프롬프트도 자동으로 빔)
        if search_task:
            stage = "3_roster"
            try:
                roster = await search_task
                out.search_result = roster.Text
                out.search_query = pipe_search.format_query(roster)
                debug.dump(v_id, stage, pipe_search.format_dump(roster))
                log.info(f"[audio] v_id={v_id} 명단 확보: {len(out.search_result)}자")
            except Exception:  # noqa: BLE001 — 명단 없이도 교정은 돈다
                log.exception(f"[audio] v_id={v_id} 명단 검색 실패 — 명단 없이 진행")

        # ④ whisper 2차 — 교정 때 대조할 '두 번째 의견'.
        #    명단의 등장인물을 initial_prompt 로 넘겨 이름 정확도를 올린다.
        if prof.stt_whisper:
            stage, code = "4_whisper", def_code.CODE_WHISPER
            await _mark(v_id, code)
            try:
                out.whisper = await pipe_stt_whisper.run(
                    state.http, v_id, out.dialogue, out.search_result)
                debug.dump(v_id, stage, out.whisper)
                log.info(f"[audio] v_id={v_id} whisper 2차: {len(out.whisper.items)}건")
            except Exception:  # noqa: BLE001 — 2차 없으면 1차만으로 교정
                log.exception(f"[audio] v_id={v_id} whisper 2차 실패 — 1차만으로 교정")

        # ⑤ 교정 — 1차를 기준으로 whisper 2차·명단·용어집을 참고자료로 대조 교정.
        #    교정은 idx 로 2차를 찾으므로 여기서 조회표로 바꿔 넘긴다.
        stage = "5_correct"
        code = def_code.CODE_GLOSSARY if prof.correct_glossary else def_code.CODE_CORRECT
        corrected = out.dialogue
        if prof.correct:
            await _mark(v_id, code)
            corrected = await pipe_correct.run(
                state.vllm, out.dialogue, out.search_result, req, out.whisper,
                glossary=glossary_correct.by_category(req.category) if prof.correct_glossary else "")
            debug.dump(v_id, stage, corrected)

        # ⑥ 할루시 필터 — 언어이탈 후보 판정 → drop/relang + 재번호
        stage, code = "6_hallu", def_code.CODE_HALLU
        out.dialogue_clean = corrected
        if prof.hallu:
            await _mark(v_id, code)
            out.dialogue_clean = await pipe_hallu.run(state.vllm, corrected)
            debug.dump(v_id, stage, out.dialogue_clean)
            log.info(f"[audio] v_id={v_id} 할루시필터: "
                     f"{len(corrected.items)}→{len(out.dialogue_clean.items)}줄")

        # ⑦ 요약 — 구간 + 전체. 깨끗한 대사 입력.
        if prof.summary:
            stage, code = "7_summary", def_code.CODE_SUMMARY
            await _mark(v_id, code)
            out.summary = await pipe_summary.run(state.vllm, out.dialogue_clean, req)
            debug.dump(v_id, stage, out.summary)
            log.info(f"[audio] v_id={v_id} 요약: 구간 {len(out.summary.sections)}개")

        log.info(f"[audio] v_id={v_id} 완료: {len(out.dialogue_clean.items)} dialogues")
        return out

    except Exception as e:
        e.status_code = def_code.error_code(code, e)
        log.exception(f"[audio] v_id={v_id} 실패 (stage={stage}, code={e.status_code})")
        raise
    finally:
        # 앞 스텝이 먼저 터져 합류(await)를 못 했으면 떠 있는 task 정리
        if search_task and not search_task.done():
            search_task.cancel()
