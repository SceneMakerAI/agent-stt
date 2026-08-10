"""t_frame_board CRUD — 커서를 받아 동작 (connect 는 저장 조합이 관리).

프레임별 스코어보드 박스 하나를 저장. 멱등 저장은 delete_insert() 하나로.

svc 타입을 import 하지 않고 속성만 읽는다(덕타이핑) — video 는 img_detect 의 Video.
  ⚠ 보드 유무 판단은 board(0/1)로 한다. 좌표로 판단하지 말 것.
"""
from lib.log import get_logger

log = get_logger(__name__)


def delete(cur, vid: int) -> int:
    """v_id 의 보드 박스 전체 삭제. 반환: 삭제 행 수."""
    return cur.execute("DELETE FROM t_frame_board WHERE v_id=%s", (vid,))


def insert(cur, vid: int, video) -> int:
    """Video.FRAME 의 BOARD_DETECT → 멱등 저장. 반환: INSERT 행 수."""
    rows = [
        (vid, f.idx, f.idx_time, f.idx_sec,
         f.BOARD_DETECT.board, f.BOARD_DETECT.score,
         f.BOARD_DETECT.x, f.BOARD_DETECT.y, f.BOARD_DETECT.w, f.BOARD_DETECT.h)
        for f in video.FRAME
    ]
    if rows:
        cur.executemany(
            "INSERT INTO t_frame_board "
            "(v_id, `idx`, idx_time, idx_sec, board, score, x, y, w, h) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
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
