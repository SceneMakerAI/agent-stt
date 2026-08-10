"""웹 명단 검색 산출물 — 값만 담는다. 함수는 두지 않는다.

만드는 쪽은 pipe_search. 읽는 쪽은 교정(명단)과 저장(t_video), 그리고 검수 덤프다.
"""
from dataclasses import dataclass, field


@dataclass
class Search_Doc:
    """본문까지 확보한 문서 하나 — 명단의 출처이자 LLM 추출의 입력.

    Search_Site 에 본문(content)이 더해진 것이다. 본문을 못 받으면 이건 안 만들어진다.
    """
    keyword: str = ""     # 이 문서를 찾아낸 검색 질의
    url: str = ""
    title: str = ""
    content: str = ""     # 본문 전문 (검색 스니펫이 아니라 실제 문서. 수만 자)


@dataclass
class Search_Site:
    """질의 하나가 어느 문서로 이어졌는지 — 무엇을 보고 뽑았나의 기록.

    url 이 비어 있으면 그 질의는 문서를 못 구했다는 뜻이다.
    """
    keyword: str = ""     # 검색에 쓴 질의
    url: str = ""
    title: str = ""


@dataclass
class Roster:
    """영상 하나의 명단 검색 결과."""
    Text: str = ""      # 명단 텍스트 (교정 입력) → t_video.search_result. 확보 문서 0이면 ""
    LLM_Search_Keywords: list[str] = field(default_factory=list)   # LLM 이 만든 검색 질의들
    Search_Sites: list[Search_Site] = field(default_factory=list)   # 질의별 결과 → t_video.search_query
