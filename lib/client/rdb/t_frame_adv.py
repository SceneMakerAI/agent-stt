"""t_frame_adv CRUD — 커서를 받아 동작 (connect 는 저장 조합이 관리).

프레임별 분류 결과(야구/광고·투구·보드종류)와 필수항목 개수를 저장. 멱등 저장은 delete_insert() 하나로.

svc 타입을 import 하지 않고 속성만 읽는다(덕타이핑) — video 는 img_detect 의 Video.
  ⚠ 값 -1 은 '안 돌림'이다 (광고 프레임의 pitch 등). 컬럼이 signed 여야 들어간다.
  is_changed / reg_datetime 은 DB 기본값(0 / now)을 쓴다 — 여기서 안 넣는다.
"""
from lib.log import get_logger

log = get_logger(__name__)


def delete(cur, vid: int) -> int:
    """v_id 의 프레임 분류 전체 삭제. 반환: 삭제 행 수."""
    return cur.execute("DELETE FROM t_frame_adv WHERE v_id=%s", (vid,))


def insert(cur, vid: int, video) -> int:
    """Video.FRAME → INSERT. 반환: INSERT 행 수. (삭제는 delete_insert 가 묶는다)"""
    rows = [
        (vid, f.idx, f.idx_time, f.idx_sec,
         f.CLS.normal, f.CLS.pitch, f.CLS.board_type, f.detect_major_obj)
        for f in video.FRAME
    ]
    if rows:
        cur.executemany(
            "INSERT INTO t_frame_adv "
            "(v_id, `idx`, idx_time, idx_sec, `normal`, pitch, board_type, detect_major_obj) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s, %s)",
            rows,
        )
    return len(rows)


def delete_insert(cur, vid: int, video) -> int:
    """멱등 저장 — 지우고 다시 넣는다. 반환: 넣은 행 수 (0 가능).

    실패는 예외로 올린다 — save_svc 의 트랜잭션이 통째 rollback 되고 그 영상은 실패로 남는다.
    저장은 대안이 없어서(부분 저장은 무의미) 호출자가 판단할 게 없다.
    """
    delete(cur, vid)
    return insert(cur, vid, video)
