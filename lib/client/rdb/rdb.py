"""MariaDB 공용 — connect() (트랜잭션 경계) 하나만.

  connect : 테이블 파일(t_*)과 저장 조합(svc/rdb)이 트랜잭션을 열 때 쓰는 공용 유틸.

설계:
  - 연결은 작업마다 새로 연다 (with connect()). STT 가 5~10분 블로킹하는 동안 커넥션을
    들고 있으면 wait_timeout 으로 끊기므로, 호출 시점마다 짧게 열고 닫는다.
  - with 블록 정상 종료 → commit, 예외 → rollback, 항상 close.

테이블별 CRUD 는 t_*.py(커서 받음), 트랜잭션 조합은 svc/rdb(connect 소유).
cast(2차 보정) 전용 조회/저장은 CAST.md 참고 — 재도입 시 svc/rdb 패턴으로.
"""
from contextlib import contextmanager

import pymysql
from pymysql.constants import CLIENT

import config
from lib.log import get_logger

log = get_logger(__name__)


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
        # 롤백이 조용히 일어나면 안 된다. 무엇이 왜 실패했는지(v_id·단계)는 바로 뒤 상위
        # 로그에 찍히므로, 여기선 '되돌렸다'는 사실만 남기고 예외는 그대로 올린다.
        log.error("트랜잭션 rollback")
        raise
    finally:
        conn.close()
