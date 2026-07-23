"""웹 명단 검색 — 제목/연도/카테고리 → 등장인물·선수 명단(텍스트). (1차 공정 ③④)

흐름:
  ② 질문 수정 : LLM 이 "site:<도메인> <검색어>" 질의 N개 생성 (JSON)
  ③ 검색+본문 : 각 질의를 bing(ddgs, backend 고정) 검색 → 후보 위→아래 최대 MAX_TRIES 회
                본문 추출(ddgs.extract, markdown) 시도 → 성공 1개, 다 실패면 그 질의 pass
  ④ 내용 취합 : LLM 이 본문들에서 카테고리에 맞는 명단만 텍스트로 추출

설계 결정(테스트로 검증):
  - 검색은 ddgs `backend="bing"` 고정 — 기본(auto)은 엔진 랜덤이라 비결정적.
  - 본문 fetch·HTML 정제는 ddgs.extract 가 처리 (위키·나무 공통, 분기 없음).
  - LLM 콜 둘 다 temperature=0 / enable_thinking=False. 최종 추출은 JSON 미사용(텍스트).
  - 실패 질의는 pass, 확보된 본문만 추출 (한 질의 실패가 전체를 흔들지 않게).

vLLM 클라이언트는 외부 주입 (process 가 state.vllm 을 넘김). 블로킹(ddgs)은 호출부에서
to_thread 로 넘긴다.
"""
import asyncio
import json

from ddgs import DDGS

from lib.client import vllm
from lib.log import get_logger

log = get_logger(__name__)

# ── 고정 파라미터
N_QUERIES = 4          # LLM 이 만들 질의 수
FETCH_MAXLEN = 20000   # 본문 1개당 LLM 에 넣을 최대 길이
MIN_BODY = 200         # 이보다 짧거나 실패/빈 본문은 실패로 간주 (0자·stub 노이즈)
BING_CANDIDATES = 5    # 질의당 bing 후보 수 (폴백용으로 넉넉히)
MAX_TRIES = 3          # 후보를 위→아래로 최대 몇 번 추출 시도 (다 실패하면 pass)

SITES = ["namu.wiki", "ko.wikipedia.org", "en.wikipedia.org"]   # 질의 허용 도메인 팔레트

THINK_OFF = {"chat_template_kwargs": {"enable_thinking": False}}
JSON_OUT = {"type": "json_object"}


# ── ② 질문 수정 — LLM 이 site: 질의 세트 생성
QGEN_SYSTEM = """너는 웹검색 질의를 만드는 도우미다.
주어진 영상 정보(제목/연도/카테고리)로 '등장인물·선수 명단'을 찾기 위한
DuckDuckGo 검색 질의를 만든다.

[규칙]
- 각 질의는 반드시 "site:<도메인> <검색어>" 형식. 도메인은 아래 목록에서만 고른다.
- 스포츠 경기(예: A vs B)면 양 팀을 각각 따로 질의한다. 연도가 주어졌으면 연도를 붙인다.
- 드라마면 "<제목> 등장인물" 처럼 배역을 찾는 질의를 만든다.
- 명단이 잘 나올 site 를 골라 배분한다 (한 site 만 쓰지 말 것).

[허용 site]
{sites}

[출력] 오직 JSON: {{"queries": ["site:... ...", ...]}}  (정확히 {n}개)"""


async def _gen_queries(v: vllm.VLLMClient, question: str, year, category: str) -> list[str]:
    lines = [f"제목/설명: {question}", f"카테고리: {category}"]
    if year:
        lines.insert(1, f"연도: {year}")
    text, ms = await v.chat(
        messages=[
            {"role": "system", "content": QGEN_SYSTEM.format(sites="\n".join(SITES), n=N_QUERIES)},
            {"role": "user", "content": "\n".join(lines)},
        ],
        temperature=0, response_format=JSON_OUT, extra_body=THINK_OFF,
    )
    queries = json.loads(text)["queries"]
    log.info(f"web_search 질의 생성 ({ms}ms): {queries}")
    return queries


# ── ③ bing 검색 + 본문 추출 (fetch·HTML 정제는 ddgs.extract 가 처리)
def _fetch_body(url: str) -> str | None:
    """URL 본문을 ddgs.extract 로 받아 markdown 텍스트로 반환 (위키·나무 공통).
    fetch 실패/너무 짧은 본문은 None (→ 상위에서 다음 후보로 폴백)."""
    try:
        res = DDGS().extract(url.replace("+", "%20"), fmt="text_markdown")  # href 공백 '+' → 실제 URL
        body = res.get("content", "") or ""
    except Exception:  # noqa: BLE001 — fetch 오류 → 폴백 신호
        return None
    return body if len(body) >= MIN_BODY else None


def search_fetch(query: str) -> dict | None:
    """bing 검색(site 고정) → 후보 위→아래로 최대 MAX_TRIES 회 본문 추출 시도 → 성공 1개.
    MAX_TRIES 다 실패하면 None (그 질의는 pass). 블로킹 — 호출부가 to_thread 로 넘긴다."""
    try:
        rows = DDGS().text(query, region="kr-kr", backend="bing", max_results=BING_CANDIDATES)
    except Exception:  # noqa: BLE001 — "No results"/rate-limit 등 검색 실패 → 그 질의 pass
        return None
    for cand in rows[:MAX_TRIES]:
        url = cand.get("href", "")
        body = _fetch_body(url)
        if body:
            return {"query": query, "url": url, "title": cand.get("title", ""), "body": body}
    return None


# ── ④ 내용 취합 — LLM 이 카테고리에 맞는 명단 추출
EXTRACT_SYSTEM = """너는 여러 백과사전 본문에서 이 영상의 명단을 뽑는 추출기다.

[카테고리별로 뽑을 것]
- 스포츠(야구/축구 등): 양 팀 각각의 선수·감독. role 에는 보직/포지션(감독/투수/타자/공격수 등).
- 드라마/사극: 배역 이름(배우 실명 아님). role 에는 그 인물의 역할·설명을 한 줄로
  (예: "남자주인공, 피아니스트, 교통사고로 기억상실" / "준상의 첫사랑").

[규칙]
- 본문에 실제로 있는 이름만. 지어내지 마라.
- **본문에 그 팀/작품의 명단이 없으면 그 구분을 비워라. 네 지식으로 채우지 마라.**
- 이 영상(연도/팀/작품)과 무관한 인물은 빼라.
- role 은 본문 근거로 간결히. 근거 없으면 "".

[출력] JSON 아님. 사람이 읽는 텍스트로. 아래 형식만:
카테고리: <카테고리>

## <팀 또는 구분 이름>
-<이름>—<역할/설명>    (역할 근거 없으면 이름만)
-...

## <다른 구분>
-...

다른 말(머리말/설명/코드블록)은 붙이지 마라."""


async def _extract(v: vllm.VLLMClient, question: str, year, category: str, docs: list[dict]) -> str:
    joined = "\n\n".join(
        f"### 출처: {d['title']} ({d['url']})\n{d['body'][:FETCH_MAXLEN]}" for d in docs
    )
    ctx = f"영상: {question}" + (f" / 연도 {year}" if year else "") + f" / 카테고리 {category}"
    user = f"{ctx}\n\n아래 본문들에서 명단을 뽑아 지정 형식으로.\n\n{joined}"
    text, ms = await v.chat(
        messages=[{"role": "system", "content": EXTRACT_SYSTEM}, {"role": "user", "content": user}],
        temperature=0, max_tokens=8192, extra_body=THINK_OFF,
    )
    log.info(f"web_search 추출 완료 ({ms}ms): {len(text)}자")
    return text


# ── 공개 진입점 (②③④ 오케스트레이션)
async def search_web(v: vllm.VLLMClient, question: str, year, category: str) -> dict:
    """제목/연도/카테고리 → {"roster", "queries", "trace"}.

    roster  : 명단 텍스트 (교정 입력용 — 이것만 corrector 에 넘긴다). 확보 문서 없으면 "".
    queries : LLM 이 만든 검색 질의들
    trace   : 질의별 결과 [{query, url|None, title}]  (검수용 — 어떻게 검색했는지)
    year 는 None/"" 가능 (연도 없이 검색).
    """
    queries = await _gen_queries(v, question, year, category)

    # 질의별 search_fetch(블로킹 ddgs)를 스레드로 동시 실행 — gather 는 입력 순서 유지
    results = await asyncio.gather(*(asyncio.to_thread(search_fetch, q) for q in queries))
    docs: list[dict] = []      # 성공 문서 (추출 입력)
    trace: list[dict] = []     # 질의별 결과 (덤프용)
    for q, d in zip(queries, results):
        if d:
            docs.append(d)
            trace.append({"query": q, "url": d["url"], "title": d.get("title", "")})
            log.info(f"web_search '{q}' → {d['url']} ({len(d['body'])}자)")
        else:
            trace.append({"query": q, "url": None, "title": ""})
            log.info(f"web_search '{q}' → {MAX_TRIES}회 실패, pass")
    log.info(f"web_search 확보 문서 {len(docs)}/{len(queries)}")

    roster = "" if not docs else await _extract(v, question, year, category, docs)
    if not docs:
        log.warning("web_search 확보 문서 0 → 빈 명단 반환")
    return {"roster": roster, "queries": queries, "trace": trace}


def format_query(result: dict) -> str:
    """검색 질의 → 조회 문서 (t_video.search_query 컬럼 / 덤프 헤더용)."""
    lines = ["[검색 질의] (LLM 생성 → 조회한 문서)"]
    for t in result.get("trace", []):
        # DDG href 는 공백을 '+' 로 주는데 그대로면 브라우저에서 안 열림 → 실제 조회한 %20 형태로 표시
        dst = t["url"].replace("+", "%20") if t.get("url") else "(3회 실패, pass)"
        lines.append(f"- {t['query']}\n    → {dst}")
    return "\n".join(lines)


def format_dump(result: dict) -> str:
    """질의 + 명단을 검수용 텍스트로 (2_roster 덤프)."""
    return f"{format_query(result)}\n\n[명단]\n{result.get('roster') or '(명단 없음)'}"


if __name__ == "__main__":   # 단독 테스트: python -m lib.svc.stt.search.web_search
    import ssl

    async def _demo():
        ssl.create_default_context()   # main.py 와 동일한 OpenSSL 선초기화 워크어라운드
        v = vllm.build()
        try:
            res = await search_web(v, "코리안시리즈 KIA vs SK", 2009, "스포츠-야구")
            print("\n=== 최종 결과 ===")
            print(format_dump(res))
        finally:
            await v.close()

    asyncio.run(_demo())
