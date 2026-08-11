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
import socket
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

KEEPALIVE_SOCKET_OPTIONS = [
    (socket.SOL_SOCKET, socket.SO_KEEPALIVE, 1),
    (socket.IPPROTO_TCP, socket.TCP_KEEPIDLE, 60*2),
    (socket.IPPROTO_TCP, socket.TCP_KEEPINTVL, 30),
    (socket.IPPROTO_TCP, socket.TCP_KEEPCNT, 5),
]


@asynccontextmanager
async def lifespan(app: FastAPI):
    # OpenSSL 을 메인 스레드에서 선(先)초기화. 이 환경의 OpenSSL 은 비-메인 스레드에서
    # 처음 초기화되면 깨진다(SSLError _ssl.c:3123). AsyncOpenAI/httpx 가 SSL 컨텍스트를
    # 만들기 전에 여기서 한 번 띄워둔다. (worker-prep_stt 와 동일한 워크어라운드)
    ssl.create_default_context()

    # 공유 리소스 — uvicorn 이벤트루프 위에서 1회 생성해 app.state 로 공유.
    #   vllm  : AsyncOpenAI 가 '지금 이 루프'에 바인딩됨 → 교정(④)을 같은 루프에서 await.
    #   http  : 워커 호출용 sync 클라이언트 (블로킹 호출은 svc 가 to_thread 로 넘김).
    #           keepalive 를 켜야 긴 추론 중에 NAT 가 연결을 끊지 않는다.
    #           timeout 30초는 기본값 — 오래 걸리는 호출은 각 client 가 직접 넘긴다
    #           (PREP_TIMEOUT_S / STT_TIMEOUT_S / IMG_MODELS_TIMEOUT_S).
    app.state.vllm = vllm.build()
    app.state.http = httpx.Client(
        timeout=httpx.Timeout(30.0),
        transport=httpx.HTTPTransport(socket_options=KEEPALIVE_SOCKET_OPTIONS),
    )

    # 현재 접속한 사용자 수 — 동시성 상한은 이 카운터(MAX_REQ_CNT) 하나로만 잡는다.
    #   요청 1건이 워커마다 한 번씩만 부르므로, 접수를 막으면 워커 호출도 같이 막힌다.
    app.state.current_req_cnt = 0

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
