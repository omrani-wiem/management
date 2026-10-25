from types import SimpleNamespace

import httpx
import pytest

from app.config import settings
from app.services import llm_provider


@pytest.fixture(autouse=True)
def _reset():
    llm_provider.get_llm.cache_clear()
    yield
    llm_provider.get_llm.cache_clear()


def test_ollama_request_shape(monkeypatch):
    captured = {}

    def fake_post(url, json=None, timeout=None):
        captured.update(url=url, payload=json, timeout=timeout)
        return SimpleNamespace(raise_for_status=lambda: None, json=lambda: {"message": {"content": '{"ok": 1}'}})

    monkeypatch.setattr(settings, "llm_provider", "ollama")
    monkeypatch.setattr(httpx, "post", fake_post)
    out = llm_provider.get_llm().chat([{"role": "user", "content": "salut"}], json_mode=True, max_tokens=123)
    assert out == '{"ok": 1}'
    assert captured["url"].endswith("/api/chat")
    assert captured["payload"]["format"] == "json" and captured["payload"]["stream"] is False
    assert captured["payload"]["options"]["num_predict"] == 123


def test_unknown_provider_gives_clear_error(monkeypatch):
    monkeypatch.setattr(settings, "llm_provider", "inconnu")
    with pytest.raises(RuntimeError, match="inconnu"):
        llm_provider.get_llm()


def test_groq_without_key_gives_clear_error(monkeypatch):
    monkeypatch.setattr(settings, "llm_provider", "groq")
    monkeypatch.setattr(settings, "groq_api_key", None)
    with pytest.raises(RuntimeError, match="GROQ_API_KEY"):
        llm_provider.get_llm()
