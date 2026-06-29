"""vLLM (Qwen3.6, OpenAI 호환) 호출 — transport 계층.

AsyncOpenAI + asyncio.Semaphore 캡슐. 한 chat() 호출 = 슬롯 1개 소비
→ 동시 호출 수가 config.VLLM_CONCURRENCY 로 제한된다 (vLLM max-num-seqs 보호).

인스턴스는 프로세스당 1개 만들어 공유 (멀티요청/HTTP화 대비) — corrector 가 주입받아 쓴다.
'무엇을' 보낼지(프롬프트/페이지)는 corrector 책임, 여기는 '어떻게' 보낼지만.
"""
from __future__ import annotations

import asyncio
import time

from openai import AsyncOpenAI

import config
from lib.log import get_logger

log = get_logger(__name__)


class VLLMClient:
    """AsyncOpenAI + Semaphore. chat() 한 번이 동시성 슬롯 1개를 쓴다."""

    def __init__(self, openai: AsyncOpenAI, sem: asyncio.Semaphore, model: str) -> None:
        self._openai = openai
        self._sem = sem
        self.model = model

    async def chat(
        self,
        *,
        messages: list[dict],
        temperature: float = 0.2,
        max_tokens: int = 2048,
        response_format: dict | None = None,
        extra_body: dict | None = None,
    ) -> tuple[str, int]:
        """chat.completions.create 1회 호출 → (응답 text, elapsed_ms).

        파싱(JSON 등)은 호출자(corrector) 책임. 여기선 content 문자열만 돌려준다.
        """
        async with self._sem:
            t0 = time.monotonic()
            resp = await self._openai.chat.completions.create(
                model=self.model,
                messages=messages,
                temperature=temperature,
                max_tokens=max_tokens,
                response_format=response_format,
                extra_body=extra_body,
            )
            elapsed_ms = int((time.monotonic() - t0) * 1000)
            return resp.choices[0].message.content, elapsed_ms

    async def close(self) -> None:
        await self._openai.close()


def build() -> VLLMClient:
    """config 로 VLLMClient 1개 생성. main / lifespan 에서 1회 호출해 공유한다."""
    # vLLM 은 인증 없음. SDK 가 빈 키를 거부해서 더미값만 넣는다.
    openai = AsyncOpenAI(base_url=config.VLLM_BASE_URL, api_key="-")
    sem = asyncio.Semaphore(config.VLLM_CONCURRENCY)
    log.info(f"vllm client: {config.VLLM_BASE_URL} model={config.VLLM_MODEL} conc={config.VLLM_CONCURRENCY}")
    return VLLMClient(openai, sem, config.VLLM_MODEL)
