import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

LOG_DIR = Path("/usr/service/logs/scenemaker")
LOG_FILE = LOG_DIR / "stt_agent.log"

# ── 서버 (FastAPI)
HOST = os.getenv("HOST")
PORT = int(os.getenv("PORT"))


# ── FFMPEG & STT —자막 호출/결과 조회
STT_HOST = os.getenv("STT_HOST")
STT_PORT = int(os.getenv("STT_PORT"))
PREP_STT_BASE_URL = f"http://{STT_HOST}:{STT_PORT}"
PREP_TIMEOUT_S = 60*5          # prep(ffmpeg) 대기(초) 
STT_TIMEOUT_S = 60*10          # STT 최대 대기(초) 

# 자막 교정용
VLLM_HOST = os.getenv("VLLM_HOST")
VLLM_PORT = int(os.getenv("VLLM_PORT"))
VLLM_BASE_URL = f"http://{VLLM_HOST}:{VLLM_PORT}/v1"
VLLM_MODEL = "qwen"

# 상태 업데이트 & 대사 결과 Insert DB
RDB_HOST = os.getenv("RDB_HOST")
RDB_PORT = int(os.getenv("RDB_PORT"))
RDB_USER = os.getenv("RDB_USER")
RDB_PW = os.getenv("RDB_PW")
RDB_NAME = os.getenv("RDB_NAME")

# ── 다음 단계 트리거 (⑦) — agent-vision 분석 요청
VISION_HOST = os.getenv("VISION_HOST")
VISION_PORT = int(os.getenv("VISION_PORT"))
VISION_BASE_URL = f"http://{VISION_HOST}:{VISION_PORT}"

# ── 동시성 제한 / 백프레셔
MAX_REQ_CNT = 5              # 접수 대기열 상한 (running + 대기). 초과 시 429 거절
STT_CONCURRENCY = 2          # prep+stt 동시 처리 상한 (whisper GPU 1개라 1)

# ── vLLM 동시성 — 클라이언트 전역 세마포어 (교정·검색 등 모든 vllm 호출이 공유)
VLLM_CONCURRENCY = 8          # 동시 vLLM 호출 상한 (lib/client/vllm.py 가 사용)

# ── 요약 (⑤ summary) — 구간(청크 병렬, 직전 N개 문맥) + 전체(마지막 1콜)
SUMMARY_WINDOW_SEC = 60      # 구간 요약 윈도우(초). 300=5분, 60=1분
SUMMARY_PREV_N = 3           # 구간 요약 시 참고할 직전 구간요약 개수 (앞 흐름 문맥. 뒤는 안 봄)
SUMMARY_CHUNKS = 8           # 구간요약을 몇 덩이로 나눠 동시에 돌릴지. 덩이 안은 순차(문맥 유지),
                             # 덩이끼리는 병렬. VLLM_CONCURRENCY 와 맞추는 게 최적(더 키워도 대기)

# ── 2차 보정 (cast — 화자 매칭 + 대사 이름 정정) 은 별도 공정으로 분리 (CAST.md 참고).


# ── 디버그 — 단계별 중간 결과를 파일로 덤프 (검수용).
# ⚠ 단계 간 데이터 전달은 "메모리"로만 한다. 아래 덤프는 write-only —
#    다음 단계가 절대 읽지 않는다 (파일 read 는 느려서 금지). 순수 디버깅용.
DEBUG_DIR = Path(os.getenv("DEBUG_DIR"))
DUMP_STEPS = {
    "1_stt":     True,   # 1차 STT(Qwen) → segments
    "2_roster":  True,   # web_search 명단 텍스트 (스포츠·드라마) — whisper 프롬프트 재료
    "3_whisper": True,   # 2차 전사(whisper) {idx: text} — 교정 대조용 (스포츠·드라마)
    "4_correct": True,   # vLLM 교정 결과 (1차 + whisper + 명단 대조)
    "5_hallu":   True,   # 할루시 필터 (kept/dropped/verdicts)
    "6_summary": True,   # 요약 (구간 + 전체)
}
