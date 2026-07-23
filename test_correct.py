"""교정 프롬프트 단독 재교정 테스트 — 새 프롬프트가 비문(B)을 잡는지 before/after 비교.
사용: python test_correct.py [v_id] [page_segments]  (기본 v_id=1, 앞 15줄)

원본(1_stt.json) 앞부분만 corrector.correct 로 재교정해 원본·기존교정(3_correct.json)·신규 비교.
"""
import asyncio
import json
import ssl
import sys
from pathlib import Path
from types import SimpleNamespace

from lib.client import vllm as vllm_mod
from lib.svc.stt.correct import corrector

v_id = int(sys.argv[1]) if len(sys.argv) > 1 else 1
n = int(sys.argv[2]) if len(sys.argv) > 2 else 15
out = Path("output") / str(v_id)

stt = json.loads((out / "1_stt.json").read_text())
stt = stt if isinstance(stt, list) else stt.get("segments", stt)
old = {s["idx"]: s["text"] for s in json.loads((out / "3_correct.json").read_text())}
roster_f = out / "2_roster.txt"
roster = roster_f.read_text() if roster_f.exists() else ""

page = stt[:n]
req = SimpleNamespace(title="코리안시리즈 KIA vs SK", category="스포츠-야구", year=2009)


async def main():
    ssl.create_default_context()   # main.py 와 동일 워크어라운드
    vllm = vllm_mod.build()
    try:
        fixed = await corrector.correct(vllm, page, roster, req)
    finally:
        await vllm.close()

    for s in fixed:
        i = s["idx"]
        o = next(x["text"] for x in page if x["idx"] == i)
        print(f"\n── idx {i}")
        print(f"  원본 : {o}")
        print(f"  기존 : {old.get(i, '(없음)')}")
        print(f"  신규 : {s['text']}")


asyncio.run(main())
