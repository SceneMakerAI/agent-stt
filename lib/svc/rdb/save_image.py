"""이미지 갈래 저장 — 어느 테이블에 무엇을 넣을지 정한다. 커서를 받는다.

트랜잭션(connect)은 save_svc 가 연다. 여기는 '무엇을 넣을지'만 안다:
  t_frame_adv           ← 프레임별 분류 (야구/광고·투구·보드종류 + 필수항목 개수)
  t_frame_board         ← 프레임별 스코어보드 박스
  t_frame_board_detail  ← 프레임별 보드 세부 6항목 (프레임당 6행)
  t_video_board         ← 영상 단위 고정 박스 7개

out 은 ImageOut(덕타이핑). out.video 가 None 이면 검출을 못 한 것이라 아무것도 안 넣는다 —
이미지 갈래는 옵션이라 그래도 음성 결과는 저장된다.
"""
from lib.client.rdb import (t_frame_adv, t_frame_board, t_frame_board_detail,
                            t_video_board)
from lib.log import get_logger

log = get_logger(__name__)


def save(cur, v_id: int, out) -> int:
    """ImageOut → 테이블 넷. 반환: 저장한 프레임 수 (검출 결과 없으면 0). 실패는 예외로 올라간다."""
    if out.video is None:
        log.info(f"save_image: v_id={v_id} 검출 결과 없음 — 저장 생략")
        return 0

    n_adv = t_frame_adv.delete_insert(cur, v_id, out.video)
    n_brd = t_frame_board.delete_insert(cur, v_id, out.video)
    n_dtl = t_frame_board_detail.delete_insert(cur, v_id, out.video)
    n_fix = t_video_board.delete_insert(cur, v_id, out.video)
    log.info(f"save_image: v_id={v_id} adv={n_adv} board={n_brd} detail={n_dtl} fixed={n_fix}")
    return n_adv
