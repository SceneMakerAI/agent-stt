"""저장 조합 — 트랜잭션을 여는 유일한 곳. 갈래 결과를 한 번에 커밋한다.

save_audio / save_image 는 커서만 받아 자기 테이블에 넣고, 여기서 connect() 로 트랜잭션을
한 번 열어 둘을 묶는다 — 하나라도 실패하면 통째 rollback (대사만 들어가고 프레임·상태가
안 바뀌는 불일치 방지).

status_code 도 여기서 찍는다. '완료'의 기준이 하나여야 다운스트림이 반쯤 처리된 영상을
완료로 보지 않는다 — 갈래가 각자 상태를 건드리면 그 기준이 둘이 된다.
"""
from lib import def_code
from lib.client.rdb import t_video
from lib.client.rdb.rdb import connect
from lib.log import get_logger
from lib.svc.rdb import save_audio, save_image

log = get_logger(__name__)


def save(v_id: int, audio=None, image=None, code: int = def_code.CODE_OK) -> None:
    """갈래 결과를 한 트랜잭션으로 저장하고 상태를 찍는다.

    audio / image 는 None 이면 그 갈래를 안 돌린 것이라 건너뛴다
    (다큐는 image=None, 재처리로 이미지만 돌리면 audio=None).
    """
    with connect() as conn, conn.cursor() as cur:
        n_dlg = save_audio.save(cur, v_id, audio) if audio is not None else 0
        n_frm = save_image.save(cur, v_id, image) if image is not None else 0
        t_video.update_status(cur, v_id, code)
    log.info(f"save_svc: v_id={v_id} dialogue={n_dlg} frame={n_frm} → status={code}")
