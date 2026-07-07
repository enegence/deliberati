from backend.postprocess import merge_turn_index_entries


def _entry(turn_number, highlight):
    return {
        "turn_number": turn_number,
        "role": "user" if turn_number % 2 == 1 else "assistant",
        "created_at": f"2026-07-0{turn_number}T00:00:00Z",
        "short_highlight": highlight,
        "stage3_excerpt": None,
        "transcript_offset": {"message_index": turn_number - 1},
    }


def test_empty_stored_returns_derived():
    derived = [_entry(1, "D1"), _entry(2, "D2")]
    assert merge_turn_index_entries([], derived) == derived


def test_stored_covering_all_turns_wins():
    stored = [_entry(1, "S1"), _entry(2, "S2")]
    derived = [_entry(1, "D1"), _entry(2, "D2")]
    merged = merge_turn_index_entries(stored, derived)
    assert [e["short_highlight"] for e in merged] == ["S1", "S2"]


def test_derived_fills_tail_when_stored_lags():
    # Follow-up scenario: stored index has 2 turns, transcript now has 4.
    stored = [_entry(1, "S1"), _entry(2, "S2")]
    derived = [_entry(1, "D1"), _entry(2, "D2"), _entry(3, "D3"), _entry(4, "D4")]
    merged = merge_turn_index_entries(stored, derived)
    assert [e["short_highlight"] for e in merged] == ["S1", "S2", "D3", "D4"]
    assert len(merged) == 4


def test_stored_extras_beyond_derived_are_dropped():
    stored = [_entry(1, "S1"), _entry(2, "S2"), _entry(3, "S3")]
    derived = [_entry(1, "D1")]
    merged = merge_turn_index_entries(stored, derived)
    assert [e["short_highlight"] for e in merged] == ["S1"]
