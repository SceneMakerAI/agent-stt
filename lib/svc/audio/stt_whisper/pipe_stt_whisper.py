"""2차 전사 스텝 (whisper) — 1차 대사 중 '보낼 만한 구간'만 골라 다시 받아쓴다.

이 디렉토리의 **진입점**이다. 바깥(pipe_audio)은 이 파일만 부른다.

  구간 선정(pick) → 프롬프트 만들기(prompt) → whisper_stt(client) → 게이트 채택
  산출은 {idx: 텍스트} **부분 맵** — 1차 전체를 대체하는 게 아니라, 교정이 [B] 로 대조할
  '두 번째 의견'만 모은다. 없는 idx 는 교정이 1차 텍스트를 그대로 쓴다.

어떤 카테고리를 보낼지는 호출측(프로파일)이 정한다. 여기선 구간 품질만 본다:
  - 뉴스 96% / 다큐 84% 는 이미 1차와 일치 → 이득 없이 환각 위험만이라 아예 안 부른다.
  - 스포츠 56% / 드라마 65~73% 는 whisper 가 실제로 고침(좌측에·1아웃 1루와 3루).

무엇을 거르는지 (6영상 실측):
  - 짧은 필러(0.3초 "자") → whisper 가 없는 말을 지어냄 ("MBC 뉴스 김성현입니다")
  - 영어/중국어/일본어 구간 → ko 강제라 유창한 환각 ("다음 영상에서 만나요")
  - 워커가 flag 로 환각을 표시해 보내면 그 창은 결과에서 버린다

프롬프트(whisper initial_prompt)로 등장인물 이름을 편향시킨다 — v1 실측:
  정근호→정근우 / 구톰순→구톰슨 / 정분우→정근우 / 박정근→박정권 (6구간 전부 교정)
이름이 맞으면 주변 디코딩도 안정된다("그런 배가"→"그런 회가"). 그래서 교정 프롬프트의
'이름은 [B] 를 믿지 마라' 방어를 풀 수 있고, 그 효과가 이름 교정 자체보다 컸다.
"""
import asyncio
import re

import httpx

from lib.client.stt import whisper_stt
from lib.log import get_logger
from lib.svc.audio.stt_qwen.schema_dialogue import Dialogues
from lib.svc.audio.stt_whisper import util_stt_whisper
from lib.svc.audio.stt_whisper.schema_whisper import Whisper, Whispers

log = get_logger(__name__)

MIN_SEC = 3.0       # 이보다 짧으면 문맥 부족 → whisper 환각
                    #   ⚠ 2.0 으로 낮춰봤으나 손해(v1 GT 40→38~40). 대상 +21창이 되면서
                    #   짧은 창의 whisper 가 얻는 것보다 흔드는 게 많았다. 3.0 유지할 것.
MIN_CHARS = 12      # 내용 밀도. 길어도 내용 없으면(음악/함성) 환각
MIN_KO = 0.5        # 한글 비율 — 영어·중국어·일본어 구간 차단

# whisper initial_prompt 예산. whisper 는 224 토큰까지만 반영하고 넘치면 앞을 자른다.
# 한글은 토큰 효율이 나빠(이름 1개 ≈ 3~5토큰) 글자수로 넉넉히 잡는다. v1 실측 30명=149자.
PROMPT_BUDGET = 150


# ── 대상 선정 (뭘 보낼지) ─────────────────────────────────────────────
def pick(dialogues: Dialogues) -> list[dict]:
    """2차 전사를 돌릴 구간만 고른다 (구간 품질 필터) → 워커에 보낼 창 목록.

    짧은 필러(문맥 부족)·내용 없는 창(음악/함성)·비한국어(ko 강제라 환각)를 뺀다.
    카테고리 게이팅은 호출측이 이미 판정했으므로 여기선 안 본다.
    """
    out = []
    for s in dialogues.items:
        if s.lang != "Korean":
            continue
        if (s.end_sec - s.start_sec < MIN_SEC
                or util_stt_whisper.chars(s.text) < MIN_CHARS
                or util_stt_whisper.ko_ratio(s.text) < MIN_KO):
            continue
        out.append({"idx": s.idx, "start": round(s.start_sec, 2),
                    "end": round(s.end_sec, 2), "language": "ko"})
    log.info(f"stt2 대상: {len(dialogues.items)}줄 → {len(out)}창")
    return out


# ── whisper 프롬프트 (뭘 편향시킬지) ──────────────────────────────────
def prompt(roster: str, dialogues: Dialogues) -> str:
    """명단 + 1차 대사 → whisper initial_prompt ("이름1, 이름2, ... ." / 없으면 "").

    명단 전체(v1 105명)는 예산에 안 들어가므로 **1차 자막에 실제로 나온 순**으로 추린다.
    LLM 으로 '중요한 사람'을 고르지 않는 이유 — LLM 은 이 영상에 누가 나오는지 모르고
    유명도로 고르게 된다. 등장 횟수는 그걸 데이터로 안다. 게다가 명단에 섞인 오류
    (2009년 KIA 에 없는 고우석, 두산 소속 안경현 등)가 0회로 자동 탈락한다. LLM 콜도 없다.

    명단 형식은 검색 추출 프롬프트가 '-<이름>—<역할>' 로 강제하지만 LLM 출력이라
    대시 뒤 공백·괄호 표기가 흔들린다 → '-' 뒤 한글만 느슨하게 잡는다
    ("- 강준상(이민형)—..." → "강준상"). 못 뽑아도 프롬프트가 빌 뿐이라 현행 동작으로 돌아간다.
    """
    if not roster.strip():
        return ""
    names = set(re.findall(r"^-\s*([가-힣]{2,5})", roster, re.M))
    if not names:
        return ""
    text = " ".join(s.text for s in dialogues.items)
    ranked = sorted(((text.count(n), n) for n in names if text.count(n) > 0), reverse=True)

    picked: list[str] = []
    for _, name in ranked:
        if len(", ".join([*picked, name])) + 1 > PROMPT_BUDGET:
            break
        picked.append(name)
    if not picked:
        return ""
    log.info(f"stt2 프롬프트: 명단 {len(names)}명 → 자막등장 {len(ranked)}명 → 채택 {len(picked)}명")
    return ", ".join(picked) + "."


# ── 공개 진입점 ───────────────────────────────────────────────────────
async def run(http: httpx.Client, v_id: int, dialogues: Dialogues,
              roster: str = "") -> Whispers:
    """2차 전사 → Whispers (게이트 통과분만). 보낼 구간이 없으면 빈 Whispers.

    dialogues : 1차 전사 결과 (구간 선정·프롬프트 재료)
    roster    : 명단 텍스트(search). 없으면 프롬프트 없이 보낸다.

    flag(lowconf/repeat/fallback/echo/empty) 나 error 가 붙은 창은 신뢰할 수 없어 버린다 —
    호출측은 "그 idx 는 whisper 가 없다"로 취급하면 된다(교정이 1차 텍스트를 유지).
    전사는 블로킹이라 스레드로 넘긴다.
    """
    windows = pick(dialogues)
    if not windows:
        return Whispers()

    res = await asyncio.to_thread(
        whisper_stt.transcribe, http, v_id, windows, prompt(roster, dialogues))

    items, dropped = [], 0
    for x in res.results:
        text = x.text.strip()
        if x.error or x.flag or not text:
            dropped += 1
            continue
        items.append(Whisper(idx=x.idx, text=text))
    log.info(f"stt2 done: 요청 {len(windows)}창 → 채택 {len(items)} (게이트 탈락 {dropped})")
    return Whispers(items=items)
