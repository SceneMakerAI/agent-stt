"""t_video_board CRUD — 커서를 받아 동작 (connect 는 저장 조합이 관리).

영상 하나의 **고정 박스** 7개(kind 별 1행)를 저장. 멱등 저장은 delete_insert() 하나로.
프레임마다 흔들리는 박스를 전 프레임에서 굳힌 값이라, 프레임 테이블이 아니라 영상 단위다.

svc 타입을 import 하지 않고 속성만 읽는다(덕타이핑) — video 는 img_detect 의 Video.
  ⚠ 값 -1 은 '못 굳혔다'는 뜻이라 컬럼이 signed 여야 한다.
"""
from lib.log import get_logger

log = get_logger(__name__)


def delete(cur, vid: int) -> int:
    """v_id 의 고정 박스 전체 삭제. 반환: 삭제 행 수."""
    return cur.execute("DELETE FROM t_video_board WHERE v_id=%s", (vid,))


def insert(cur, vid: int, video) -> int:
    """Video.BOARD_DETECT_ADJUST → INSERT (kind 당 1행). 반환: INSERT 행 수.

    kind 목록은 응답 객체의 필드에서 그대로 뽑는다 — 워커가 항목을 늘려도 따라간다.
    """
    adjust = video.BOARD_DETECT_ADJUST
    rows = [(vid, kind.upper(), b.x, b.y, b.w, b.h)
            for kind in type(adjust).model_fields
            for b in (getattr(adjust, kind),)]
    if rows:
        cur.executemany(
            "INSERT INTO t_video_board (v_id, kind, x, y, w, h) "
            "VALUES (%s, %s, %s, %s, %s, %s)",
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
