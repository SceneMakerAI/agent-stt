"""단계별 중간 결과를 파일로 덤프 (검수용).

⚠ write-only. 단계 간 데이터 전달은 메모리로만 하고, 여기서 쓴 파일은
   다음 단계가 절대 읽지 않는다 (파일 read = 느림 → 금지). 순수 디버깅용.

process() 가 각 단계 끝에서 dump(v_id, step, data) 한 줄로 호출.
config.DUMP_STEPS[step] 가 켜졌을 때만 실제로 쓴다.
"""
import json

import config
from lib.log import get_logger

log = get_logger(__name__)


def dump(v_id: int, step: str, data) -> None:
    """step 결과를 output/{v_id}/ 에 덤프. 플래그 꺼져 있으면 통과.

    문자열 data → {step}.txt 원문 그대로 (긴 증거 텍스트 — json 으로 감싸면 개행이
    escape 돼 한 줄로 읽기 불가). dict/list → {step}.json (indent).
    """
    if not config.DUMP_STEPS.get(step):
        return
    d = config.DEBUG_DIR / str(v_id)
    d.mkdir(parents=True, exist_ok=True)
    if isinstance(data, str):
        path = d / f"{step}.txt"
        path.write_text(data, encoding="utf-8")
    else:
        path = d / f"{step}.json"
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    log.info(f"[dump] {step} → {path}")
