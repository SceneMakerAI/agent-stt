"""rdb 공통 유틸 — 테이블 파일들이 공유하는 변환 헬퍼."""


def sec_to_time(sec: int) -> str:
    """초(정수) → 'HH:MM:SS.0' (time(1) 컬럼용). 구간 경계라 소수부는 0."""
    return f"{sec // 3600:02d}:{sec % 3600 // 60:02d}:{sec % 60:02d}.0"
