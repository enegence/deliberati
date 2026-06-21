import pytest

from backend import summarizer


def _conv():
    return {
        "created_at": "2026-06-21T00:00:00Z",
        "messages": [
            {"role": "user", "content": "ok"},  # very short -> pass-through
            {"role": "user", "content": "Please " + "x" * 200},  # long -> LLM
            {"role": "assistant", "stage3": {"response": "The answer is 42 in detail."}},
        ],
    }


async def _fake_summarize(role, content, stage3_response):
    return {"summary": "LLM-ESSENCE", "usage": None}


async def test_short_user_turn_skips_llm():
    calls = []

    async def spy(role, content, stage3_response):
        calls.append(content)
        return {"summary": "LLM-ESSENCE", "usage": None}

    entries = await summarizer.build_llm_turn_index_entries(_conv(), [], summarize_fn=spy)
    # Turn 1 (very short user) must not be summarized by the LLM.
    assert "ok" not in calls
    assert entries[0]["short_highlight"]  # deterministic floor present
    # Turns 2 (long user) and 3 (assistant) use the LLM.
    assert entries[1]["short_highlight"] == "LLM-ESSENCE"
    assert entries[2]["short_highlight"] == "LLM-ESSENCE"


async def test_version_and_hash_recorded():
    from backend import config
    entries = await summarizer.build_llm_turn_index_entries(_conv(), [], summarize_fn=_fake_summarize)
    for entry in entries:
        offset = entry["transcript_offset"]
        assert offset["summarizer_version"] == config.SUMMARIZER_VERSION
        assert isinstance(offset["source_hash"], str) and offset["source_hash"]


async def test_unchanged_turn_reuses_cached_summary():
    from backend import config
    conv = _conv()
    # Build once to capture hashes.
    first = await summarizer.build_llm_turn_index_entries(conv, [], summarize_fn=_fake_summarize)
    existing = [
        {
            "turn_number": e["turn_number"],
            "short_highlight": "CACHED-" + str(e["turn_number"]),
            "stage3_excerpt": e["stage3_excerpt"],
            "transcript_offset": e["transcript_offset"],
        }
        for e in first
    ]

    calls = []

    async def spy(role, content, stage3_response):
        calls.append(content)
        return {"summary": "FRESH", "usage": None}

    second = await summarizer.build_llm_turn_index_entries(conv, existing, summarize_fn=spy)
    # Nothing changed -> no LLM calls, cached summaries reused.
    assert calls == []
    assert second[1]["short_highlight"] == "CACHED-2"


async def test_version_bump_forces_recompute():
    from backend import config
    conv = _conv()
    first = await summarizer.build_llm_turn_index_entries(conv, [], summarize_fn=_fake_summarize)
    existing = []
    for e in first:
        stale = dict(e)
        stale_offset = dict(e["transcript_offset"])
        stale_offset["summarizer_version"] = config.SUMMARIZER_VERSION - 1
        stale["short_highlight"] = "STALE"
        stale["transcript_offset"] = stale_offset
        existing.append(stale)

    calls = []

    async def spy(role, content, stage3_response):
        calls.append(content)
        return {"summary": "FRESH", "usage": None}

    second = await summarizer.build_llm_turn_index_entries(conv, existing, summarize_fn=spy)
    # Long user + assistant recompute (short user still passes through).
    assert len(calls) == 2
    assert second[1]["short_highlight"] == "FRESH"


async def test_llm_failure_keeps_deterministic_floor():
    async def failing(role, content, stage3_response):
        return None

    entries = await summarizer.build_llm_turn_index_entries(_conv(), [], summarize_fn=failing)
    # Falls back to deterministic short_highlight (non-empty), no crash.
    assert all(e["short_highlight"] for e in entries)
    assert entries[1]["short_highlight"] != "LLM-ESSENCE"
