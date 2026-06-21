import pytest

from backend import postprocess, summarizer

REQUIRED_KEYS = {
    "current_goal", "user_objective", "stable_constraints",
    "recent_decisions", "open_threads", "background_context_notes",
}


def _conv():
    return {
        "title": "Build a thing",
        "created_at": "2026-06-21T00:00:00Z",
        "messages": [
            {"role": "user", "content": "I need a fast CSV importer. Must avoid pandas."},
            {"role": "assistant", "stage3": {"response": "Use the stdlib csv module streamed."}},
            {"role": "user", "content": "What about very large files?"},
            {"role": "assistant", "stage3": {"response": "Stream row by row; never load fully."}},
        ],
    }


def test_render_memory_text_matches_build_record():
    record = postprocess.build_memory_record(_conv())
    text, tokens = postprocess.render_memory_text(record["summary_json"])
    assert text == record["summary_text"]
    assert tokens == record["token_estimate"]


async def test_build_llm_memory_record_uses_llm_fields(enable_summarizer, monkeypatch):
    async def fake_summarize_memory(seed, turn_summaries):
        return {
            "current_goal": "LLM GOAL",
            "user_objective": "LLM OBJECTIVE",
            "stable_constraints": ["avoid pandas"],
            "recent_decisions": ["stream csv"],
            "open_threads": [],
            "background_context_notes": [],
        }
    monkeypatch.setattr(summarizer, "summarize_memory", fake_summarize_memory)
    record = await summarizer.build_llm_memory_record(_conv(), ["t1", "t2"], max_tokens=900)
    assert record["summary_json"]["current_goal"] == "LLM GOAL"
    assert "LLM GOAL" in record["summary_text"]
    assert REQUIRED_KEYS.issubset(record["summary_json"].keys())


async def test_build_llm_memory_record_falls_back(enable_summarizer, monkeypatch):
    async def fake_summarize_memory(seed, turn_summaries):
        return None
    monkeypatch.setattr(summarizer, "summarize_memory", fake_summarize_memory)
    record = await summarizer.build_llm_memory_record(_conv(), ["t1"], max_tokens=900)
    deterministic = postprocess.build_memory_record(_conv())
    assert record["summary_json"]["current_goal"] == deterministic["summary_json"]["current_goal"]


async def test_build_llm_memory_record_mirror_keys_synced(enable_summarizer, monkeypatch):
    async def fake_summarize_memory(seed, turn_summaries):
        return {
            "current_goal": "LLM GOAL",
            "user_objective": "LLM OBJECTIVE",
            "stable_constraints": ["llm-c"],
            "recent_decisions": ["llm-d"],
            "open_threads": ["llm-thread"],
            "background_context_notes": ["llm-note"],
        }
    monkeypatch.setattr(summarizer, "summarize_memory", fake_summarize_memory)
    record = await summarizer.build_llm_memory_record(_conv(), ["t1", "t2"], max_tokens=900)
    sj = record["summary_json"]
    assert sj["latest_user_request"] == sj["current_goal"] == "LLM GOAL"
    assert sj["persistent_constraints"] == sj["stable_constraints"] == ["llm-c"]
    assert sj["recent_council_conclusions"] == sj["recent_decisions"] == ["llm-d"]


async def test_summarize_memory_rejects_missing_keys(enable_summarizer, monkeypatch):
    async def fake_query_model(model, messages, timeout=120.0, max_attempts=2):
        return {"content": '{"current_goal": "x"}', "usage": None}  # missing required keys
    monkeypatch.setattr(summarizer, "query_model", fake_query_model)
    assert await summarizer.summarize_memory({}, ["t1"]) is None
