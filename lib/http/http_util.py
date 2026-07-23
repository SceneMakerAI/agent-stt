"""HTTP 공용 — 요청/응답 로깅 미들웨어 + 핸들러 공통 응답.

미들웨어: 요청 들어올 때 method+URL, 끝날 때 상태코드+URL+소요시간 로그.
main.py 에서 register(app) 로 등록.
"""
import time

from fastapi import Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from lib.log import get_logger

log = get_logger(__name__)


def busy_response(body: BaseModel) -> JSONResponse:
    """백프레셔 초과 시 공통 429 응답. 본문은 각 URL 의 response 모델 (여기선 감싸기만)."""
    return JSONResponse(
        status_code=429,
        content=body.model_dump(),
        headers={"Retry-After": "60"},
    )


def register(app):
    @app.middleware("http")
    async def log_requests(request: Request, call_next):
        log.info(f"→ {request.method} {request.url}")
        t0 = time.time()
        response = await call_next(request)
        log.info(f"← {request.method} {request.url} {response.status_code} ({time.time() - t0:.1f}s)")
        return response


