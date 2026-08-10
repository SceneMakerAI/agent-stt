"""t_dialogue_summary CRUD — 커서를 받아 동작 (connect 는 저장 조합이 관리).

구간 요약(Summary.sections)을 저장. 멱등 저장은 delete_insert() 하나로.

svc 타입을 import 하지 않고 속성만 읽는다(덕타이핑).
  window_sec 컬럼은 구간 span(end_sec-start_sec)에서 계산한다 — 따로 안 받는다.
"""
from lib.client.rdb.db_util import sec_to_time
from lib.log import get_logger

log = get_logger(__name__)


def delete(cur, vid: int) -> int:
    """v_id 의 구간요약 전체 삭제. 반환: 삭제 행 수."""
    return cur.execute("DELETE FROM t_dialogue_summary WHERE v_id=%s", (vid,))


def insert(cur, vid: int, summary) -> int:
    """Summary.sections → INSERT. 반환: INSERT 행 수."""
    rows = [
        (vid, seq, sec_to_time(s.start_sec), sec_to_time(s.end_sec),
         s.end_sec - s.start_sec, s.summary)
        for seq, s in enumerate(summary.sections)
    ]
    if rows:
        cur.executemany(
            "INSERT INTO t_dialogue_summary "
            "(v_id, seq, start_time, end_time, window_sec, summary) "
            "VALUES (%s, %s, %s, %s, %s, %s)",
            rows,
        )
    return len(rows)


def delete_insert(cur, vid: int, summary) -> int:
    """멱등 저장 — 지우고 다시 넣는다. 반환: 넣은 행 수 (0 가능).

    실패는 예외로 올린다 — save_svc 의 트랜잭션이 통째 rollback 되고 그 영상은 실패로 남는다.
    저장은 대안이 없어서(부분 저장은 무의미) 호출자가 판단할 게 없다.
    """
    delete(cur, vid)
    return insert(cur, vid, summary)
