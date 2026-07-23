"""교정 프롬프트 — 공통(모든 카테고리). 카테고리별 용어집은 prompt_<cate>.py 로 분리.

build() 가 [공통 SYSTEM] + [영상 정보] + [참고 용어](카테고리 용어집) + [참고 명단](roster)
를 조립해 vLLM chat messages 를 만든다. 카테고리→용어집 매핑은 glossary_for().

원칙:
  - LLM 에는 메타(타임코드/화자)를 주지 않는다. idx + 본text) 만.
  - 줄 수/순서/idx 를 그대로 유지하도록 강제 → merge 가 idx 로 메타 복원.
  - 출력은 JSON 만. (corrector 가 파싱)
"""

SYSTEM = """너는 한국어 자막(STT 결과) 교정기다. 입력은 음성인식으로 생성돼 오탈자·오인식이 섞여 있다.
각 줄은 'idx: 원문' 이고, 일부 줄 아래에는 같은 오디오를 다른 시스템이 받아쓴 [B] 가 붙는다.

[교정 절차 — 반드시 이 순서로]
1) 초안 결합 — 원문은 **내용의 범위**를, [B] 는 **표현의 정확도**를 담당한다.
   - 원문에 있고 [B] 에 없는 내용은 반드시 살린다. [B] 가 짧다고 그 부분을 버리지 마라.
   - 같은 내용을 둘이 다르게 적었으면, [B] 쪽이 문맥상 자연스러우면 그것을 쓴다.
   - 이어붙이지 말고, 결합한 결과가 **하나의 자연스러운 문장**이 되게 다듬어라.
   - [B] 에만 있고 원문에 없는 말(앞뒤 구간에서 흘러든 말)은 넣지 마라.
2) 이름·자리 확인 — 사람 이름은 [참고 명단] 표기를 따른다.
   - **[B] 의 이름 표기도 신뢰할 수 있다.** 원문과 [B] 가 다르면 명단에 있는 쪽을 쓴다.
     둘 다 명단에 있으면 [B] 를 따른다. 명단에 없는 이름을 지어내지 않는다.
   - **서술어(동사·형용사) 자리에 [참고 명단]·[참고 용어] 의 명사가 들어가 있으면 그건 오인식이다.**
     그 명사를 지키지 말고, 발음이 비슷하면서 문맥에 맞는 말로 고쳐라.
     (예: "주심할 필요가 있다" — 주심은 심판을 뜻하는 명사라 서술어 자리에 올 수 없다 → 오인식)
3) 용어집 적용 — [참고 용어] 의 말이 발음만 비슷하게 잘못 적혔으면 그 표기로 바로잡는다.
   단 2에서 서술어 자리로 판정한 곳은 건드리지 않는다.
4) 표기 정리 — 남은 오탈자·맞춤법·띄어쓰기, 깨진 글자(예: 헌�법 → 헌법)를 고친다.

[지킬 것]
- 원래 의미와 말투를 보존. 내용을 새로 만들거나 요약/번역하지 않는다.
- 입력 줄 수와 순서를 그대로 유지. 줄을 합치거나 나누지 않는다.
- 각 줄의 idx 를 그대로 돌려준다.
- 고칠 게 없으면 원문 그대로 둔다.

[출력]
- 오직 JSON 만 출력. 형식: {"lines": [{"idx": <정수>, "text": "<교정된 본문>"}, ...]}
- lines 의 개수와 idx 는 입력과 정확히 일치해야 한다."""


ROSTER_GUIDE = """[참고 명단]
아래는 이 영상의 등장인물/선수 명단이다. 자막에 인물·선수 이름이 음성인식으로 잘못
적혔으면(비슷한 발음의 다른 표기) 이 명단의 정확한 이름으로 바로잡아라.
- 명단에 없는 이름을 새로 지어내지 마라.
- 이름이 아닌 일반 대사는 명단과 무관하니 평소대로 교정한다.

{roster}"""


# [B] 대조 규칙은 SYSTEM 의 [교정 절차] 1)2) 에 통합됐다 (별도 블록이던 WHISPER_GUIDE 제거).
# v1 GT 실측으로 바뀐 두 가지 — 각각 +4, +5 (합계 32→43/64):
#   · 이름 잠금 해제 : whisper 에 등장인물 프롬프트를 넣은 뒤로 [B] 의 이름이 정확해졌다.
#                    (정근호→정근우, 구톰순→구톰슨) 옛 규칙 "이름은 [B] 를 믿지 마라"는
#                    이제 정확한 정보를 버리게 만들어 손해였다.
#   · 고르기→결합   : 어느 한쪽을 '택하게' 하면, A 기준이면 오인식이 남고 B 기준이면 말이 잘렸다.
#                    A 를 내용 범위, B 를 표현 정확도로 나눠 '결합'시키니 둘 다 잡혔다.
# 규칙을 더 넣으면 그만큼 교정을 덜 한다(제동 1개당 GT −5 실측) → 절차는 이 4단계로 유지할 것.


def glossary_for(category: str) -> str:
    """카테고리 → 용어집 텍스트 (없으면 ""). 카테고리별 prompt_<cate>.py 에서 가져온다.

    지연 import — 순환 없이 카테고리 모듈만 필요할 때 로드. 새 카테고리는 여기 분기 추가.
    """
    if category and category.startswith("스포츠"):
        from lib.svc.stt.correct import prompt_sports
        return prompt_sports.glossary(category)   # 종목(야구/축구/농구)별 분기
    return ""


def _video_info(req) -> str:
    """req(영상 정보)에서 제목/카테고리/방송연도 컨텍스트 블록 (없으면 "")."""
    if req is None:
        return ""
    info = []
    if getattr(req, "title", ""):
        info.append(f"제목: {req.title}")
    if getattr(req, "category", ""):
        info.append(f"카테고리: {req.category}")
    if getattr(req, "year", None):
        info.append(f"방송연도: {req.year}")
    return "[영상 정보]\n" + "\n".join(info) if info else ""


def build(page: list[dict], roster: str = "", req=None,
          whisper_map: dict[int, str] | None = None) -> list[dict]:
    """페이지(segment dict 리스트) → chat messages. text 와 idx 만 노출.

    req(영상 정보)·카테고리 용어집·roster(명단)가 있으면 교정 참고자료로 system 에 덧붙인다.
    whisper_map 이 있으면 해당 idx 줄에 2차 전사를 [B] 로 병기한다 (대조 규칙은 SYSTEM 에 상주).
    (없는 섹션은 자동 생략 → 기존 동작 그대로)
    """
    whisper_map = whisper_map or {}
    parts = [SYSTEM]
    info = _video_info(req)
    if info:
        parts.append(info)
    glossary = glossary_for(getattr(req, "category", "") if req is not None else "")
    if glossary.strip():
        parts.append(glossary.strip())
    if roster.strip():
        parts.append(ROSTER_GUIDE.format(roster=roster.strip()))
    system = "\n\n".join(parts)

    lines = []
    for seg in page:
        lines.append(f'{seg["idx"]}: {seg["text"]}')
        b = whisper_map.get(seg["idx"], "").strip()
        if b:
            lines.append(f'    [B] {b}')
    body = "\n".join(lines)
    user = f"다음 자막을 교정해서 JSON 으로 반환해.\n\n{body}"
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]
