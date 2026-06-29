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

# ── 교정 페이지 분할 (④)
VLLM_CONCURRENCY = 8          # 페이지 동시 호출 상한
PAGE_MAX_SEGMENTS = 30        # 페이지당 최대 자막 줄 수


# ── 디버그 — 단계별 중간 결과를 파일로 덤프 (검수용).
# ⚠ 단계 간 데이터 전달은 "메모리"로만 한다. 아래 덤프는 write-only —
#    다음 단계가 절대 읽지 않는다 (파일 read 는 느려서 금지). 순수 디버깅용.
DEBUG_DIR = Path(os.getenv("DEBUG_DIR"))
DUMP_STEPS = {
    "stt":       True,   # ③ model_svc STT → segments
    "pages":     True,   # ④ 페이지 분할 (vLLM 입력)
    "corrected": True,   # ④ vLLM 교정 결과
}
