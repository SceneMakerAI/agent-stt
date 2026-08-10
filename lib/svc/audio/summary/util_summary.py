"""요약의 보조 함수 — 순수 함수만. (pipe_summary.py 가 쓴다)

LLM 도 외부 호출도 안 쓴다. 셋뿐:
  video_ctx()  영상 정보 → 프롬프트에 실을 한 줄
  windows()    대사 → 시간 구간별 묶음 (요약 단위)
  split()      윈도우 → 덩이 경계 (병렬 단위)
"""
from lib.svc.audio.stt_qwen.schema_dialogue import Dialogue


def video_ctx(req) -> str:
    """영상 정보(제목/카테고리/방송연도) 컨텍스트 문자열. req 없으면 빈 줄."""
    if req is None:
        return "(정보 없음)"
    parts = []
    for label, key in (("제목", "title"), ("카테고리", "category"), ("방송연도", "year")):
        val = getattr(req, key, None)
        if val:
            parts.append(f"{label}: {val}")
    return " / ".join(parts) if parts else "(정보 없음)"


def windows(items: list[Dialogue], window_sec: int) -> list[dict]:
    """대사를 start_sec 기준 window_sec 구간으로 묶음.

    반환: [{"start_sec", "end_sec", "lines"}] — lines 는 'S002: 텍스트' 줄들.
    """
    if not items:
        return []
    buckets: dict[int, list[Dialogue]] = {}
    for s in items:
        w = int(s.start_sec // window_sec)   # 구간 인덱스
        buckets.setdefault(w, []).append(s)

    out = []
    for w in sorted(buckets):
        rows = buckets[w]
        lines = "\n".join(f'{r.speaker or "?"}: {r.text}' for r in rows)
        out.append({
            "start_sec": w * window_sec,
            "end_sec": (w + 1) * window_sec,
            "lines": lines,
        })
    return out


def split(windows: list[dict], k: int) -> list[int]:
    """windows 를 k 덩이로 나눌 때 각 덩이의 '시작 인덱스' 목록. 앞 덩이부터 1개씩 더 갖는다."""
    n = len(windows)
    if n == 0:
        return []
    k = max(1, min(k, n))                     # 윈도우보다 덩이가 많을 순 없다
    size, rest = divmod(n, k)
    starts, i = [], 0
    for c in range(k):
        starts.append(i)
        i += size + (1 if c < rest else 0)
    return starts
