"""공용 로거 — 파일(/usr/service/logs/scenemaker/stt_agent.log) + 콘솔.

파일: 영속 로그 (model_svc 와 동일 경로/포맷).
콘솔: 실행 stdout 확인용.
get_logger(name) 을 재호출해도 핸들러 중복 없이 재사용.
"""
import logging

import config

LOG_DIR = config.LOG_DIR
LOG_FILE = config.LOG_FILE

_FORMAT = logging.Formatter(
    "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
_configured = False


def _configure_root() -> None:
    """루트 로거에 파일+콘솔 핸들러를 1회 부착."""
    global _configured
    if _configured:
        return

    root = logging.getLogger()
    root.setLevel("INFO")

    LOG_DIR.mkdir(parents=True, exist_ok=True)
    fh = logging.FileHandler(LOG_FILE, encoding="utf-8")
    fh.setFormatter(_FORMAT)
    root.addHandler(fh)

    ch = logging.StreamHandler()
    ch.setFormatter(_FORMAT)
    root.addHandler(ch)

    _configured = True


def get_logger(name: str) -> logging.Logger:
    _configure_root()
    return logging.getLogger(name)
