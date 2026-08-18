"""t_video CRUD — 커서를 받아 동작 (connect 는 저장 조합이 관리).

t_video 는 이미 행이 존재하므로 INSERT 가 아니라 UPDATE — STT 산출물 컬럼만 채운다.
status 는 단독 갱신(set_status)도 있으니 여기선 결과 저장 전용.

산출물 객체가 아니라 값을 받는다 — client(rdb)가 svc 타입에 하드 의존하지 않게.
꺼낼 것을 고르는 건 저장 조합(svc/rdb/save_audio)의 몫이다.
"""
from lib.client.rdb.rdb import connect
from lib.log import get_logger

log = get_logger(__name__)


def update_status(cur, vid: int, code: int) -> int:
    """t_video.status_code 만 단독 갱신 (커서 받음 — 트랜잭션 조합용). 반환: 영향 행 수."""
    return cur.execute("UPDATE t_video SET status_code=%s WHERE v_id=%s", (code, vid))


def set_status(vid: int, code: int) -> int:
    """status_code 갱신을 단독 트랜잭션으로 (공정이 단계마다 호출).

    반환: 영향받은 행 수. 0 이면 해당 v_id 가 t_video 에 없다는 뜻.
    """
    with connect() as conn, conn.cursor() as cur:
        n = update_status(cur, vid, code)
    log.info(f"t_video status: vid={vid} → {code} (rows={n})")
    return n


def update_result(cur, vid: int, summary_stt: str, search_result: str,
                  search_query: str) -> int:
    """음성 산출물(요약·검색)을 t_video 에 반영. 반환: 영향받은 행 수.

    status_code 는 여기서 안 건드린다 — '완료' 판정은 갈래가 아니라 저장 조합(save_svc)의 몫.
    """
    return cur.execute(
        "UPDATE t_video SET summary_stt=%s, search_result=%s, search_query=%s WHERE v_id=%s",
        (summary_stt, search_result, search_query, vid),
    )
