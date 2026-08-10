"""t_dialogue CRUD — 커서를 받아 동작 (connect 는 저장 조합이 관리).

할루시 필터를 통과한 대사(Dialogues)를 저장. 멱등 저장은 delete_insert() 하나로.

svc 타입을 import 하지 않고 속성만 읽는다(덕타이핑).
  매핑: idx/start_time/end_time/speaker/lang/text
        → idx/start_time/end_time/speaker/lang/dialogue

시각은 이미 정규화돼 있다 (pipe_stt_qwen 이 SS 를 0~59 로 보정) — 여기선 안 건드린다.
"""
from lib.log import get_logger

log = get_logger(__name__)


def delete(cur, vid: int) -> int:
    """v_id 의 대사 전체 삭제. 반환: 삭제 행 수."""
    return cur.execute("DELETE FROM t_dialogue WHERE v_id=%s", (vid,))


def insert(cur, vid: int, dialogues) -> int:
    """Dialogues → INSERT. 반환: INSERT 행 수. (삭제는 안 한다 — delete_insert 가 묶는다)"""
    rows = [
        (vid, d.idx, d.start_time, d.end_time, d.speaker, d.lang, d.text)
        for d in dialogues.items
    ]
    if rows:
        cur.executemany(
            "INSERT INTO t_dialogue (v_id, idx, start_time, end_time, speaker, lang, dialogue) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s)",
            rows,
        )
    return len(rows)


def delete_insert(cur, vid: int, dialogues) -> int:
    """멱등 저장 — 지우고 다시 넣는다. 반환: 넣은 행 수 (0 가능).

    실패는 예외로 올린다 — save_svc 의 트랜잭션이 통째 rollback 되고 그 영상은 실패로 남는다.
    저장은 대안이 없어서(부분 저장은 무의미) 호출자가 판단할 게 없다.
    """
    delete(cur, vid)
    return insert(cur, vid, dialogues)
