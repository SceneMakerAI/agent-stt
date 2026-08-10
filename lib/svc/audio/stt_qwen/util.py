"""시각 변환 — 순수 함수만. (pipe_stt_qwen 이 쓴다)

여기에 있는 이유 — 워커가 주는 'HH:MM:SS.s' 문자열을 다루는 곳이 1차 전사 하나로 모였다.
Dialogue 가 start_sec/end_sec 을 같이 들고 다니게 되면서, 뒤 스텝들(할루시·요약·2차 전사)은
문자열을 다시 파싱하지 않는다.
"""


def time_to_sec(t: str) -> float:
    """'HH:MM:SS.s' → 초. (sec_to_time 의 역방향)"""
    h, m, s = t.split(":")
    return int(h) * 3600 + int(m) * 60 + float(s)


def sec_to_time(sec: float) -> str:
    """초 → 'HH:MM:SS.s'. (time_to_sec 의 역방향)

    0.1초 단위 정수로 환산한 뒤 포맷한다 — 실수 상태로 포맷하면 출력할 때 또 반올림돼
    SS=60 같은 값이 다시 나올 수 있다. 정수로 만들면 자리올림이 여기서 끝난다.
    """
    tenths = round(sec * 10)
    ss = tenths % 600          # 분 내 0.1초 (0~599)
    mm = tenths // 600 % 60
    hh = tenths // 36000
    return f"{hh:02d}:{mm:02d}:{ss // 10:02d}.{ss % 10:d}"


def norm_time(t: str) -> str:
    """'HH:MM:SS.s' 정규화 — 워커 반올림으로 SS=60 이 나오는 경우(예 '01:39:60.0')를 보정.

    워커의 _fmt_time 이 s=59.96 을 '60.0' 으로 반올림해 MariaDB TIME 이 거부함.
    초로 환산했다 되돌리면 자리올림이 해결된다 ('01:39:60.0' → '01:40:00.0').
    """
    return sec_to_time(time_to_sec(t))
