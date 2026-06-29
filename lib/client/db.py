"""MariaDB 저장 (⑤) — t_video 상태 갱신 + t_dialogue 자막 INSERT.

이 모듈은 'DB 에 어떻게 쓰는지'만 안다 (스키마를 아는 repository 계층).
호출 시점/순서는 main 의 process() 책임 — 여기선 함수만 제공한다 (아직 미연결).

설계:
  - 연결은 작업마다 새로 연다 (with connect()). STT 가 5~10분 블로킹하는 동안 커넥션을
    들고 있으면 wait_timeout 으로 끊기므로, 호출 시점마다 짧게 열고 닫는다.
  - with 블록 정상 종료 → commit, 예외 → rollback, 항상 close.
"""
from contextlib import contextmanager

import pymysql
from pymysql.constants import CLIENT

import config
from lib.log import get_logger

log = get_logger(__name__)

DIALOGUE_MAXLEN = 200   # t_dialogue.dialogue 가 varchar(200) — 초과분은 잘라서 저장


@contextmanager
def connect():
    """pymysql 연결 context manager. 정상 종료 시 commit, 예외 시 rollback, 항상 close."""
    conn = pymysql.connect(
        host=config.RDB_HOST,
        port=config.RDB_PORT,
        user=config.RDB_USER,
        password=config.RDB_PW,
        database=config.RDB_NAME,
        charset="utf8mb4",
        autocommit=False,
        client_flag=CLIENT.FOUND_ROWS,   # UPDATE affected = 매칭 행 수 (값 변경 없어도 카운트)
    )
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def _norm_time(t: str) -> str:
    """'HH:MM:SS.s' 정규화 — model_svc 반올림으로 SS=60 이 나오는 경우(예 '01:39:60.0')를 보정.

    model_svc 의 _fmt_time 이 s=59.96 을 '60.0' 으로 반올림해 MariaDB TIME 이 거부함.
    문자열 → 0.1초 단위 정수로 환산 후 자리올림하여 SS 를 0~59 로 강제 (포맷 반올림도 차단).
    """
    h, m, s = t.split(":")
    tenths = round((int(h) * 3600 + int(m) * 60 + float(s)) * 10)  # 총 0.1초
    ss = tenths % 600          # 분 내 0.1초 (0~599)
    mm = tenths // 600 % 60
    hh = tenths // 36000
    return f"{hh:02d}:{mm:02d}:{ss // 10:02d}.{ss % 10:d}"


# ── 저수준 연산 — 커서를 받아 동작 (트랜잭션 합성용). 커밋/롤백은 호출자(connect) 책임.
def _update_status(cur, vid: int, code: int) -> int:
    """t_video.status_code 갱신. 반환: 영향받은 행 수."""
    return cur.execute("UPDATE t_video SET status_code=%s WHERE v_id=%s", (code, vid))


def _insert_dialogues(cur, vid: int, segments: list[dict]) -> int:
    """t_dialogue 멱등 저장 — 기존 vid 행 DELETE 후 일괄 INSERT. 반환: INSERT 행 수.

    매핑: idx/start/end/speaker/lang/text → idx/start_time/end_time/speaker/lang/dialogue.
    dialogue 는 varchar(200) 이라 초과분은 잘라 저장 (자막 한 줄도 빠지지 않게: truncate > drop).
    """
    rows = []
    for seg in segments:
        text = seg["text"]
        if len(text) > DIALOGUE_MAXLEN:
            log.warning(f"dialogue truncate: vid={vid} idx={seg['idx']} {len(text)}→{DIALOGUE_MAXLEN}")
            text = text[:DIALOGUE_MAXLEN]
        rows.append((vid, seg["idx"], _norm_time(seg["start"]), _norm_time(seg["end"]),
                     seg["speaker"], seg["lang"], text))

    cur.execute("DELETE FROM t_dialogue WHERE v_id=%s", (vid,))
    if rows:
        cur.executemany(
            "INSERT INTO t_dialogue "
            "(v_id, `idx`, start_time, end_time, speaker, lang, dialogue) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s)",
            rows,
        )
    return len(rows)


# ── 공개 API ──────────────────────────────────────────────────────────────
def set_status(vid: int, code: int) -> int:
    """t_video.status_code 만 단독 갱신 (예: 1005 처리시작 표시). 단독 트랜잭션.

    반환: 영향받은 행 수. 0 이면 해당 v_id 가 t_video 에 없다는 뜻.
    """
    with connect() as conn, conn.cursor() as cur:
        n = _update_status(cur, vid, code)
    log.info(f"t_video status: vid={vid} → {code} (rows={n})")
    return n


def save_result(vid: int, segments: list[dict], code: int) -> int:
    """t_dialogue INSERT + t_video.status_code 갱신을 '한 트랜잭션'으로 (원자적).

    둘 중 하나라도 실패하면 connect() 가 통째 rollback → 자막만 들어가고 status 안 바뀌는
    불일치를 막는다. 반환: 저장한 대사 행 수.
    """
    with connect() as conn, conn.cursor() as cur:
        n = _insert_dialogues(cur, vid, segments)
        _update_status(cur, vid, code)
    log.info(f"t_dialogue saved + status: vid={vid} rows={n} → {code}")
    return n
