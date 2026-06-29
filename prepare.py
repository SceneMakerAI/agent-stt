"""자막 파일 → 'LLM 교정 호출 직전 상태' 로 변환해 output/ 에 저장.

아직 LLM 은 부르지 않는다. 라인을 파싱해서
  - 메타(타임코드·화자·언어) 는 코드가 보관  (교정 후 재결합용, LLM 엔 안 줌)
  - 본문만 인덱스를 붙여 따로 추출            (LLM 에 보낼 것)
두 가지를 만들어 저장한다 → 보내기 전 눈으로 검수하는 용도.

실행:  uv run python prepare.py            # 기본 news.txt
       uv run python prepare.py drama     # input/drama.txt
"""
import json
import re
import sys
from pathlib import Path

# 라인 포맷: [HH:MM:SS.s~HH:MM:SS.s][화자][언어]본문
LINE_RE = re.compile(r"^\[([^~\]]+)~([^\]]+)\]\[([^\]]+)\]\[([^\]]+)\](.*)$")

INPUT_DIR = Path("input")
OUTPUT_DIR = Path("output")


def parse(text: str) -> list[dict]:
    """자막 텍스트 → 라인별 dict 리스트. 포맷 안 맞는 줄은 건너뛴다."""
    lines = []
    for n, raw in enumerate(text.splitlines(), start=1):
        raw = raw.strip()
        if not raw:
            continue
        m = LINE_RE.match(raw)
        if not m:
            print(f"  [skip] line {n}: 포맷 불일치 → {raw[:40]!r}")
            continue
        start, end, speaker, lang, body = m.groups()
        lines.append({
            "i": len(lines),          # 0-based 인덱스 (재결합 키)
            "start": start,
            "end": end,
            "speaker": speaker,
            "lang": lang,
            "text": body.strip(),
        })
    return lines


def main() -> None:
    name = sys.argv[1] if len(sys.argv) > 1 else "news"
    name = name.removesuffix(".txt")

    src = INPUT_DIR / f"{name}.txt"
    raw = src.read_text(encoding="utf-8")
    lines = parse(raw)
    print(f"parsed: {len(lines)} lines  ←  {src}")

    OUTPUT_DIR.mkdir(exist_ok=True)

    # 1) 전체 state — 메타 포함. 교정 결과를 i 로 다시 붙일 때 쓴다.
    state_path = OUTPUT_DIR / f"{name}.state.json"
    state = {"source": str(src), "num_lines": len(lines), "lines": lines}
    state_path.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"saved state      → {state_path}")

    # 2) LLM 입력 — 모델이 보는 것. 메타 없이 'i: 본문' 만. (타임코드/화자 미노출)
    llm_input = "\n".join(f"{ln['i']}: {ln['text']}" for ln in lines)
    llm_path = OUTPUT_DIR / f"{name}.llm_input.txt"
    llm_path.write_text(llm_input, encoding="utf-8")
    print(f"saved llm input  → {llm_path}")

    # 미리보기
    print("\n── LLM 에 보낼 내용 (앞 5줄) ──")
    for ln in lines[:5]:
        print(f"{ln['i']}: {ln['text']}")


if __name__ == "__main__":
    main()
