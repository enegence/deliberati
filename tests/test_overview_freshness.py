from datetime import datetime, timezone

from backend import main


def _conversation(message_count=4):
    """Alternating user/assistant transcript with `message_count` messages."""
    messages = []
    for i in range(message_count):
        created_at = f"2026-07-0{i + 1}T00:00:00+00:00"
        if i % 2 == 0:
            messages.append({
                "role": "user",
                "content": f"Question number {i + 1} about the council",
                "created_at": created_at,
            })
        else:
            messages.append({
                "role": "assistant",
                "created_at": created_at,
                "stage1": [{"model": "m/a", "response": "resp"}],
                "stage2": [{"model": "m/a", "ranking": "FINAL RANKING:\n1. Response A", "parsed_ranking": ["Response A"]}],
                "stage3": {"model": "m/chair", "response": f"Final answer {i + 1}"},
            })
    return {
        "id": "conv-1",
        "title": "Test",
        "created_at": "2026-07-01T00:00:00+00:00",
        "messages": messages,
    }


def _stored_entries(count):
    return [
        {
            "turn_number": n,
            "role": "user" if n % 2 == 1 else "assistant",
            "created_at": datetime(2026, 7, n, tzinfo=timezone.utc),
            "short_highlight": f"STORED-{n}",
            "stage3_excerpt": None,
            "transcript_offset": {"message_index": n - 1},
        }
        for n in range(1, count + 1)
    ]


def test_overview_turn_index_includes_new_turns_when_stored_lags(monkeypatch):
    # Stored index covers only the first 2 of 4 messages (follow-up just ran).
    monkeypatch.setattr(
        main.postgres_store, "get_conversation_turn_index", lambda cid: _stored_entries(2)
    )
    monkeypatch.setattr(
        main.postgres_store, "get_latest_conversation_memory", lambda cid: None
    )

    overview = main.serialize_conversation_overview("conv-1", _conversation(4))

    turn_index = overview["turn_index"]
    assert len(turn_index) == 4
    # Stored quality highlights win where present; derived fills the tail.
    assert turn_index[0]["short_highlight"] == "STORED-1"
    assert turn_index[1]["short_highlight"] == "STORED-2"
    assert turn_index[2]["short_highlight"]  # derived, non-empty
    assert turn_index[3]["short_highlight"]
    # created_at is always serialized to a string, whatever the source.
    assert all(isinstance(entry["created_at"], str) for entry in turn_index)


def test_overview_turn_index_uses_stored_when_complete(monkeypatch):
    monkeypatch.setattr(
        main.postgres_store, "get_conversation_turn_index", lambda cid: _stored_entries(4)
    )
    monkeypatch.setattr(
        main.postgres_store, "get_latest_conversation_memory", lambda cid: None
    )

    overview = main.serialize_conversation_overview("conv-1", _conversation(4))

    assert [e["short_highlight"] for e in overview["turn_index"]] == [
        "STORED-1", "STORED-2", "STORED-3", "STORED-4",
    ]
