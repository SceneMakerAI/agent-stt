"""할루시네이션 필터 — 교정된 segments → 잡음성 할루시 줄 drop + idx 재정렬.

위치: 교정(correct) 다음, 저장(t_dialogue) 전. 걸러진 줄은 DB 에 안 들어간다.
      같은 출력이 summary 입력도 되므로 요약도 자동으로 깨끗해진다.

반복 루프는 worker(Qwen3-ASR, repetition_penalty)가 이미 억제하므로 여기선 안 다룬다.
여기가 잡는 건 '주언어와 다른 고립 줄'(새소리→외국어 같은 LID 할루시)뿐:

  1. 후보 추출(규칙): 주언어(최빈 lang)와 다른 줄만 골라냄 (LLM 부담↓)
  2. 판정(2단 LLM, 미구현): 후보를 앞뒤 문맥과 함께 3분류
       keep   — 진짜 외국어 발화 (인터뷰·가사·광고)
       drop   — 잡음성 할루시 (무의미 음절 등)
       relang — LID 오분류 (실제론 주언어) → 지우지 말고 lang 만 교정
  3. reindex: drop 후 idx 0,1,2… 재매김 (원본은 orig_idx 로 보존, 검증용).

transport(vllm) 와 분리. process(run) 가 state.vllm 을 넘겨 호출.
"""
from collections import Counter

from lib.client.vllm import VLLMClient
from lib.log import get_logger
from lib.svc.stt.hallucination import prompt

log = get_logger(__name__)


def main_lang(segments: list[dict]) -> str:
    """최빈 lang 을 주언어로 (한국 방송이면 대개 'Korean')."""
    c = Counter(s.get("lang", "") for s in segments if s.get("lang"))
    return c.most_common(1)[0][0] if c else ""


def _reindex(segments: list[dict]) -> list[dict]:
    """idx 를 0,1,2… 재매김. 원본 idx 는 orig_idx 로 보존."""
    out = []
    for new_idx, s in enumerate(segments):
        r = dict(s)
        r["orig_idx"] = s["idx"]
        r["idx"] = new_idx
        out.append(r)
    return out


async def run(vllm: VLLMClient, segments: list[dict]) -> dict:
    """언어이탈 후보 → 2단 LLM 판정(keep/drop/relang) → drop 반영 + reindex.

    반환:
      main_lang  : 주언어
      verdicts   : { idx: keep|drop|relang } (검증용)
      dropped    : drop 된 줄 (원본 그대로)
      kept       : drop 제외 + relang 태그교정 + reindex 된 최종 segments
    """
    main = main_lang(segments)
    candidates = [s for s in segments if s.get("lang") and s["lang"] != main]

    # 2단: 후보를 앞뒤 문맥과 함께 LLM 판정 (id2seg 로 문맥 줄 조회)
    id2seg = {s["idx"]: s for s in segments}
    verdicts = await prompt.judge(vllm, main, candidates, id2seg)

    dropped, survived = [], []
    for s in segments:
        v = verdicts.get(s["idx"], "keep")
        if v == "drop":
            dropped.append(s)
            continue
        if v == "relang":                 # LID 오분류 → 주언어로 태그 교정 (drop 아님)
            s = {**s, "lang": main}
        survived.append(s)
    kept = _reindex(survived)

    log.info(f"hallu filter: main={main!r} 후보={len(candidates)} "
             f"drop={len(dropped)} kept={len(kept)}/{len(segments)}")
    return {"main_lang": main, "verdicts": verdicts, "dropped": dropped, "kept": kept}
