import pytest

from backend import entity_extraction, summarizer


def _conv():
    return {
        "title": "CarbonSKU planner",
        "created_at": "2026-06-21T00:00:00Z",
        "messages": [
            {
                "role": "user",
                "content": "Design CarbonSKU emissions tracking with strong audit trails.",
                "bundle": {"name": "Default Council", "council_models": ["openai/gpt-5.4"], "chairman_model": "openai/gpt-5.4"},
            },
            {"role": "assistant", "stage3": {"response": "Track CarbonSKU via append-only ledger."}},
        ],
    }


def test_exact_plus_inferred_equals_original():
    combined = entity_extraction.build_exact_entities(_conv()) + entity_extraction.build_inferred_entities(_conv())
    original = entity_extraction.build_conversation_entities(_conv())
    # Same set of (type, name, link) keys, order aside.
    def key(e):
        return (e["entity_type"], e["canonical_name"].lower(), e["link_type"])
    assert {key(e) for e in combined} == {key(e) for e in original}


def test_exact_entities_have_no_inferred_types():
    types = {e["entity_type"] for e in entity_extraction.build_exact_entities(_conv())}
    assert types <= {"bundle", "model"}


async def test_build_llm_entities_uses_llm_tags(enable_summarizer, monkeypatch):
    async def fake_extract_tags(turn_summaries, memory_text):
        return [
            {"entity_type": "entity", "canonical_name": "CarbonSKU", "link_type": "mentioned", "metadata": {"source": "llm"}},
            {"entity_type": "theme", "canonical_name": "emissions tracking", "link_type": "theme", "metadata": {"source": "llm"}},
        ]
    monkeypatch.setattr(summarizer, "extract_tags", fake_extract_tags)
    entities = await summarizer.build_llm_conversation_entities(_conv(), ["t1"], "mem")
    names = {(e["entity_type"], e["canonical_name"]) for e in entities}
    assert ("entity", "CarbonSKU") in names
    assert ("theme", "emissions tracking") in names
    # Exact bundle/model still present.
    assert any(e["entity_type"] == "bundle" for e in entities)
    assert any(e["entity_type"] == "model" for e in entities)


async def test_build_llm_entities_falls_back(enable_summarizer, monkeypatch):
    async def fake_extract_tags(turn_summaries, memory_text):
        return None
    monkeypatch.setattr(summarizer, "extract_tags", fake_extract_tags)
    entities = await summarizer.build_llm_conversation_entities(_conv(), ["t1"], "mem")
    original = entity_extraction.build_conversation_entities(_conv())
    def key(e):
        return (e["entity_type"], e["canonical_name"].lower(), e["link_type"])
    assert {key(e) for e in entities} == {key(e) for e in original}


async def test_extract_tags_drops_invalid_items(enable_summarizer, monkeypatch):
    async def fake_query_model(model, messages, timeout=120.0, max_attempts=2):
        return {"content": '[{"entity_type":"entity","canonical_name":"X","link_type":"mentioned"},{"bad":1}]', "usage": None}
    monkeypatch.setattr(summarizer, "query_model", fake_query_model)
    tags = await summarizer.extract_tags(["t1"], "mem")
    assert tags == [{"entity_type": "entity", "canonical_name": "X", "link_type": "mentioned", "metadata": {"source": "llm"}}]
