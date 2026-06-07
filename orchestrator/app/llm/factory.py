"""Construct the configured :class:`LLMProvider`."""

from __future__ import annotations

from ..config import Settings
from .base import LLMProvider
from .cerebras import CerebrasLLMProvider
from .gemini import GeminiLLMProvider
from .local import LocalLLMProvider
from .stub import StubLLMProvider


def build_llm(settings: Settings) -> LLMProvider:
    if settings.llm_provider == "stub":
        return StubLLMProvider()
    if settings.llm_provider == "gemini":
        if not settings.gemini_api_key:
            raise RuntimeError("GEMINI_API_KEY required for gemini provider.")
        return GeminiLLMProvider(settings.gemini_api_key, model=settings.gemini_model)
    if settings.llm_provider == "cerebras":
        if not settings.cerebras_api_key:
            raise RuntimeError("CEREBRAS_API_KEY required for cerebras provider.")
        return CerebrasLLMProvider(
            settings.cerebras_api_key,
            model=settings.cerebras_model,
            base_url=settings.cerebras_base_url,
            max_tokens=settings.llm_max_tokens,
            reasoning_effort=settings.llm_reasoning_effort,
            timeout_s=settings.llm_request_timeout_s,
            max_retries=settings.llm_max_retries,
            retry_backoff_s=settings.llm_retry_backoff_s,
            retry_backoff_max_s=settings.llm_retry_backoff_max_s,
            chunk_size=settings.llm_chunk_size,
        )
    if settings.llm_provider == "local":
        if not settings.local_llm_model_path:
            raise RuntimeError("LOCAL_LLM_MODEL_PATH required for local provider.")
        return LocalLLMProvider(settings.local_llm_model_path)
    raise ValueError(f"Unknown LLM_PROVIDER: {settings.llm_provider}")
