"""자막 교정 — segments → 교정된 segments. (하나의 '프로세스')

이 디렉토리의 **진입점**이다. 바깥(process)은 이 파일만 import 한다.

흐름:
  1. util_correct.split    대사를 페이지로 나눔
  2. 페이지별 병렬          vllm_correct.correct_page  (asyncio.gather, Semaphore 가 동시성 제한)
  3. util_correct.merge    idx 로 원본의 text 만 교체 (메타는 그대로)

실패한 페이지(호출 오류·JSON 깨짐·idx 불일치)는 '원문 유지'로 안전하게 fallback.
자막은 한 줄도 빠지면 안 되므로, 교정 실패 < 원문 보존.

파일 넷으로 나뉜다 — 이 파일은 순서와 실패 정책만 안다:
  vllm_correct.py       LLM 콜 + 프롬프트
  util_correct.py       페이지 분할 / 취합·길이검증
  glossary_correct.py   용어집 텍스트 (카테고리별 자산)
"""
import asyncio
from dataclasses import replace

from lib.client.vllm import VLLMClient
from lib.log import get_logger
from lib.svc.audio.correct import util_correct, vllm_correct
from lib.svc.audio.stt_qwen.schema_dialogue import Dialogues
from lib.svc.audio.stt_whisper.schema_whisper import Whispers

log = get_logger(__name__)


async def run(vllm: VLLMClient, dialogues: Dialogues, roster: str = "", req=None,
              whispers: Whispers | None = None, glossary: str = "") -> Dialogues:
    """대사 전체 교정 → 새 Dialogues (text 만 교정, 나머지 필드는 그대로).

    원본은 안 건드린다 — 잘렸을 때 되돌리고(MIN_KEEP_RATIO) 실패 페이지를 원문으로
    폴백하려면 원문이 남아 있어야 한다.

    참고자료 넷을 각 페이지 프롬프트에 싣는다 (없으면 해당 섹션 생략 → 기존 동작):
      roster   : 등장인물·선수 명단 — 인물 이름 표기의 근거
      req      : 영상 정보(제목/카테고리/방송연도)
      whispers : 2차 전사 — 같은 오디오의 '두 번째 의견'. 이름 아닌 오인식(자치계→좌측에)을
                 대조로 잡는다. 없는 idx 는 1차만으로 교정.
      glossary : 용어집 텍스트 (이미 골라서 넘어온 것 — 카테고리 판정은 호출측 몫)

    조회표(idx→text)는 여기서 만든다 — 줄마다 찾아야 해서 표가 필요한 건 교정의 사정이라,
    호출측이 알 필요가 없다.
    """
    whisper_map = {w.idx: w.text for w in (whispers.items if whispers else [])}
    pages = util_correct.split(dialogues.items)
    log.info(f"correct: {len(dialogues.items)}줄 → {len(pages)} pages "
             f"(roster {len(roster)}자, whisper {len(whisper_map)}건, 용어집 {len(glossary)}자)")

    # 페이지별 교정을 한꺼번에 띄움. 실제 동시 호출 수는 vllm 내부 Semaphore 가 제한.
    page_fixes = await asyncio.gather(
        *[vllm_correct.correct_page(vllm, p, roster, req, whisper_map, glossary) for p in pages])

    # 취합: 모든 페이지의 { idx: 교정 text } 를 하나로 합침.
    fixed_text: dict[int, str] = {}
    for m in page_fixes:
        fixed_text.update(m)

    items, truncated = util_correct.merge(dialogues.items, fixed_text)
    if truncated:
        log.info(f"correct: 길이 미달로 원문 유지 {truncated}줄 "
                 f"(<{util_correct.MIN_KEEP_RATIO:.0%})")
    return replace(dialogues, items=items)
