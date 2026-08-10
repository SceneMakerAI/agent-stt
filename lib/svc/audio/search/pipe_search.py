"""웹 명단 검색 — 제목/연도/카테고리 → 등장인물·선수 명단(텍스트). (1차 공정 ③④)

이 디렉토리의 **진입점**이다. 바깥(process)은 이 파일만 import 한다.

흐름:
  ② 질의 생성 : vllm_search.gen_queries    — "site:<도메인> <검색어>" 질의 N개
  ③ 검색+본문 : fetch()                   — 질의별로 문서 1개 확보 (실패는 pass)
  ④ 내용 취합 : vllm_search.extract_roster — 확보한 본문들에서 명단만 텍스트로

파일 넷으로 나뉜다 — 이 파일은 순서·폴백 정책과 ③ 을 갖는다:
  lib/client/search_web/engine_web.py  부르는 법     (검색·본문추출. 엔진 교체 지점)
  vllm_search.py                       LLM 콜        (②④ + 프롬프트)
  util_search.py                       보조 순수함수 (본문 판정 / 결과 포맷)
  schema_search.py                     산출물        (Search_Doc / Search_Site / Roster)

vLLM 클라이언트는 외부 주입 (process 가 state.vllm 을 넘김). 블로킹(검색)은 여기서
to_thread 로 넘긴다.
"""
import asyncio

from lib.client import vllm
from lib.client.search_web import engine_web
from lib.log import get_logger
from lib.svc.audio.search import util_search, vllm_search
from lib.svc.audio.search.schema_search import Roster, Search_Doc, Search_Site

log = get_logger(__name__)

CANDIDATES = 5   # 질의당 검색 후보 수 (폴백용으로 넉넉히)
MAX_TRIES = 3    # 후보를 위→아래로 최대 몇 번 추출 시도 (다 실패하면 pass)

# 진입점 일원화 — 바깥은 pipe_search 하나만 알면 된다 (결과 포맷 구현은 util_search).
format_query = util_search.format_query
format_dump = util_search.format_dump


def fetch(query: str) -> Search_Doc | None:
    """③ 질의 하나 → 쓸 만한 문서 하나. 다 실패하면 None (그 질의는 pass).

    엔진 호출은 engine_web 이 하고 여기는 **언제 포기할지**만 정한다 — 후보를 CANDIDATES 개
    받아 위→아래로 최대 MAX_TRIES 회 본문 추출을 시도하고 첫 성공을 쓴다.
    '쓸 만한지' 판정은 util_search.usable (200자 미만·빈 본문 거르기).
    블로킹 — run 이 to_thread 로 넘긴다.
    """
    for hit in engine_web.search(query, max_results=CANDIDATES)[:MAX_TRIES]:
        body = engine_web.extract(hit.href)
        if util_search.usable(body):
            return Search_Doc(keyword=query, url=hit.href, title=hit.title, content=body)
    return None


async def run(v: vllm.VLLMClient, question: str, year, category: str) -> Roster:
    """제목/연도/카테고리 → Roster(명단 텍스트 + 질의 + 질의별 결과).

    확보 문서가 0이면 명단은 "" 다 (질의·trace 는 그대로 남긴다 — 왜 못 구했는지 봐야 하니까).
    year 는 None/"" 가능 (연도 없이 검색).
    """
    queries = await vllm_search.gen_queries(v, question, year, category)

    # 질의별 fetch(블로킹 검색)를 스레드로 동시 실행 — gather 는 입력 순서 유지
    results = await asyncio.gather(*(asyncio.to_thread(fetch, q) for q in queries))
    docs: list[Search_Doc] = []       # 성공 문서 (추출 입력)
    trace: list[Search_Site] = []    # 질의별 결과 (검수용)
    for q, d in zip(queries, results):
        if d:
            docs.append(d)
            trace.append(Search_Site(keyword=q, url=d.url, title=d.title))
            log.info(f"web_search '{q}' → {d.url} ({len(d.content)}자)")
        else:
            trace.append(Search_Site(keyword=q))
            log.info(f"web_search '{q}' → {MAX_TRIES}회 실패, pass")
    log.info(f"web_search 확보 문서 {len(docs)}/{len(queries)}")

    text = "" if not docs else await vllm_search.extract_roster(v, question, year, category, docs)
    if not docs:
        log.warning("web_search 확보 문서 0 → 빈 명단 반환")
    return Roster(Text=text, LLM_Search_Keywords=queries, Search_Sites=trace)


if __name__ == "__main__":   # 단독 테스트: python -m lib.svc.audio.search.pipe_search
    import ssl

    async def _demo():
        ssl.create_default_context()   # main.py 와 동일한 OpenSSL 선초기화 워크어라운드
        v = vllm.build()
        try:
            res = await run(v, "코리안시리즈 KIA vs SK", 2009, "스포츠-야구")
            print("\n=== 최종 결과 ===")
            print(format_dump(res))
        finally:
            await v.close()

    asyncio.run(_demo())
