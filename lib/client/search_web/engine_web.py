"""웹 검색 엔진 호출 — 질의 검색 + 본문 추출. (transport)

  search(query)  질의 → 후보 목록 [{title, href, body}, ...]
  extract(url)   URL → 본문 markdown 텍스트

현재 백엔드는 ddgs 의 bing 이다. **엔진을 갈아끼울 지점은 이 파일 하나** — 호출측
(svc/…/search_web.py)은 ddgs 를 모른다. namu.wiki 가 CC BY-NC-SA(비영리)라 상업 배포 시
구글 Custom Search API 등으로 검색부만 바꿔야 하는데, 그때 여기 두 함수만 갈면 된다.

설계 결정(테스트로 검증):
  - backend="bing" 고정 — 기본(auto)은 엔진 랜덤이라 비결정적이다. bing 은 3/3 동일 top +
    site: 지원. google/brave/wikipedia 백엔드는 이 서버 IP 에서 "No results" 로 막힌다
    (bing 공식 API 는 2025-08 은퇴 — ddgs 경유라 무관).
  - 본문 fetch·HTML 정제는 ddgs.extract 가 처리한다 (위키·나무 공통, 분기 없음).

⚠ **여기서 품질 판단은 하지 않는다.** 본문이 쓸만한지(길이), 후보를 몇 개 받고 몇 번까지
   재시도할지는 정책이라 호출측(svc) 몫이다. 이 파일은 "부르고, 받은 걸 준다"까지만.
   실패는 예외로 올리지 않고 빈 값으로 돌려준다 — 한 질의의 실패가 전체 검색을 흔들면 안 된다.

블로킹 호출이다 — 호출측이 to_thread 로 넘긴다.
"""
from dataclasses import dataclass

from ddgs import DDGS

from lib.log import get_logger

log = get_logger(__name__)

REGION = "kr-kr"     # 검색 지역 (한국어 문서 우선)
BACKEND = "bing"     # 위 설계 결정 참고. 바꾸면 결과가 비결정적이 된다


@dataclass
class Result_Search:
    """검색 결과 한 건 — 엔진이 보여주는 목록 한 줄. 본문이 아니다."""
    title: str = ""
    href: str = ""      # 이 링크로 본문을 따로 받는다 (extract)
    body: str = ""      # 검색 스니펫(200자 남짓). 명단 추출엔 부족해서 안 쓴다


def search(query: str, max_results: int,
           region: str = REGION, backend: str = BACKEND) -> list[Result_Search]:
    """질의 → 후보 목록. 실패하면 빈 리스트.

    "No results" / rate-limit 등 검색 실패를 예외로 올리지 않는다 — 호출측이 '이 질의는
    pass' 로 넘어갈 수 있어야 한다.

    키를 하나씩 꺼내 담는다 — ddgs 는 우리가 못 고치는 외부 라이브러리라, 키가 늘거나
    빠져도 터지지 않게 받는다. (우리 워커는 반대로 계약이 깨지면 즉시 터뜨린다)
    """
    try:
        rows = DDGS().text(query, region=region, backend=backend, max_results=max_results)
    except Exception as e:  # noqa: BLE001 — 검색 실패 → 빈 결과로 신호
        log.warning(f"web 검색 실패 '{query}': {e}")
        return []
    return [Result_Search(title=r.get("title", ""), href=r.get("href", ""), body=r.get("body", ""))
            for r in rows]


def extract(url: str) -> str | None:
    """URL 본문 → markdown 텍스트. fetch 실패면 None (빈 본문은 "" — 실패와 구분된다).

    ⚠ href 의 공백은 DDG 가 '+' 로 주는데 그대로 열면 404 다 → '%20' 으로 바꿔 요청한다.
      (반환하는 dict 의 url 은 호출측이 갖고 있는 원본 href 그대로다)
    """
    try:
        res = DDGS().extract(url.replace("+", "%20"), fmt="text_markdown")
    except Exception as e:  # noqa: BLE001 — fetch 오류 → 폴백 신호
        log.debug(f"본문 추출 실패 {url}: {e}")
        return None
    return res.get("content", "") or ""
