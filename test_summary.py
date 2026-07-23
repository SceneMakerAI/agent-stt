"""요약(refine) 검증 — output/{v_id}/hallucination.json 의 kept → summarize → summary.json.

실행:  uv run python test_summary.py [v_id] [window_sec]
       예)  uv run python test_summary.py 2 300
"""
import asyncio
import json
import ssl
import sys
from pathlib import Path

from lib.client import vllm
from lib.svc.stt.summary import summarizer

VID = sys.argv[1] if len(sys.argv) > 1 else "2"
WINDOW = int(sys.argv[2]) if len(sys.argv) > 2 else None


async def main():
    ssl.create_default_context()
    # 할루시 필터 통과본(kept)이 있으면 그걸, 없으면 correct.json 을 입력으로
    hpath = Path(f"output/{VID}/hallucination.json")
    if hpath.exists():
        segments = json.loads(hpath.read_text(encoding="utf-8"))["kept"]
    else:
        segments = json.loads(Path(f"output/{VID}/correct.json").read_text(encoding="utf-8"))

    v = vllm.build()
    try:
        res = await summarizer.summarize(v, segments, window_sec=WINDOW)
    finally:
        await v.close()

    out = Path(f"output/{VID}/summary.json")
    out.write_text(json.dumps(res, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"입력 {len(segments)}줄 / window={res['window_sec']}초 / 구간 {len(res['segments'])}개\n")
    for s in res["segments"]:
        mm = f"{s['start_sec']//60}~{s['end_sec']//60}분"
        print(f"■ [{mm}] {s['summary']}")
    print(f"\n★ 전체 summary:\n{res['overall']}")
    print(f"\n→ {out}")


if __name__ == "__main__":
    asyncio.run(main())
