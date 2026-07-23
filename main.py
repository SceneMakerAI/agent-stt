"""stt_agent 진입점 — FastAPI app 생성 + 라우터 등록만. 로직은 lib/ 계층에 둠:
    lib/http      핸들러(라우터) + 요청/응답 DTO   전송 계층 (HTTP)
    lib/service   비즈니스 로직 (transport 무관, 공정 조립)
    lib/client    model_svc(STT) / vLLM(교정) 호출
    lib/client/db.py  MariaDB 저장 (상태 갱신 + 자막 INSERT)

공정 (vid 1개당, POST /correct_svc/):
  ②③ STT  : model_svc 동기 호출 → 5~10분 블로킹 후 segments
  ④ 교정   : vLLM(Qwen) 페이지 병렬 교정  (async)
  ⑤ 저장   : t_dialogue INSERT + status_code 갱신

공유 리소스(vLLM 클라이언트 / httpx)는 lifespan 에서 1회 만들어 app.state 에 둔다.
vLLM 클라이언트(AsyncOpenAI)는 lifespan 안에서 생성돼 uvicorn 이벤트루프에 바인딩 —
교정(④)을 그 루프에서 그대로 await. (배치 시절의 수동 루프 관리는 불필요)

실행:  uv run uvicorn main:app --host 0.0.0.0 --port 8002 --reload
"""
import asyncio
import ssl
from contextlib import asynccontextmanager

import httpx
import uvicorn
from fastapi import FastAPI

import config
from lib.client import vllm
from lib.http import http_util, stt_svc
from lib.log import get_logger

log = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # OpenSSL 을 메인 스레드에서 선(先)초기화. 이 환경의 OpenSSL 은 비-메인 스레드에서
    # 처음 초기화되면 깨진다(SSLError _ssl.c:3123). AsyncOpenAI/httpx 가 SSL 컨텍스트를
    # 만들기 전에 여기서 한 번 띄워둔다. (worker-prep_stt 와 동일한 워크어라운드)
    ssl.create_default_context()

    # 공유 리소스 — uvicorn 이벤트루프 위에서 1회 생성해 app.state 로 공유.
    #   vllm  : AsyncOpenAI 가 '지금 이 루프'에 바인딩됨 → 교정(④)을 같은 루프에서 await.
    #   http  : STT 호출용 sync 클라이언트 (블로킹 호출은 service 가 to_thread 로 넘김).
    app.state.vllm = vllm.build()
    app.state.http = httpx.Client(timeout=httpx.Timeout(30.0))

    # 현재 접속한 사용자 수
    app.state.current_req_cnt = 0

    # prep+stt 동시성 상한 — 전역 1개(GPU).
    app.state.stt_sem = asyncio.Semaphore(config.STT_CONCURRENCY)

    log.info(f"stt_agent up: {config.HOST}:{config.PORT}")
    yield
    app.state.http.close()
    await app.state.vllm.close()


app = FastAPI(title="stt_agent", version="1.0", lifespan=lifespan)

app.include_router(stt_svc.router)
http_util.register(app)


@app.get("/")
def root():
    return {"message": "hello world", "service": "stt_agent"}


if __name__ == "__main__":
    uvicorn.run(app, host=config.HOST, port=config.PORT)
