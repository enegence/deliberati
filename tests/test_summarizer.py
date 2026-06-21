import pytest

from backend import summarizer


def test_content_hash_stable_and_sensitive():
    assert summarizer.content_hash("abc") == summarizer.content_hash("abc")
    assert summarizer.content_hash("abc") != summarizer.content_hash("abd")


def test_parse_json_block_handles_fenced_json():
    assert summarizer.parse_json_block('```json\n{"a": 1}\n```') == {"a": 1}
    assert summarizer.parse_json_block('noise {"a": 1} tail') == {"a": 1}
    assert summarizer.parse_json_block("not json") is None


async def test_summarize_turn_disabled_returns_none(monkeypatch):
    from backend import config
    monkeypatch.setattr(config, "SUMMARIZER_ENABLED", False)
    result = await summarizer.summarize_turn("assistant", "x", "long answer")
    assert result is None


async def test_summarize_turn_returns_summary(enable_summarizer, monkeypatch):
    async def fake_query_model(model, messages, timeout=120.0, max_attempts=2):
        return {"content": "  A crisp essence.  ", "usage": {"model": model}}
    monkeypatch.setattr(summarizer, "query_model", fake_query_model)
    result = await summarizer.summarize_turn("assistant", "", "long answer")
    assert result["summary"] == "A crisp essence."
    assert result["usage"]["kind"] == "turn_summary"


async def test_summarize_turn_none_on_query_failure(enable_summarizer, monkeypatch):
    async def fake_query_model(model, messages, timeout=120.0, max_attempts=2):
        return None
    monkeypatch.setattr(summarizer, "query_model", fake_query_model)
    assert await summarizer.summarize_turn("assistant", "", "answer") is None


async def test_summarize_turn_none_on_empty_content(enable_summarizer, monkeypatch):
    async def fake_query_model(model, messages, timeout=120.0, max_attempts=2):
        return {"content": "   ", "usage": None}
    monkeypatch.setattr(summarizer, "query_model", fake_query_model)
    assert await summarizer.summarize_turn("assistant", "", "answer") is None
