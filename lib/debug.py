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
    """step 결과를 output/{v_id}/{step}.json 으로 덤프. 플래그 꺼져 있으면 통과."""
    if not config.DUMP_STEPS.get(step):
        return
    d = config.DEBUG_DIR / str(v_id)
    d.mkdir(parents=True, exist_ok=True)
    path = d / f"{step}.json"
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    log.info(f"[dump] {step} → {path}")
