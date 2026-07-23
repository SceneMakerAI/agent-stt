"""할루시 필터(2단 LLM) 검증 — output/{v_id}/correct.json → filter → hallucination.json.

실행:  uv run python test_hallu.py [v_id]   (기본 2)
"""
import asyncio
import json
import ssl
import sys
from pathlib import Path

from lib.client import vllm
from lib.svc.stt.hallucination import filter as hallu

VID = sys.argv[1] if len(sys.argv) > 1 else "2"


async def main():
    ssl.create_default_context()
    segments = json.loads(Path(f"output/{VID}/correct.json").read_text(encoding="utf-8"))
    v = vllm.build()
    try:
        rep = await hallu.run(v, segments)
    finally:
        await v.close()

    out = Path(f"output/{VID}/hallucination.json")
    out.write_text(json.dumps(rep, ensure_ascii=False, indent=2), encoding="utf-8")

    id2 = {s["idx"]: s for s in segments}
    print(f"입력 {len(segments)}줄 / 주언어 = {rep['main_lang']}")
    print(f"\n■ drop({len(rep['dropped'])}줄):")
    for s in rep["dropped"]:
        print(f"   [{s['idx']}] {s['lang']} | {s['text']!r}")
    relang = [i for i, v in rep["verdicts"].items() if v == "relang"]
    print(f"\n■ relang({len(relang)}줄, 태그교정):")
    for i in relang:
        print(f"   [{i}] {id2[i]['lang']}→{rep['main_lang']} | {id2[i]['text']!r}")
    keep = [i for i, vv in rep["verdicts"].items() if vv == "keep"]
    print(f"\n■ keep(외국어 유지): {len(keep)}줄")
    print(f"■ kept 최종(reindex): {len(rep['kept'])}줄 → {out}")


if __name__ == "__main__":
    asyncio.run(main())
