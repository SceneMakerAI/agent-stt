"""음성 갈래 저장 — 어느 테이블에 무엇을 넣을지 정한다. 커서를 받는다.

트랜잭션(connect)은 save_svc 가 연다. 여기는 '무엇을 넣을지'만 안다:
  t_dialogue          ← out.dialogue_clean   (할루시 통과 대사)
  t_dialogue_summary  ← out.summary.sections (구간요약. 요약 off 면 0행)
  t_video (UPDATE)    ← out.summary.overall / search_result / search_query

out 은 AudioOut(덕타이핑) — client/rdb 처럼 svc/audio 를 import 하지 않는다.
"""
from lib.client.rdb import t_dialogue, t_dialogue_summary, t_video
from lib.log import get_logger

log = get_logger(__name__)


def save(cur, v_id: int, out) -> int:
    """AudioOut → 테이블 셋. 반환: 저장한 대사 행 수. 실패는 예외로 올라간다.

    구간요약이 0행인 건 정상이다 (스포츠는 요약을 안 함).
    """
    n_dlg = t_dialogue.delete_insert(cur, v_id, out.dialogue_clean)
    n_sum = t_dialogue_summary.delete_insert(cur, v_id, out.summary)
    t_video.update_result(cur, v_id, out.summary.overall,
                          out.search_result, out.search_query)
    log.info(f"save_audio: v_id={v_id} dialogue={n_dlg} summary={n_sum}")
    return n_dlg
