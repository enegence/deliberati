import pytest

from backend import worker


def _conv():
    return {
        "id": "00000000-0000-0000-0000-000000000001",
        "created_at": "2026-06-21T00:00:00Z",
        "messages": [
            {"role": "user", "content": "Need a fast CSV importer, avoid pandas."},
            {"role": "assistant", "stage3": {"response": "Use stdlib csv, streamed."}},
        ],
    }


@pytest.fixture
def stub_storage(monkeypatch):
    from backend import storage, postgres_store
    monkeypatch.setattr(storage, "get_conversation", lambda cid: _conv())
    monkeypatch.setattr(postgres_store, "get_conversation_turn_index", lambda cid: [])
    monkeypatch.setattr(postgres_store, "get_latest_conversation_memory", lambda cid: {})
    captured = {}
    monkeypatch.setattr(postgres_store, "replace_turn_index", lambda cid, e: captured.__setitem__("turns", e) or True)
    monkeypatch.setattr(postgres_store, "store_conversation_memory", lambda *a: (captured.__setitem__("memory", a[2]) or 1))
    monkeypatch.setattr(postgres_store, "replace_conversation_entities", lambda cid, e: captured.__setitem__("entities", e) or True)
    return captured


async def test_index_turns_job_runs_with_summarizer_disabled(stub_storage, monkeypatch):
    from backend import config
    monkeypatch.setattr(config, "SUMMARIZER_ENABLED", False)
    await worker.process_job({"job_type": "index_turns", "conversation_id": _conv()["id"], "id": "j1"})
    assert len(stub_storage["turns"]) == 2  # deterministic floor, no crash


async def test_all_jobs_run_with_summarizer_enabled(stub_storage, enable_summarizer, monkeypatch):
    from backend import summarizer

    async def fake_turn(role, content, stage3_response):
        return {"summary": "ESSENCE", "usage": None}

    async def fake_memory(seed, turn_summaries):
        return {
            "current_goal": "fast csv", "user_objective": "fast csv",
            "stable_constraints": ["avoid pandas"], "recent_decisions": ["stdlib csv"],
            "open_threads": [], "background_context_notes": [],
        }

    async def fake_tags(turn_summaries, memory_text):
        return [{"entity_type": "theme", "canonical_name": "csv import", "link_type": "theme", "metadata": {"source": "llm"}}]

    monkeypatch.setattr(summarizer, "summarize_turn", fake_turn)
    monkeypatch.setattr(summarizer, "summarize_memory", fake_memory)
    monkeypatch.setattr(summarizer, "extract_tags", fake_tags)

    for job_type in ("index_turns", "refresh_memory", "extract_entities"):
        await worker.process_job({"job_type": job_type, "conversation_id": _conv()["id"], "id": "j"})

    # First message is a short user turn — deterministically skipped by LLM; LLM summary lands on turns[1] (assistant).
    assert stub_storage["turns"][1]["short_highlight"] == "ESSENCE"
    assert any(e["canonical_name"] == "csv import" for e in stub_storage["entities"])
    assert stub_storage["memory"]["current_goal"] == "fast csv"
