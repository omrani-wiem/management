"""Fournisseur de LLM interchangeable : Groq (cloud) ou Ollama (local / on-premise).
Choix par la variable d'environnement LLM_PROVIDER."""
import logging
from functools import lru_cache
from typing import Protocol

import httpx

from app.config import settings
from app.services.sensitive_data import redact_value

logger = logging.getLogger(__name__)


class LLMProvider(Protocol):
    name: str

    def chat(self, messages: list[dict], json_mode: bool = False, max_tokens: int = 2000) -> str: ...


class GroqProvider:
    name = "groq"

    def __init__(self) -> None:
        if not settings.groq_api_key:
            raise RuntimeError("GROQ_API_KEY manquant dans le .env (LLM_PROVIDER=groq)")
        from groq import Groq  # import tardif

        self._client = Groq(api_key=settings.groq_api_key)

    def chat(self, messages: list[dict], json_mode: bool = False, max_tokens: int = 2000) -> str:
        safe_messages = redact_value(messages)
        kwargs = {"response_format": {"type": "json_object"}} if json_mode else {}
        response = self._client.chat.completions.create(
            model=settings.groq_model,
            messages=safe_messages,
            temperature=0.1,
            max_tokens=max_tokens,
            **kwargs,
        )
        return redact_value(response.choices[0].message.content or "")


class OllamaProvider:
    name = "ollama"

    def chat(self, messages: list[dict], json_mode: bool = False, max_tokens: int = 2000) -> str:
        safe_messages = redact_value(messages)
        payload = {
            "model": settings.ollama_model,
            "messages": safe_messages,
            "stream": False,
            "options": {"temperature": 0.1, "num_predict": max_tokens, "num_ctx": 8192},
        }
        if json_mode:
            payload["format"] = "json"
        url = f"{settings.ollama_url.rstrip('/')}/api/chat"
        response = httpx.post(url, json=payload, timeout=settings.llm_timeout_s)
        response.raise_for_status()
        return redact_value(response.json().get("message", {}).get("content", "") or "")


@lru_cache(maxsize=1)
def get_llm() -> LLMProvider:
    provider = settings.llm_provider.strip().lower()
    logger.info("Fournisseur LLM : %s", provider)
    if provider == "groq":
        return GroqProvider()
    if provider == "ollama":
        return OllamaProvider()
    raise RuntimeError(f"LLM_PROVIDER inconnu : '{settings.llm_provider}' (valeurs : groq | ollama)")
