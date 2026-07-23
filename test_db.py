"""db_svc.save_result 단독 테스트 — STT 를 다시 돌리지 않고 덤프(output/{v_id}/)로 SttInfo 를
조립해 DB 저장만 검증. 사용: python test_db.py [v_id]  (기본 2)

읽는 덤프: 4_hallu.json(kept) · 5_summary.json(segments/overall) · 2_roster.txt(있으면 검색결과).
"""
import json
import sys
from pathlib import Path

from lib.client.rdb import db_svc
from lib.svc.stt.stt_schema import SttInfo

v_id = int(sys.argv[1]) if len(sys.argv) > 1 else 2
out = Path("output") / str(v_id)

hallu = json.loads((out / "4_hallu.json").read_text())
summary = json.loads((out / "5_summary.json").read_text())
roster_f = out / "2_roster.txt"

info = SttInfo(
    v_id=v_id,
    kept=hallu["kept"],
    segments=summary["segments"],
    summary_stt=summary["overall"],
    search_result=roster_f.read_text() if roster_f.exists() else "",
    search_query="",
)

print(f"[test] v_id={v_id}  kept={len(info.kept)}  segments={len(info.segments)}  "
      f"summary_stt={len(info.summary_stt)}자  roster={len(info.search_result)}자")
db_svc.save_result(info)
print("[test] save_result 완료")
