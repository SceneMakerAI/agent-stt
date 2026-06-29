"""HTTP 미들웨어 — 요청/응답 로깅.

요청 들어올 때 method+URL, 끝날 때 상태코드+URL+소요시간을 로그에 남긴다.
main.py 에서 register(app) 로 등록.
"""
import time

from fastapi import Request

from lib.log import get_logger

log = get_logger(__name__)


def register(app):
    @app.middleware("http")
    async def log_requests(request: Request, call_next):
        log.info(f"→ {request.method} {request.url}")
        t0 = time.time()
        response = await call_next(request)
        log.info(f"← {request.method} {request.url} {response.status_code} ({time.time() - t0:.1f}s)")
        return response


