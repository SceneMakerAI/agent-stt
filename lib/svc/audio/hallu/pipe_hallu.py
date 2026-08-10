"""할루시네이션 필터 — 교정된 segments → 잡음성 할루시 줄 drop + idx 재정렬.

이 디렉토리의 **진입점**이다. 바깥(process)은 이 파일만 import 한다.

위치: 교정(correct) 다음, 저장(t_dialogue) 전. 걸러진 줄은 DB 에 안 들어간다.
      같은 출력이 summary 입력도 되므로 요약도 자동으로 깨끗해진다.

반복 루프는 worker(Qwen3-ASR, repetition_penalty)가 이미 억제하므로 여기선 안 다룬다.
여기가 잡는 건 '주언어와 다른 고립 줄'(새소리→외국어 같은 LID 할루시)뿐:

  1. 후보 추출(규칙): 주언어(최빈 lang)와 다른 줄만 골라냄 (LLM 부담↓)
  2. 판정(2단 LLM): 후보를 앞뒤 문맥과 함께 3분류
       keep   — 진짜 외국어 발화 (인터뷰·가사·광고)
       drop   — 잡음성 할루시 (무의미 음절 등)
       relang — LID 오분류 (실제론 주언어) → 지우지 말고 lang 만 교정
  3. renumber: drop 후 idx 0,1,2… 재매김 (구멍 메우기).

파일 셋으로 나뉜다 — 이 파일은 순서와 실패 정책만 안다:
  vllm_hallu.py   LLM 판정 (②) + 프롬프트
  util_hallu.py   규칙 판정 — 주언어 / 발화속도 / renumber
  pipe_hallu.py   여기

transport(vllm) 와 분리. process(run) 가 state.vllm 을 넘겨 호출.
"""
from dataclasses import replace

from lib.client.vllm import VLLMClient
from lib.log import get_logger
from lib.svc.audio.hallu import util_hallu, vllm_hallu
from lib.svc.audio.stt_qwen.schema_dialogue import Dialogues

log = get_logger(__name__)


async def run(vllm: VLLMClient, dialogues: Dialogues) -> Dialogues:
    """언어이탈 후보 → 2단 LLM 판정(keep/drop/relang) → drop 반영 + 재번호.

    반환은 남은 줄(kept)뿐이다. 버린 줄은 **로그에 한 줄씩** 남긴다 — 파일로 안 남기니
    무엇이 왜 빠졌는지는 로그가 유일한 근거다. drop 은 되돌릴 수 없어서 흔적이 필요하다.
    """
    items = dialogues.items
    main = util_hallu.main_lang(items)
    candidates = [s for s in items if s.lang and s.lang != main]

    # 2단: 후보를 앞뒤 문맥과 함께 LLM 판정 (id2seg 로 문맥 줄 조회)
    id2seg = {s.idx: s for s in items}
    verdicts = await vllm_hallu.judge(vllm, main, candidates, id2seg)

    survived, dropped, too_fast, relang = [], 0, 0, 0
    for s in items:
        # 발화속도 초과는 언어·LLM판정 무관하게 먼저 drop (배경음악·반복 환각)
        if util_hallu.too_fast(s):
            log.info(f"  drop[속도] idx={s.idx} {s.start_time} {s.text[:40]!r}")
            dropped += 1
            too_fast += 1
            continue
        v = verdicts.get(s.idx, "keep")
        if v == "drop":
            log.info(f"  drop[문맥] idx={s.idx} {s.start_time} ({s.lang}) {s.text[:40]!r}")
            dropped += 1
            continue
        if v == "relang":                 # LID 오분류 → 주언어로 태그 교정 (drop 아님)
            s = replace(s, lang=main)
            relang += 1
        survived.append(s)

    log.info(f"hallu filter: main={main!r} 후보={len(candidates)} "
             f"drop={dropped}(속도초과 {too_fast}) relang={relang} "
             f"kept={len(survived)}/{len(items)}")
    return replace(dialogues, items=util_hallu.renumber(survived))
