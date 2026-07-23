"""t_video CRUD — 커서 + info 받아 동작 (connect 는 db_svc 가 관리).

t_video 는 이미 행이 존재하므로 INSERT 가 아니라 UPDATE — STT 산출물 컬럼만 채운다.
status 는 단독 갱신(set_status)도 있으니 여기선 결과 저장 전용.

info 는 SttInfo 를 그대로 받되 import 하지 않고 속성만 읽는다(덕타이핑) — client(rdb)가
svc(SttInfo)에 하드 의존하지 않게. 꺼내 쓰는 것:
  info.v_id, info.summary_stt, info.search_result, info.search_query.
"""
from lib.client.rdb.rdb import connect
from lib.log import get_logger

log = get_logger(__name__)


def update_status(cur, vid: int, code: int) -> int:
    """t_video.status_code 만 단독 갱신 (커서 받음 — 트랜잭션 조합용). 반환: 영향 행 수."""
    return cur.execute("UPDATE t_video SET status_code=%s WHERE v_id=%s", (code, vid))


def set_status(vid: int, code: int) -> int:
    """status_code 갱신을 단독 트랜잭션으로 (핸들러가 바로 호출 — 접수 1001, 처리시작 1005 등).

    반환: 영향받은 행 수. 0 이면 해당 v_id 가 t_video 에 없다는 뜻.
    """
    with connect() as conn, conn.cursor() as cur:
        n = update_status(cur, vid, code)
    log.info(f"t_video status: vid={vid} → {code} (rows={n})")
    return n


def update_result(cur, info, code: int) -> int:
    """STT 산출물(요약·검색) + status_code 를 t_video 에 반영. 반환: 영향받은 행 수."""
    return cur.execute(
        "UPDATE t_video SET summary_stt=%s, search_result=%s, search_query=%s, status_code=%s "
        "WHERE v_id=%s",
        (info.summary_stt, info.search_result, info.search_query, code, info.v_id),
    )
