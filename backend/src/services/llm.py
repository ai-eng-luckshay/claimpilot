"""Centralized LLM service — provider-agnostic interface with factory pattern.

Usage:
    from backend.src.services.llm import get_llm_service

    llm = get_llm_service("extraction")     # multimodal OCR cascade
    llm = get_llm_service("adjudication")   # reasoning cascade
    result = llm.structured_call(prompt, OutputSchema)
    result = llm.structured_call(prompt, OutputSchema, content_blocks=[...])  # multimodal

Model cascade: on HTTP 429 (rate limit), the service automatically retries with the next
model in the cascade. Rate-limited models are tracked globally — if a model is exhausted
in one cascade it is also skipped in all other cascades for 24 hours.

Any non-429 error is raised immediately without retrying.

To add a new provider:
    1. Implement a class inheriting LLMService.
    2. Register it in _PROVIDERS at the bottom of this file.
    3. Set LLM_PROVIDER=<key> in your .env file.
"""

import threading
import time
from abc import ABC, abstractmethod
from typing import Any, Type, cast

from pydantic import BaseModel
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_core.messages import HumanMessage, AIMessage

from backend.src.config.app_settings import settings
from backend.src.config.logger_config import error_logger


class LLMService(ABC):
    """Abstract base — all agents call through this interface."""

    @abstractmethod
    def structured_call(
        self,
        prompt: str,
        output_schema: Type[BaseModel],
        *,
        chat_history: list[dict] | None = None,
        content_blocks: list[dict] | None = None,
    ) -> BaseModel:
        """
        Call the LLM and return a validated Pydantic instance.

        Args:
            prompt: Instruction text. When content_blocks is given, this is prepended
                    as the first text block; otherwise it is the sole message body.
            output_schema: Pydantic model the response must conform to.
            chat_history: Optional prior turns [{role: "user"|"assistant", content: str}].
            content_blocks: Optional multimodal content dicts (images, PDFs, extra text).
                            {"type": "text",  "text": "..."}
                            {"type": "image", "base64": "...", "mime_type": "image/jpeg"}
                            {"type": "file",  "base64": "...", "mime_type": "application/pdf"}
        """
        ...


# ---------------------------------------------------------------------------
# Gemini provider — cascade fallback on rate limiting (HTTP 429)
# ---------------------------------------------------------------------------

def _is_rate_limited(exc: Exception) -> bool:
    """Return True if the exception indicates an HTTP 429 / quota exhausted error."""
    msg = str(exc).lower()
    return (
        "429" in msg
        or "resource has been exhausted" in msg
        or "quota exceeded" in msg
        or "rate limit" in msg
    )


class GeminiService(LLMService):
    """
    LangChain-backed Gemini provider with per-use-case model cascades.

    Models are tried in order. On HTTP 429 the model is added to a shared
    exhausted set and the next model in the cascade is tried. Because the set
    is class-level, a model that is rate-limited in one cascade is automatically
    skipped in all other cascades for the same 24-hour window.

    Update the cascade lists below as new Gemini models become available.
    """

    # Stage 1 — Image Understanding / OCR (multimodal, speed-optimised)
    EXTRACTION_CASCADE: list[str] = [
        "gemini-3.1-flash-lite",    # primary
        "gemini-2.5-flash-lite",    # fallback 1
        "gemini-2.0-flash-lite",    # fallback 2
        "gemini-3.5-flash",         # fallback 3
        "gemini-3.0-flash",         # fallback 4
        "gemini-2.5-flash",         # fallback 5
        "gemini-2.0-flash",         # fallback 6
    ]

    # Stage 2 — Claims Decision (text reasoning, policy + fraud + decision)
    ADJUDICATION_CASCADE: list[str] = [
        "gemini-3.1-flash-lite",    # primary
        "gemini-2.5-flash-lite",    # fallback 1
        "gemini-2.0-flash-lite",    # fallback 2
        "gemini-3.5-flash",         # fallback 3
        "gemini-3.0-flash",         # fallback 4
        "gemini-2.5-flash",         # fallback 5
        "gemini-2.0-flash",         # fallback 6
    ]

    _RESET_AFTER_SECONDS: int = 60 * 60 * 24  # 24 hours — aligns with Gemini daily quota reset

    # Global exhausted-model registry — shared across all cascade instances.
    # Key: model name, Value: timestamp when the model was first rate-limited.
    # Models are re-admitted after _RESET_AFTER_SECONDS.
    _exhausted_models: dict[str, float] = {}
    _lock: threading.Lock = threading.Lock()

    def __init__(self, models: list[str], cascade_key: str = "default", temperature: float = 0):
        self._models = models
        self._cascade_key = cascade_key
        self._temperature = temperature

    def structured_call(
        self,
        prompt: str,
        output_schema: Type[BaseModel],
        *,
        chat_history: list[dict] | None = None,
        content_blocks: list[dict] | None = None,
    ) -> BaseModel:
        # Expire models whose 24-hour window has passed.
        with GeminiService._lock:
            now = time.time()
            recovered = [
                m for m, t in GeminiService._exhausted_models.items()
                if now - t >= GeminiService._RESET_AFTER_SECONDS
            ]
            for m in recovered:
                del GeminiService._exhausted_models[m]
                error_logger.info("LLM: model=%s quota reset after 24h", m)

        last_error: Exception | None = None

        for model in self._models:
            with GeminiService._lock:
                if model in GeminiService._exhausted_models:
                    continue  # skip globally rate-limited models across all cascades

            try:
                result = self._invoke(
                    model, prompt, output_schema,
                    chat_history=chat_history,
                    content_blocks=content_blocks,
                )
                if model != self._models[0]:
                    error_logger.warning(
                        "LLM.structured_call: succeeded on fallback model=%s cascade=%s",
                        model, self._cascade_key,
                    )
                return result

            except Exception as exc:
                if _is_rate_limited(exc):
                    with GeminiService._lock:
                        if model not in GeminiService._exhausted_models:
                            GeminiService._exhausted_models[model] = time.time()
                            available = [m for m in self._models if m not in GeminiService._exhausted_models]
                            error_logger.warning(
                                "LLM.structured_call: rate limited on model=%s (cascade=%s) — "
                                "added to global exhausted set; remaining in this cascade: %s",
                                model, self._cascade_key, available,
                            )
                    last_error = exc
                    continue
                raise  # non-429 errors bubble up immediately

        raise last_error or RuntimeError(
            f"All models in cascade '{self._cascade_key}' exhausted: {self._models}"
        )

    def _invoke(
        self,
        model: str,
        prompt: str,
        output_schema: Type[BaseModel],
        *,
        chat_history: list[dict] | None,
        content_blocks: list[dict] | None,
    ) -> BaseModel:
        llm = ChatGoogleGenerativeAI(
            model=model,
            google_api_key=settings.google_api_key,
            temperature=self._temperature,
        ).with_structured_output(output_schema, method="json_schema")

        messages: list[Any] = []

        if chat_history:
            for msg in chat_history:
                content = msg.get("content", "")
                messages.append(
                    AIMessage(content=content)
                    if msg.get("role") == "assistant"
                    else HumanMessage(content=content)
                )

        if content_blocks:
            full_content = cast(list[str | dict[Any, Any]], [{"type": "text", "text": prompt}] + content_blocks)
            messages.append(HumanMessage(content=full_content))
        else:
            messages.append(HumanMessage(content=prompt))

        error_logger.info(
            "LLM._invoke: model=%s schema=%s multimodal=%s",
            model, output_schema.__name__, content_blocks is not None,
        )
        return cast(BaseModel, llm.invoke(messages))


# ---------------------------------------------------------------------------
# Registry + factory
# ---------------------------------------------------------------------------

_PROVIDERS: dict[str, type[GeminiService]] = {
    "gemini": GeminiService,
    # "openai": OpenAIService,
    # "anthropic": AnthropicService,
}

_CASCADES: dict[str, list[str]] = {
    "extraction":    GeminiService.EXTRACTION_CASCADE,
    "adjudication":  GeminiService.ADJUDICATION_CASCADE,
}


def get_llm_service(use_case: str = "adjudication", **kwargs) -> LLMService:
    """
    Return an LLMService configured for the given use case.

    use_case:
        "extraction"   — multimodal OCR cascade (lighter models first)
        "adjudication" — reasoning cascade (flash first, pro as emergency)

    kwargs: passed to the provider constructor (e.g. temperature=0.2).
    """
    provider_key = settings.llm_provider.lower()
    cls = _PROVIDERS.get(provider_key)
    if cls is None:
        raise ValueError(
            f"Unknown LLM provider '{provider_key}'. Registered: {list(_PROVIDERS.keys())}"
        )
    models = _CASCADES.get(use_case, GeminiService.ADJUDICATION_CASCADE)
    return cls(models=models, cascade_key=use_case, **kwargs)
