"""공용 유틸 — 특정 계층(client/http/correct)에 속하지 않는 순수 함수만 둔다."""


import datetime


def _fmt_tenths(tenths: int) -> str:
    """0.1초 단위 정수 → 'HH:MM:SS.s' 문자열."""
    ss = tenths % 600          # 분 내 0.1초 (0~599)
    mm = tenths // 600 % 60
    hh = tenths // 36000
    return f"{hh:02d}:{mm:02d}:{ss // 10:02d}.{ss % 10:d}"


def norm_time(t: str) -> str:
    """'HH:MM:SS.s' 정규화 — model_svc 반올림으로 SS=60 이 나오는 경우(예 '01:39:60.0')를 보정.

    model_svc 의 _fmt_time 이 s=59.96 을 '60.0' 으로 반올림해 MariaDB TIME 이 거부함.
    문자열 → 0.1초 단위 정수로 환산 후 자리올림하여 SS 를 0~59 로 강제 (포맷 반올림도 차단).
    """
    h, m, s = t.split(":")
    return _fmt_tenths(round((int(h) * 3600 + int(m) * 60 + float(s)) * 10))


def td_to_time(td: datetime.timedelta) -> str:
    """DB TIME 컬럼(pymysql 은 timedelta 로 반환) → 'HH:MM:SS.s' 문자열 (norm_time 과 같은 포맷)."""
    return _fmt_tenths(round(td.total_seconds() * 10))


def time_to_sec(t: str) -> float:
    """'HH:MM:SS.s' 문자열 → 초. (td_to_time 의 역방향, 윈도우 분할용)"""
    h, m, s = t.split(":")
    return int(h) * 3600 + int(m) * 60 + float(s)
