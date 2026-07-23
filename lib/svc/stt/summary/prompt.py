"""요약 프롬프트 — 2단계.

1단계 (구간 요약, segment):
  입력: 직전 구간요약(prev) + 이번 구간 대사
  출력: 이번 구간 요약 (2~4문장)
  → '전체 누적'이 아니라 '직전 요약'만 넘기므로 콜이 항상 가볍다(눈덩이 없음).

2단계 (전체 요약, overall):
  입력: 구간요약 전부
  출력: 영상 전체 줄거리 (마지막에 딱 1콜)

대사는 화자(S002 등)를 붙여 준다 — 나레이션/인터뷰/대화 구조를 살리기 위함
(이름은 아직 모르므로 화자 번호로만 구분).
"""
from lib.client.vllm import VLLMClient
from lib.log import get_logger

log = get_logger(__name__)

# ── 1단계: 구간 요약 (직전 요약 + 이번 대사 → 이번 구간 요약)
SEGMENT_SYSTEM = """너는 영상 대사를 구간별로 요약하는 도우미다. 대사는 STT(음성인식) 결과이고,
각 줄 앞의 S001·S002 는 화자(목소리) 번호다(이름은 모름).

[영상 정보]
{ctx}

[해야 할 일]
'직전 구간 요약들'(앞 흐름)과 '이번 구간 대사'를 받아, 이번 구간에서 무슨 일이 있었는지
요약한다. 직전 요약들은 앞 흐름을 이어가기 위한 참고일 뿐 — 요약 대상은 오직 '이번 구간 대사'다.

[분량 — 대사 양에 맞춘다 (억지로 늘리지 마라)]
- 대사가 충분하면 2~4문장.
- 대사가 적으면(한두 줄) 딱 1문장으로. 없는 내용을 지어내 늘리지 마라.
- **요약할 내용이 없으면(대사가 없거나 의미 없는 소리뿐) 빈 문자열("")을 반환한다.**
  "이야기가 시작된다" 같은 알맹이 없는 문장으로 채우지 마라.

[지킬 것]
- 대사에 실제로 있는 내용만. 지어내지 마라.
- **이번 구간 대사에 없는 내용(앞 요약에만 있는 것)을 이번 요약에 넣지 마라.** 앞 요약은
  문맥 참고용이지 요약 대상이 아니다.
- 화자 번호로 나레이션/인터뷰/대화 구조를 파악하되, 요약문에 'S002' 같은 번호는 쓰지 마라.
- 광고·잡음처럼 맥락에 안 맞는 줄은 요약에 넣지 마라.

[출력] 이번 구간 요약 텍스트만 (JSON·머리말 없이). 요약할 게 없으면 빈 문자열."""


def build_segment(ctx: str, prev_summaries: list[str], lines: str,
                  prev_raw: str = "") -> list[dict]:
    """앞 흐름 문맥은 '직전 요약들'이 원칙. 그게 아직 없을 때만(청크 병렬의 덩이 첫 구간)
    prev_raw(직전 구간들의 원본 대사)로 대신한다 — 둘 다 목적은 '앞에 무슨 일이 있었나'."""
    if prev_summaries or not prev_raw:
        head = "[직전 구간 요약들 (앞 흐름, 참고용)]"
        prev = "\n".join(f"- {s}" for s in prev_summaries if s) or "(없음 — 첫 구간)"
    else:
        head = "[직전 구간 대사 (앞 흐름, 참고용 — 요약 대상 아님)]"
        prev = prev_raw
    user = (f"{head}\n{prev}\n\n"
            f"[이번 구간 대사]\n{lines}\n\n이번 구간을 2~4문장으로 요약해.")
    return [
        {"role": "system", "content": SEGMENT_SYSTEM.format(ctx=ctx)},
        {"role": "user", "content": user},
    ]


async def segment(vllm: VLLMClient, ctx: str, prev_summaries: list[str], lines: str,
                  prev_raw: str = "") -> str:
    """한 구간 요약 → 요약 텍스트. prev_summaries=직전 N개(앞 흐름). 실패 시 빈 문자열.

    prev_raw : 직전 요약이 없을 때 쓰는 대체 문맥(직전 구간들의 원본 대사).
    """
    try:
        text, ms = await vllm.chat(
            messages=build_segment(ctx, prev_summaries, lines, prev_raw),
            temperature=0.2, max_tokens=512,
            extra_body={"chat_template_kwargs": {"enable_thinking": False}},
        )
        seg = text.strip()
        log.info(f"summary segment ({ms}ms): {len(seg)}자")
        return seg
    except Exception as e:  # noqa: BLE001 — 실패 구간은 스킵
        log.warning(f"summary segment 실패 → 스킵: {e}")
        return ""


# ── 2단계: 전체 요약 (구간요약 전부 → 전체 줄거리, 마지막 1콜)
OVERALL_SYSTEM = """너는 영상의 구간별 요약들을 하나의 전체 줄거리로 합치는 도우미다.

[영상 정보]
{ctx}

[해야 할 일]
시간 순서대로 나열된 구간 요약들을 받아, 영상 전체를 관통하는 줄거리를 만든다.

[지킬 것]
- 구간 요약에 있는 내용만. 지어내지 마라.
- 흐름이 자연스럽게 이어지게 하되, 같은 내용을 반복하지 마라.
- 전체 줄거리는 5~8문장으로 간결하게 (핵심 흐름 위주).

[출력] 전체 줄거리 텍스트만 (JSON·머리말 없이)."""


def build_overall(ctx: str, seg_summaries: list[str]) -> list[dict]:
    joined = "\n".join(f"{i+1}. {s}" for i, s in enumerate(seg_summaries) if s)
    return [
        {"role": "system", "content": OVERALL_SYSTEM.format(ctx=ctx)},
        {"role": "user", "content": f"[구간 요약들]\n{joined}\n\n전체 줄거리를 5~8문장으로."},
    ]


async def overall(vllm: VLLMClient, ctx: str, seg_summaries: list[str]) -> str:
    """구간요약 전부 → 전체 줄거리 (1콜). 실패 시 구간요약 이어붙임으로 폴백."""
    if not any(seg_summaries):
        return ""
    try:
        text, ms = await vllm.chat(
            messages=build_overall(ctx, seg_summaries),
            temperature=0.2, max_tokens=2048,
            extra_body={"chat_template_kwargs": {"enable_thinking": False}},
        )
        log.info(f"summary overall ({ms}ms): {len(text.strip())}자")
        return text.strip()
    except Exception as e:  # noqa: BLE001 — 실패 시 구간요약 이어붙임
        log.warning(f"summary overall 실패 → 구간요약 연결로 폴백: {e}")
        return " ".join(s for s in seg_summaries if s)
