"""t_frame_baseball_board_detail CRUD — 커서를 받아 동작 (connect 는 저장 조합이 관리).

프레임 하나당 보드 세부 항목 6개(kind 별 1행)를 저장. 멱등 저장은 delete_insert() 하나로.
프레임 7천 장이면 4만 행이라 CHUNK 씩 나눠 넣는다.

svc 타입을 import 하지 않고 속성만 읽는다(덕타이핑) — video 는 img_detect 의 Video.
  못 찾은 항목도 detect=0 으로 넣는다 — 빼면 '검출 실패'와 '안 돌림'이 구분되지 않는다.
  txt(OCR 자리) / reg_datetime 은 DB 기본값('' / now)을 쓴다.
"""
from lib.log import get_logger

log = get_logger(__name__)

# 보드 세부 항목. 모델·응답은 소문자, DB kind 컬럼은 대문자.
KINDS = ("team", "inning", "count", "out", "base", "etc")

CHUNK = 5000   # executemany 한 번에 보낼 행 수 (패킷 크기 보호)


def delete(cur, vid: int) -> int:
    """v_id 의 보드 세부 전체 삭제. 반환: 삭제 행 수."""
    return cur.execute("DELETE FROM t_frame_baseball_board_detail WHERE v_id=%s", (vid,))


def insert(cur, vid: int, video) -> int:
    """Video.FRAME 의 BOARD_DETAIL_DETECT → 멱등 저장 (프레임당 6행). 반환: INSERT 행 수."""
    rows = []
    for f in video.FRAME:
        for kind in KINDS:
            d = getattr(f.BOARD_DETAIL_DETECT, kind)
            rows.append((vid, f.idx, kind.upper(), f.idx_time, f.idx_sec,
                         d.detect, d.score, d.x, d.y, d.w, d.h))
    sql = ("INSERT INTO t_frame_baseball_board_detail "
           "(v_id, `idx`, kind, idx_time, idx_sec, detect, score, x, y, w, h) "
           "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)")
    for i in range(0, len(rows), CHUNK):
        cur.executemany(sql, rows[i:i + CHUNK])
    return len(rows)


def delete_insert(cur, vid: int, video) -> int:
    """멱등 저장 — 지우고 다시 넣는다. 반환: 넣은 행 수 (0 가능).

    실패는 예외로 올린다 — save_svc 의 트랜잭션이 통째 rollback 되고 그 영상은 실패로 남는다.
    저장은 대안이 없어서(부분 저장은 무의미) 호출자가 판단할 게 없다.
    """
    delete(cur, vid)
    return insert(cur, vid, video)
