"""db_svc — STT 1차 공정 저장의 트랜잭션 조합. 외부는 save_result(info) 하나만 호출.

테이블별 파일(t_dialogue/t_dialogue_summary/t_video)은 커서만 받아 CRUD 하고, 여기서
connect() 로 트랜잭션을 한 번 열어 셋을 묶는다 — 하나라도 실패하면 통째 rollback
(대사만 들어가고 요약·상태가 안 바뀌는 불일치 방지).

info 는 SttInfo(덕타이핑) — 각 테이블 함수가 필요한 필드만 꺼내 쓴다.
"""
from lib.client.rdb import t_dialogue, t_dialogue_summary, t_video
from lib.client.rdb.rdb import connect
from lib.log import get_logger

log = get_logger(__name__)

STT_END = 1006     # t_video.status_code — STT 1차 공정 완료


def save_result(info, code: int = STT_END) -> None:
    """info 의 STT 산출물을 한 트랜잭션으로 저장:
      t_dialogue          ← info.kept       (대사)
      t_dialogue_summary  ← info.segments   (구간요약)
      t_video (UPDATE)    ← info.summary_stt/search_result/search_query + status_code
    """
    with connect() as conn, conn.cursor() as cur:
        n_dlg = t_dialogue.insert(cur, info)
        n_sum = t_dialogue_summary.insert(cur, info)
        t_video.update_result(cur, info, code)
    log.info(f"db_svc save: v_id={info.v_id} dialogue={n_dlg} summary={n_sum} → status={code}")
