# LLM-backed Turn Summaries, Rolling Memory & Tagging

**Date:** 2026-06-21
**Status:** Approved design, pending implementation plan

## Problem

Post-processing currently derives three artifacts from each conversation using
deterministic heuristics. They are cheap but miss the *essence* of a turn:

1. **Turn index** (`postprocess.build_turn_index_entries`) — per-turn summary is
   literal truncation: assistant turns = Stage 3 response clipped to 180/420
   chars; user turns = regex pasted-source detection.
2. **Rolling memory** (`postprocess.build_memory_record`) — conversation-level
   goal/constraints/decisions extracted via sentence-keyword heuristics.
3. **Entity/theme tagging** (`entity_extraction.build_conversation_entities`) —
   capitalized-word regex + lowercase keyword frequency with hand-maintained
   stopword lists.

Replace the *quality-bearing* parts of all three with a cheap LLM, while keeping
cost effectively negligible and preserving today's behavior as a fallback.

## Goals

- Better summaries and tags that capture intent, not substrings.
- Stay extremely cheap: avoid O(N²) re-summarization across a conversation's life.
- Surgical: keep the existing three-job / three-table architecture, schemas,
  storage, and frontend untouched. No DB migration.
- Graceful degradation: any LLM failure falls back to today's deterministic path.

## Non-Goals

- No DB migrations (reuse the existing `transcript_offset` jsonb column).
- No frontend changes (output schemas are unchanged).
- `bundle` and `model` tags stay deterministic — they are exact metadata, not
  inferred, so an LLM adds nothing and risks hallucination.
- Rolling-memory `summary_json` key set is unchanged; the LLM fills the same keys.

## Architecture

Approach **A — Incremental + composed** (chosen over a naive full-rebuild swap,
which is O(N²), and over a single consolidated call, which couples the three
systems and makes fallback all-or-nothing).

Per-turn summaries are computed **once** and cached (turns are append-only, so a
message's index is immutable). Memory and tagging consume the compact cached
turn-summaries instead of re-reading the full transcript. Each pass falls back to
its existing deterministic twin independently.

### Cost model

- Steady state per new turn: ~3 small calls (1 turn summary + 1 memory + 1 tags),
  each a few hundred tokens at nano pricing → fractions of a cent.
- First-time backfill of an existing long conversation: N turn-summaries
  (batched), one-time.
- The job enqueue (`enqueue_export_job`) already coalesces pending jobs per
  conversation+type, so bursts collapse to one refresh.

## Components

### 1. Config — `backend/config.py`

- `SUMMARIZER_MODEL: str` — default `"openai/gpt-5-nano"`. **Verify the exact
  OpenRouter slug at implementation time;** if unavailable, fall back to
  `"google/gemini-2.5-flash"` (the existing cheap lane).
- `SUMMARIZER_ENABLED: bool` — default `True`. Master kill-switch: when `False`,
  all three passes use today's deterministic path. Read from env.
- `SUMMARIZER_VERSION: int` — constant. Bumping it invalidates cached turn
  summaries and forces re-summarization.
- `SUMMARIZER_MIN_CHARS: int` — default `120`. User turns at or below this length
  (and with no code block / pasted-source structure) skip the LLM and pass
  through cleaned raw text — the raw text already *is* the essence for a true
  one-liner. Assistant turns and long/pasted user turns always get summarized.

### 2. New module — `backend/summarizer.py`

Single home for the LLM passes and their prompts, so `postprocess.py` and
`entity_extraction.py` stay focused. All functions are `async`, return the **same
shape** as their deterministic twin, and return `None` on any failure (timeout,
empty content, invalid JSON, disabled flag).

- `async summarize_turn(role, content, stage3_response) -> str | None`
  Returns a one-line essence (≤180 chars). Role-aware prompt (user ask vs.
  assistant verdict).
- `async summarize_memory(turn_summaries, bundle, latest_stage3) -> dict | None`
  Returns a dict conforming to the existing `summary_json` keys
  (`current_goal`, `user_objective`, `stable_constraints`, `recent_decisions`,
  `open_threads`, `background_context_notes`, `active_bundle`, etc.). JSON output
  parsed from the model's content string and validated against the required keys;
  missing/extra keys → treat as failure → fallback.
- `async extract_tags(turn_summaries, memory) -> list[dict] | None`
  Returns a list of `{entity_type, canonical_name, link_type, metadata}` for the
  `entity` and `theme` types only.

Each call is wrapped with `build_usage_request(kind=..., usage=..., model=...)`
(`kind` ∈ `turn_summary | memory_summary | tagging`) mirroring
`council.generate_conversation_title`.

### 3. Turn summaries — incremental (`worker.py` `index_turns` job)

1. Read existing rows via `postgres_store.get_conversation_turn_index`. **Extend
   that function's SELECT to also return `transcript_offset`** (currently it does
   not), so cached version/hash are visible.
2. Build a map `message_index -> existing_entry`.
3. For each message, reuse the stored `short_highlight` when the stored
   `summarizer_version == SUMMARIZER_VERSION` **and** `source_hash` matches the
   current content hash; otherwise compute a fresh summary:
   - Assistant turn → `summarize_turn(role, content, stage3_response)`.
   - User turn, length > `SUMMARIZER_MIN_CHARS` or structured → `summarize_turn`.
   - User turn, very short and unstructured → cleaned raw text (no LLM).
   - On `summarize_turn` returning `None` → today's deterministic
     `build_turn_index_entries` logic for that turn.
4. `stage3_excerpt` stays a **verbatim** deterministic clip (a real-words preview;
   keeping it literal is intentional and free).
5. Persist `summarizer_version` and `source_hash` inside the `transcript_offset`
   jsonb (no schema change). `replace_turn_index` still writes the full set; the
   savings are purely in skipped LLM calls for unchanged turns.

The turn-summary builder moves to / is wrapped by an async path the worker awaits.
`build_turn_index_entries` is retained as the fallback/deterministic core.

### 4. Memory — `refresh_memory` job

Feed the compact cached per-turn summaries (not the full transcript), the active
bundle, and the latest Stage 3 to `summarize_memory`. Validate the returned keys;
on `None`/invalid → existing `build_memory_record`. Output schema, storage call
(`store_conversation_memory`), and frontend consumption are unchanged.

### 5. Tagging — `extract_entities` job

- Keep `bundle` and `model` extraction exactly as-is (deterministic, exact).
- Replace only the regex `entity`/`theme` extraction with `extract_tags`, fed the
  cached turn summaries + memory. On `None` → existing
  `_extract_capitalized_entities` / `_extract_theme_terms` path.
- De-dup via the existing `add_entity` mechanism. Output schema unchanged.

## Error handling / graceful degradation

- Every pass falls back to its current deterministic function on any failure.
- Deterministic functions are **kept, not deleted**.
- `SUMMARIZER_ENABLED=False` → today's behavior globally.
- Worst case at any layer = current behavior. No new failure surface for users.

## Usage / cost visibility

Worker-side LLM usage is not currently folded into a conversation's usage summary.
Minimum: log each call's usage. Note in the plan where it would plug into the
usage aggregation if surfaced later. Not a blocker for shipping.

## Testing

- Unit: `summarizer.py` functions return correct shape; return `None` on
  malformed model output, timeout, and `SUMMARIZER_ENABLED=False`.
- Unit: incremental reuse — unchanged turns are not re-summarized when
  `summarizer_version`/hash match; changed `SUMMARIZER_VERSION` forces recompute.
- Unit: very-short user turn passes through without an LLM call; long/structured
  user turn and assistant turn invoke the LLM.
- Unit: each job's deterministic fallback fires when the LLM returns `None`.
- Integration: a multi-turn conversation produces valid turn index / memory /
  entity rows end-to-end with the summarizer enabled and disabled.

## Open items to verify at implementation time

- Exact OpenRouter slug for `gpt-5-nano`.
- JSON-from-content parsing robustness for the memory/tags passes (the
  `query_model` return is a content string, not a structured tool call).
- Extending `get_conversation_turn_index` SELECT to include `transcript_offset`.
