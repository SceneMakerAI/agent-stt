"""t_dialogue CRUD — 커서 + info 받아 동작 (connect 는 db_svc 가 관리).

할루시 필터 통과 대사(info.kept)를 저장. 멱등: DELETE 후 일괄 INSERT.

info 는 SttInfo 를 그대로 받되 import 하지 않고 속성만 읽는다(덕타이핑) — client(rdb)가
svc(SttInfo)에 하드 의존하지 않게. 꺼내 쓰는 것: info.v_id, info.kept.
  kept: [{idx, start, end, speaker, lang, text}, ...]
  매핑: idx/start/end/speaker/lang/text → idx/start_time/end_time/speaker/lang/dialogue.
"""
from lib.log import get_logger
from lib.util import norm_time

log = get_logger(__name__)

def delete(cur, vid: int) -> int:
    """v_id 의 t_dialogue 전체 삭제. 반환: 삭제 행 수."""
    return cur.execute("DELETE FROM t_dialogue WHERE v_id=%s", (vid,))


def insert(cur, info) -> int:
    """info.kept → 멱등 저장 (DELETE 후 INSERT). 반환: INSERT 행 수."""
    vid = info.v_id
    rows = [
        (vid, seg["idx"], norm_time(seg["start"]), norm_time(seg["end"]),
         seg["speaker"], seg["lang"], seg["text"])
        for seg in info.kept or []
    ]
    delete(cur, vid)
    if rows:
        cur.executemany(
            f"INSERT INTO t_dialogue (v_id, idx, start_time, end_time, speaker, lang, dialogue) VALUES (%s, %s, %s, %s, %s, %s, %s)",
            rows,
        )
    return len(rows)
