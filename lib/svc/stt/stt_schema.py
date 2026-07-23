"""stt 공정의 공유 데이터 객체 — 한 v_id 의 입력 + 단계별 산출물을 담는다.

process.run 이 SttInfo 를 하나 만들어 단계마다 채우고, 저장(db_svc)엔 이 객체 하나만 넘긴다.
(공정이 주고받는 구조를 여기서 고정한다.)

  입력  : v_id / title / category / year   (요청에서)
  산출물: dialogue → 교정 → kept → summary, 그리고 검색(search_result/search_query)
  필드명은 저장 대상 DB 컬럼(t_video 등)과 맞춘다 — db_svc 가 그대로 꺼내 쓴다.
"""
from dataclasses import dataclass


@dataclass
class SttInfo:
    # ── 입력 (요청 SttRequest 에서)
    v_id: int
    title: str = ""
    category: str = ""
    year: int | None = None

    # ── 단계별 산출물 (해당 단계 통과 전에는 None)
    dialogue: list[dict] | None = None       # ① 1차 STT(Qwen) [{idx,start,end,text,lang,speaker}]
    whisper_map: dict[int, str] | None = None  # ② 2차 전사(whisper) {idx: text} — ④ 교정 대조용.
                                             #    비대상(뉴스·다큐)·실패 시 빈 dict → 1차만으로 교정
    kept: list[dict] | None = None           # ⑤ 할루시 필터 통과 (t_dialogue 저장 대상 대사)
    segments: list[dict] | None = None       # ⑥ 구간요약 [{start_sec,end_sec,summary}] (t_dialogue_summary)

    # ── 저장 컬럼 값 (DB 컬럼명과 동일)
    summary_stt: str = ""       # 전체 요약        → t_video.summary_stt
    search_result: str = ""     # 검색 명단        → t_video.search_result
    search_query: str = ""      # 검색 질의(+URL) → t_video.search_query
