"""할루시네이션 판정 프롬프트 (2단 LLM) — 언어이탈 후보 + 문맥 → 3분류 JSON.

filter.py 가 '주언어와 다른 줄'을 후보로 뽑아, 각 후보를 **앞뒤 문맥과 함께** 여기로 보낸다.
LLM 은 후보마다 keep / drop / relang 중 하나로 판정한다.

원칙: **drop 은 아주 좁게.** 명백한 잡음 할루시만. 애매하면 keep (t_dialogue 삭제는 되돌릴 수 없음).
"""
import json

from lib.client.vllm import VLLMClient
from lib.log import get_logger

log = get_logger(__name__)

SYSTEM = """너는 STT(음성인식) 자막에서 '잡음 할루시'만 골라내는 판정기다.
주 언어({main})가 아닌 줄들이 후보로 들어온다. 각 후보를 **앞뒤 문맥과 함께** 보고 판정하라.

[문맥으로 판단하는 법 — 핵심]
- 각 후보에는 앞뒤 줄이 같이 주어진다. **후보의 내용이 앞뒤 줄의 주제·흐름과 이어지는지**를 먼저 본다.
  * 앞뒤 대화/나레이션과 **주제가 이어지면** → 실제 발화 (keep). 외국어여도 인터뷰·나레이션의 일부일 수 있다.
  * 앞뒤와 **완전히 동떨어진 뜬금없는 내용**이면 → 할루시 의심 (drop 후보).
- 즉 "외국어라서" 지우는 게 아니라, "**문맥에서 튀어서**" 지운다. 판단 근거는 언어가 아니라 문맥이다.

[판정 (하나만)]
- keep   : 실제 발화. 앞뒤 문맥과 이어지는 외국어 인터뷰·나레이션·가사·광고 등.
- drop   : 잡음 할루시. 무의미한 음절 반복, 소음(새소리·음악)을 억지로 글자화한 것,
           **앞뒤 문맥과 완전히 동떨어진** 헛소리.
- relang : 내용은 사실 주 언어({main})인데 언어 태그만 틀렸다. (예: 한국어인데 lang=Chinese).
           지우지 말고 태그만 고칠 대상.

[지킬 것]
- **애매하면 keep.** 삭제는 되돌릴 수 없다. 문맥과 이어지거나 뜻이 통하면 외국어여도 keep.
- drop 은 '문맥에서 명백히 튀는' 것만. 짧아도(예: "Va bene?") 앞뒤와 이어지면 keep.
- relang 은 글자가 주 언어({main})로 쓰여 있는데 lang 만 다른 경우.

[출력] 오직 JSON: {{"results": [{{"idx": <정수>, "verdict": "keep|drop|relang"}}, ...]}}
후보로 준 idx 전부에 대해, 정확히 그 idx 들로만 판정을 낸다."""


def build(main: str, candidates: list[dict], id2seg: dict[int, dict], ctx: int = 2) -> list[dict]:
    """후보들 + 각 후보의 앞뒤 ctx 줄 문맥 → chat messages.

    main       : 주 언어
    candidates : 판정할 후보 (주언어 아닌 줄)
    id2seg     : idx → segment (문맥 줄을 끌어오기 위한 전체 인덱스)
    ctx        : 후보 앞뒤로 함께 보여줄 줄 수
    """
    blocks = []
    for c in candidates:
        i = c["idx"]
        lines = []
        for j in range(i - ctx, i + ctx + 1):
            s = id2seg.get(j)
            if not s:
                continue
            mark = " ← 후보" if j == i else ""
            lines.append(f'  [{j}] ({s.get("lang","")}) {s["text"]}{mark}')
        blocks.append("\n".join(lines))
    user = ("다음 후보들을 각각 앞뒤 문맥과 함께 보고 판정해 JSON 으로.\n\n"
            + "\n\n".join(blocks))
    return [
        {"role": "system", "content": SYSTEM.format(main=main)},
        {"role": "user", "content": user},
    ]


async def judge(vllm: VLLMClient, main: str, candidates: list[dict],
                id2seg: dict[int, dict]) -> dict[int, str]:
    """후보 → { idx: verdict }. 실패/누락 후보는 'keep'(보수적)으로 폴백."""
    verdicts = {c["idx"]: "keep" for c in candidates}   # 기본 keep
    if not candidates:
        return verdicts
    try:
        text, ms = await vllm.chat(
            messages=build(main, candidates, id2seg),
            temperature=0, max_tokens=4096,
            response_format={"type": "json_object"},
            extra_body={"chat_template_kwargs": {"enable_thinking": False}},
        )
        for r in json.loads(text)["results"]:
            idx, v = int(r["idx"]), str(r["verdict"])
            if idx in verdicts and v in ("keep", "drop", "relang"):
                verdicts[idx] = v
        log.info(f"hallu judge ({ms}ms): "
                 f"{sum(v=='drop' for v in verdicts.values())} drop / "
                 f"{sum(v=='relang' for v in verdicts.values())} relang / {len(verdicts)} 후보")
    except Exception as e:  # noqa: BLE001 — 판정 실패는 전부 keep (원문 보존)
        log.warning(f"hallu judge 실패 → 전부 keep: {e}")
    return verdicts
