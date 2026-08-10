"""웹 명단 검색의 LLM 콜 — 질의 생성(②) + 명단 추출(④). 프롬프트도 여기 산다.

vLLM 에 가는 건 이 파일이 전부다. 검색(③)과 흐름은 pipe_search.py.
프롬프트를 따로 빼지 않는 이유 — 프롬프트와 그걸 쓰는 콜은 항상 같이 고치게 된다.
카테고리별 질의 지시(스포츠는 양 팀 따로 / 드라마는 배역)도 QGEN_SYSTEM 안에 있다.

설계 결정(테스트로 검증):
  - 두 콜 다 temperature=0 / enable_thinking=False (재현성 + thinking 오버헤드 제거).
  - 질의 생성만 JSON, **명단 추출은 JSON 미사용(텍스트)** — guided decoding 오버헤드가 없고
    교정 프롬프트에 그대로 실을 수 있다.

vLLM 클라이언트는 외부 주입 (pipe 가 넘긴다).
"""
import json

from lib.client import vllm
from lib.log import get_logger
from lib.svc.audio.search.schema_search import Search_Doc

log = get_logger(__name__)

N_QUERIES = 4          # LLM 이 만들 질의 수
FETCH_MAXLEN = 20000   # 본문 1개당 LLM 에 넣을 최대 길이

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


async def gen_queries(v: vllm.VLLMClient, question: str, year, category: str) -> list[str]:
    """영상 정보 → "site:<도메인> <검색어>" 질의 N_QUERIES 개."""
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


async def extract_roster(v: vllm.VLLMClient, question: str, year, category: str,
                         docs: list[Search_Doc]) -> str:
    """확보한 본문들 → 명단 텍스트. docs 는 pipe_search.fetch() 가 모은 것."""
    joined = "\n\n".join(
        f"### 출처: {d.title} ({d.url})\n{d.content[:FETCH_MAXLEN]}" for d in docs
    )
    ctx = f"영상: {question}" + (f" / 연도 {year}" if year else "") + f" / 카테고리 {category}"
    user = f"{ctx}\n\n아래 본문들에서 명단을 뽑아 지정 형식으로.\n\n{joined}"
    text, ms = await v.chat(
        messages=[{"role": "system", "content": EXTRACT_SYSTEM}, {"role": "user", "content": user}],
        temperature=0, max_tokens=8192, extra_body=THINK_OFF,
    )
    log.info(f"web_search 추출 완료 ({ms}ms): {len(text)}자")
    return text
