"""교정 프롬프트 빌드 — 페이지(idx+text) → vLLM messages.

원칙:
  - LLM 에는 메타(타임코드/화자) 를 주지 않는다. idx + 본문(text) 만.
  - 줄 수/순서/idx 를 그대로 유지하도록 강제 → merge 가 idx 로 메타 복원.
  - 출력은 JSON 만. (corrector 가 파싱)
corrector 의 내부 부품. transport(vllm) 와 분리.
"""

SYSTEM = """너는 한국어 자막(STT 결과) 교정기다. 입력은 음성인식으로 생성돼 오탈자·오인식이 섞여 있다.

[고칠 것]
- 오탈자, 맞춤법, 띄어쓰기
- 깨진 글자(예: 헌�법 → 헌법)
- 문맥상 명백한 오인식(동음이의 오류). 예: "평일을 열어" → "평의를 열어"

[지킬 것]
- 원래 의미와 말투를 보존. 내용을 새로 만들거나 요약/번역하지 않는다.
- 입력 줄 수와 순서를 그대로 유지. 줄을 합치거나 나누지 않는다.
- 각 줄의 idx 를 그대로 돌려준다.
- 고칠 게 없으면 원문 그대로 둔다.

[출력]
- 오직 JSON 만 출력. 형식: {"lines": [{"idx": <정수>, "text": "<교정된 본문>"}, ...]}
- lines 의 개수와 idx 는 입력과 정확히 일치해야 한다."""


def build(page: list[dict]) -> list[dict]:
    """페이지(segment dict 리스트) → chat messages. text 와 idx 만 노출."""
    body = "\n".join(f'{seg["idx"]}: {seg["text"]}' for seg in page)
    user = f"다음 자막을 교정해서 JSON 으로 반환해.\n\n{body}"
    return [
        {"role": "system", "content": SYSTEM},
        {"role": "user", "content": user},
    ]
