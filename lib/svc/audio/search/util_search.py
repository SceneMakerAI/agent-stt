"""웹 명단 검색의 보조 함수 — 순수 함수만. (pipe_search 가 쓴다)

외부 호출도 상태도 없다. 둘로 나뉜다:
  usable()                   확보한 본문을 쓸 수 있는지 판정 (폴백 여부를 정하는 기준)
  format_query/format_dump   Roster → 사람이 읽는 텍스트 (DB 컬럼 / 검수 덤프)
"""
from lib.svc.audio.search.schema_search import Roster

MIN_BODY = 200   # 이보다 짧거나 실패/빈 본문은 실패로 간주 (0자·stub 노이즈)


def usable(body: str | None) -> bool:
    """이 본문을 쓸 수 있는가. fetch 실패(None)와 너무 짧은 본문을 함께 거른다.

    engine 은 '가져왔는지'만 알려주고(None=실패, ""=빈 본문) 품질은 판단하지 않는다.
    쓸만한지는 정책이라 여기서 본다.
    """
    return bool(body) and len(body) >= MIN_BODY


def format_query(roster: Roster) -> str:
    """검색 질의 → 조회 문서 (t_video.search_query 컬럼 / 덤프 헤더용)."""
    lines = ["[검색 질의] (LLM 생성 → 조회한 문서)"]
    for site in roster.Search_Sites:
        # DDG href 는 공백을 '+' 로 주는데 그대로면 브라우저에서 안 열림 → 실제 조회한 %20 형태로 표시
        dst = site.url.replace("+", "%20") if site.url else "(3회 실패, pass)"
        lines.append(f"- {site.keyword}\n    → {dst}")
    return "\n".join(lines)


def format_dump(roster: Roster) -> str:
    """질의 + 명단을 검수용 텍스트로 (2_roster 덤프)."""
    return f"{format_query(roster)}\n\n[명단]\n{roster.Text or '(명단 없음)'}"
