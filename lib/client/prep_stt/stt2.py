"""stt2_svc 호출 — 2차 전사(whisper). 교정 리컨사일용. (transport)

  POST STT2_URL  {v_id, windows[]} → results[]

1차(Qwen)가 뽑은 구간 중 '보낼 만한 것'만 골라 워커에 던지면, 워커가 그 구간만
seek-read 해서 whisper 로 다시 받아쓴다. 화자·시각은 1차 것을 쓰므로 텍스트만 받는다.

pick_windows() 로 대상을 고르는 이유 (6영상 실측):
  - 짧은 필러(0.3초 "자") → whisper 가 없는 말을 지어냄 ("MBC 뉴스 김성현입니다")
  - 영어/중국어/일본어 구간 → ko 강제라 유창한 환각 ("다음 영상에서 만나요")
  - 뉴스 96% / 다큐 84% 는 이미 1차와 일치 → 이득 없이 환각 위험만. 스킵.
  - 스포츠 56% / 드라마 65~73% 는 whisper 가 실제로 고침(좌측에·1아웃 1루와 3루). 적용.

워커가 게이트(flag)로 환각을 이미 걸러 보내므로, flag 붙은 창은 여기서 버린다.

prompt(whisper initial_prompt)로 등장인물 이름을 편향시킨다 — v1 실측:
  정근호→정근우 / 구톰순→구톰슨 / 정분우→정근우 / 박정근→박정권 (6구간 전부 교정)
이름이 맞으면 주변 디코딩도 안정된다("그런 배가"→"그런 회가"). 그래서 교정 프롬프트의
'이름은 [B] 를 믿지 마라' 방어를 풀 수 있고, 그 효과가 이름 교정 자체보다 컸다.
"""
import re

import httpx
from pydantic import BaseModel

import config
from lib.log import get_logger

log = get_logger(__name__)

STT2_URL = f"{config.PREP_STT_BASE_URL}/stt2_svc/"

CATEGORIES = ("스포츠", "드라마")   # 게이팅 — 이 카테고리만 2차 전사
MIN_SEC = 3.0       # 이보다 짧으면 문맥 부족 → whisper 환각
                    #   ⚠ 2.0 으로 낮춰봤으나 손해(v1 GT 40→38~40). 대상 +21창이 되면서
                    #   짧은 창의 whisper 가 얻는 것보다 흔드는 게 많았다. 3.0 유지할 것.
MIN_CHARS = 12      # 내용 밀도. 길어도 내용 없으면(음악/함성) 환각
MIN_KO = 0.5        # 한글 비율 — 영어·중국어·일본어 구간 차단

# whisper initial_prompt 예산. whisper 는 224 토큰까지만 반영하고 넘치면 앞을 자른다.
# 한글은 토큰 효율이 나빠(이름 1개 ≈ 3~5토큰) 글자수로 넉넉히 잡는다. v1 실측 30명=149자.
PROMPT_BUDGET = 150


class Window(BaseModel):
    idx: int                # 창 식별자 — 워커가 그대로 되돌려줌
    start: float            # 구간 시작 (초)
    end: float              # 구간 끝 (초)
    language: str = "ko"    # 강제 언어 (자동감지 X)


class Stt2Request(BaseModel):
    v_id: str
    windows: list[Window]
    prompt: str = ""        # whisper initial_prompt (등장인물 편향). 빈 문자열이면 미적용


def stt2(http: httpx.Client, vid: int, segments: list[dict], category: str,
         roster: str = "") -> dict[int, str]:
    """2차 전사 — 대상 구간만 골라 POST STT2_URL → {idx: whisper 텍스트}.

    segments : 1차 STT 산출물 [{idx, start:"HH:MM:SS.s", end, text, lang}, ...]
    category : 게이팅 키 (스포츠·드라마만 수행, 그 외는 {} 반환)
    roster   : 명단 텍스트(web_search) — 여기서 whisper 프롬프트를 만든다. 없으면 프롬프트 없이.

    대상 선정은 내부(_pick)에서 한다 — 필터 없이 이 호출을 할 일이 없으므로 묶었다.
    flag(lowconf/repeat/fallback/echo/empty) 나 error 가 붙은 창은 신뢰 불가라 결과에서 뺀다.
    → 호출측은 "그 idx 는 whisper 가 없다"로 취급하면 된다 (교정이 1차 텍스트를 유지).
    """
    windows = _pick(segments, category)
    if not windows:
        return {}
    body = Stt2Request(v_id=str(vid), windows=[Window(**w) for w in windows],
                       prompt=_prompt(roster, segments))
    r = http.post(STT2_URL, json=body.model_dump(), timeout=config.STT_TIMEOUT_S)
    r.raise_for_status()
    results = r.json().get("results", [])

    out, dropped = {}, 0
    for x in results:
        text = (x.get("text") or "").strip()
        if x.get("error") or x.get("flag") or not text:
            dropped += 1
            continue
        out[int(x["idx"])] = text
    log.info(f"stt2 done: 요청 {len(windows)}창 → 채택 {len(out)} (게이트 탈락 {dropped})")
    return out


# ── whisper 프롬프트 (뭘 편향시킬지) ──────────────────────────────────
def _prompt(roster: str, segments: list[dict]) -> str:
    """명단 + 1차 STT → whisper initial_prompt ("이름1, 이름2, ... ." / 없으면 "").

    명단 전체(v1 105명)는 예산에 안 들어가므로 **1차 자막에 실제로 나온 순**으로 추린다.
    LLM 으로 '중요한 사람'을 고르지 않는 이유 — LLM 은 이 영상에 누가 나오는지 모르고
    유명도로 고르게 된다. 등장 횟수는 그걸 데이터로 안다. 게다가 명단에 섞인 오류
    (2009년 KIA 에 없는 고우석, 두산 소속 안경현 등)가 0회로 자동 탈락한다. LLM 콜도 없다.

    명단 형식은 EXTRACT_SYSTEM 이 '-<이름>—<역할>' 로 강제하지만 LLM 출력이라
    대시 뒤 공백·괄호 표기가 흔들린다 → '-' 뒤 한글만 느슨하게 잡는다
    ("- 강준상(이민형)—..." → "강준상"). 못 뽑아도 프롬프트가 빌 뿐이라 현행 동작으로 돌아간다.
    """
    if not roster.strip():
        return ""
    names = set(re.findall(r"^-\s*([가-힣]{2,5})", roster, re.M))
    if not names:
        return ""
    text = " ".join(s.get("text", "") for s in segments)
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


# ── 대상 선정 (뭘 보낼지) ─────────────────────────────────────────────
def _pick(segments: list[dict], category: str) -> list[dict]:
    """2차 전사를 돌릴 구간만 고른다. 대상 아니면 [].

    거르는 이유는 모듈 docstring 참고 — 짧은 필러·비한국어·이득 없는 카테고리를 뺀다.
    """
    if not (category and category.startswith(CATEGORIES)):
        return []
    out = []
    for s in segments:
        if s.get("lang") != "Korean":
            continue
        a, b = _sec(s["start"]), _sec(s["end"])
        if b - a < MIN_SEC or _chars(s["text"]) < MIN_CHARS or _ko_ratio(s["text"]) < MIN_KO:
            continue
        out.append({"idx": s["idx"], "start": round(a, 2), "end": round(b, 2), "language": "ko"})
    log.info(f"stt2 대상: {len(segments)}세그 → {len(out)}창 (category={category!r})")
    return out


def _chars(text: str) -> int:
    """공백·문장부호 뺀 글자수 (내용 밀도)."""
    return len(re.sub(r"[\s.,!?~·'\"]", "", text))


def _ko_ratio(text: str) -> float:
    """글자 중 한글 비율. 분모 = 한글+라틴+한자+가나 (숫자·기호 제외).

    숫자를 분모에서 빼는 게 핵심 — "126 구톰슨의 킹머신이 1.2" 같은 통계 문장이
    숫자 때문에 외국어로 오판되면 안 된다 (구톰슨은 한글이므로 한국어).
    """
    ko = sum('가' <= c <= '힣' for c in text)
    other = sum(('一' <= c <= '鿿') or ('぀' <= c <= 'ヿ') or (c.isascii() and c.isalpha())
                for c in text)
    return ko / max(1, ko + other)


def _sec(t: str) -> float:
    """'HH:MM:SS.s' → 초."""
    h, m, s = t.split(":")
    return int(h) * 3600 + int(m) * 60 + float(s)
