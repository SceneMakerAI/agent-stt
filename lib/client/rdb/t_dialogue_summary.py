"""t_dialogue_summary CRUD — 커서 + info 받아 동작 (connect 는 db_svc 가 관리).

1분 구간 요약(summarizer 산출물)을 저장. 멱등: DELETE 후 일괄 INSERT.

info 는 SttInfo 를 그대로 받되 import 하지 않고 속성만 읽는다(덕타이핑) — client(rdb)가
svc(SttInfo)에 하드 의존하지 않게. 꺼내 쓰는 것: info.v_id, info.segments.
  segments: [{start_sec, end_sec, summary}, ...]  (summarizer 산출물)
  window_sec 는 구간 span(end_sec-start_sec)에서 계산.
"""
from lib.client.rdb.db_util import sec_to_time
from lib.log import get_logger

log = get_logger(__name__)


def delete(cur, vid: int) -> int:
    """v_id 의 구간요약 전체 삭제. 반환: 삭제 행 수."""
    return cur.execute("DELETE FROM t_dialogue_summary WHERE v_id=%s", (vid,))


def insert(cur, info) -> int:
    """info.segments → 멱등 저장 (DELETE 후 INSERT). 반환: INSERT 행 수."""
    vid = info.v_id
    rows = [
        (vid, seq, sec_to_time(s["start_sec"]), sec_to_time(s["end_sec"]),
         s["end_sec"] - s["start_sec"], s.get("summary") or "")
        for seq, s in enumerate(info.segments or [])
    ]
    delete(cur, vid)
    if rows:
        cur.executemany(
            f"INSERT INTO t_dialogue_summary (v_id, seq, start_time, end_time, window_sec, summary) VALUES (%s, %s, %s, %s, %s, %s)",
            rows,
        )
    return len(rows)
