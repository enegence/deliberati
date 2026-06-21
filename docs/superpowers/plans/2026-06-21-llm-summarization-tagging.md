# LLM-backed Summaries & Tagging Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the deterministic heuristics in the three post-processing passes (turn index, rolling memory, entity/theme tagging) with a cheap configurable LLM, keeping cost O(N) via per-turn caching and preserving today's behavior as a fallback.

**Architecture:** A new `backend/summarizer.py` holds the LLM calls and three integration builders. Each builder computes the existing deterministic result as a floor, then overlays LLM output where available; any LLM failure leaves the deterministic result in place. Turn summaries are cached per-turn (keyed by `summarizer_version` + content hash stored in the existing `transcript_offset` jsonb), so a refresh only summarizes new/changed turns. The worker jobs (`index_turns`, `refresh_memory`, `extract_entities`) call the builders instead of the deterministic functions directly.

**Tech Stack:** Python 3.10, FastAPI, httpx (via existing `openrouter.query_model`), Postgres (psycopg), pytest + pytest-asyncio (added here).

## Global Constraints

- Backend modules use **relative imports** (`from .config import ...`). Run as `python -m backend.main` from repo root.
- All new LLM calls go through `backend.openrouter.query_model` and are wrapped with `backend.usage.build_usage_request(kind=..., usage=..., model=...)` (keyword-only).
- Every LLM builder returns the **same schema** as its deterministic twin and never raises — on any failure it returns the deterministic result.
- No DB migration. Per-turn cache metadata rides inside the existing `transcript_offset` jsonb column.
- No frontend changes. Output schemas are unchanged.
- `bundle` and `model` entity extraction stays deterministic (exact metadata).
- Config read at call-time via `config.NAME` (not `from .config import NAME`) for anything tests must toggle (`SUMMARIZER_ENABLED`, `SUMMARIZER_MODEL`, `SUMMARIZER_VERSION`, `SUMMARIZER_MIN_CHARS`).
- Run tests with `.venv/bin/pytest` from repo root.

---

## File Structure

- `pyproject.toml` — add test deps + pytest config (modify)
- `backend/config.py` — add `SUMMARIZER_*` constants (modify)
- `backend/summarizer.py` — LLM calls + 3 integration builders + helpers (create)
- `backend/postprocess.py` — extract `render_memory_text` helper from `build_memory_record` (modify)
- `backend/entity_extraction.py` — split exact vs inferred entity builders (modify)
- `backend/worker.py` — call the LLM builders in the three jobs (modify)
- `tests/__init__.py`, `tests/conftest.py` — test package + fixtures (create)
- `tests/test_summarizer.py`, `tests/test_turn_index.py`, `tests/test_memory.py`, `tests/test_tagging.py` (create)

---

### Task 1: Test scaffolding + config constants

**Files:**
- Modify: `pyproject.toml`
- Modify: `backend/config.py`
- Create: `tests/__init__.py`
- Create: `tests/test_config.py`

**Interfaces:**
- Produces: `config.SUMMARIZER_MODEL: str`, `config.SUMMARIZER_ENABLED: bool`, `config.SUMMARIZER_VERSION: int`, `config.SUMMARIZER_MIN_CHARS: int`.

- [ ] **Step 1: Add test deps + pytest config to `pyproject.toml`**

Append to `pyproject.toml`:

```toml
[project.optional-dependencies]
test = [
    "pytest>=8.0.0",
    "pytest-asyncio>=0.23.0",
]

[tool.pytest.ini_options]
asyncio_mode = "auto"
testpaths = ["tests"]
```

- [ ] **Step 2: Install test deps into the venv**

The project has no `[build-system]` and uses a flat layout, so an editable
install is unnecessary and would fail. `backend` imports fine from the repo
root, so install the test tools directly:

Run: `.venv/bin/pip install "pytest>=8.0.0" "pytest-asyncio>=0.23.0"`
Expected: installs pytest + pytest-asyncio successfully. (The
`[project.optional-dependencies] test` group is declared in `pyproject.toml`
only as documentation.)

- [ ] **Step 3: Create `tests/__init__.py`**

```python
```
(empty file)

- [ ] **Step 4: Write the failing config test** — `tests/test_config.py`

```python
from backend import config


def test_summarizer_defaults_present():
    assert isinstance(config.SUMMARIZER_MODEL, str) and config.SUMMARIZER_MODEL
    assert isinstance(config.SUMMARIZER_ENABLED, bool)
    assert isinstance(config.SUMMARIZER_VERSION, int)
    assert config.SUMMARIZER_MIN_CHARS > 0
```

- [ ] **Step 5: Run it, verify it fails**

Run: `.venv/bin/pytest tests/test_config.py -v`
Expected: FAIL with `AttributeError: module 'backend.config' has no attribute 'SUMMARIZER_MODEL'`.

- [ ] **Step 6: Add constants to `backend/config.py`**

Append after the rolling-memory line (around line 92):

```python
# Cheap LLM summarizer/tagger for post-processing passes.
SUMMARIZER_MODEL = os.getenv("COUNCIL_SUMMARIZER_MODEL", "openai/gpt-5-nano")
SUMMARIZER_ENABLED = _read_bool("COUNCIL_SUMMARIZER_ENABLED", True)
SUMMARIZER_VERSION = int(os.getenv("COUNCIL_SUMMARIZER_VERSION", "1"))
# User turns at/below this length with no code/pasted structure skip the LLM.
SUMMARIZER_MIN_CHARS = int(os.getenv("COUNCIL_SUMMARIZER_MIN_CHARS", "120"))
```

- [ ] **Step 7: Run test, verify pass**

Run: `.venv/bin/pytest tests/test_config.py -v`
Expected: PASS.

- [ ] **Step 8: Commit**

```bash
git add pyproject.toml backend/config.py tests/__init__.py tests/test_config.py
git commit -m "test: add pytest scaffolding and summarizer config constants"
```

> **Note for implementer:** Verify `openai/gpt-5-nano` is a live OpenRouter slug. If not, set the default to `google/gemini-2.5-flash`. This does not affect any test (all LLM calls are mocked).

---

### Task 2: Summarizer module — turn summary call + helpers

**Files:**
- Create: `backend/summarizer.py`
- Create: `tests/conftest.py`
- Create: `tests/test_summarizer.py`

**Interfaces:**
- Consumes: `config.SUMMARIZER_ENABLED`, `config.SUMMARIZER_MODEL`; `openrouter.query_model`; `usage.build_usage_request`.
- Produces:
  - `content_hash(text: str) -> str`
  - `parse_json_block(text: str) -> Any | None`
  - `async summarize_turn(role: str, content: str, stage3_response: str) -> dict | None` returning `{"summary": str, "usage": dict | None}` or `None`.

- [ ] **Step 1: Create `tests/conftest.py`**

```python
import pytest


@pytest.fixture
def enable_summarizer(monkeypatch):
    """Force the summarizer on regardless of env."""
    from backend import config
    monkeypatch.setattr(config, "SUMMARIZER_ENABLED", True)
    monkeypatch.setattr(config, "SUMMARIZER_MODEL", "test/model")
    return config
```

- [ ] **Step 2: Write failing tests** — `tests/test_summarizer.py`

```python
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
```

- [ ] **Step 3: Run tests, verify they fail**

Run: `.venv/bin/pytest tests/test_summarizer.py -v`
Expected: FAIL (`ModuleNotFoundError: No module named 'backend.summarizer'`).

- [ ] **Step 4: Create `backend/summarizer.py`**

```python
"""Cheap-LLM summarization and tagging for post-processing passes.

Each builder returns the same schema as its deterministic twin and never
raises; on any failure it returns None so callers fall back to deterministic.
"""

from __future__ import annotations

import hashlib
import json
import re
from typing import Any, Dict, List, Optional

from . import config
from .openrouter import query_model
from .usage import build_usage_request

TURN_SUMMARY_MAX_CHARS = 180
_TURN_TIMEOUT = 30.0


def content_hash(text: str) -> str:
    """Stable short hash of turn content for cache invalidation."""
    return hashlib.sha256((text or "").encode("utf-8")).hexdigest()[:16]


def parse_json_block(text: str) -> Optional[Any]:
    """Best-effort parse of a JSON object/array from a model content string."""
    if not text:
        return None
    candidate = text.strip()
    fence = re.search(r"```(?:json)?\s*(.+?)```", candidate, re.DOTALL)
    if fence:
        candidate = fence.group(1).strip()
    try:
        return json.loads(candidate)
    except (ValueError, TypeError):
        pass
    match = re.search(r"(\{.*\}|\[.*\])", candidate, re.DOTALL)
    if not match:
        return None
    try:
        return json.loads(match.group(1))
    except (ValueError, TypeError):
        return None


def _model() -> str:
    return config.SUMMARIZER_MODEL


def _enabled() -> bool:
    return bool(config.SUMMARIZER_ENABLED)


def _turn_prompt(role: str, content: str, stage3_response: str) -> str:
    if role == "assistant":
        body = stage3_response or content
        instruction = (
            "Summarize the council's answer below in one sentence (max 25 words). "
            "Capture the core conclusion, not the preamble."
        )
    else:
        body = content
        instruction = (
            "Summarize this user message in one sentence (max 25 words). "
            "Capture what they are actually asking for."
        )
    return f"{instruction}\n\nText:\n{body}\n\nSummary:"


async def summarize_turn(
    role: str, content: str, stage3_response: str
) -> Optional[Dict[str, Any]]:
    """One-line essence for a single turn, or None to fall back."""
    if not _enabled():
        return None
    model = _model()
    messages = [{"role": "user", "content": _turn_prompt(role, content, stage3_response)}]
    response = await query_model(model, messages, timeout=_TURN_TIMEOUT)
    if not response:
        return None
    summary = (response.get("content") or "").strip().strip('"\'')
    if not summary:
        return None
    if len(summary) > TURN_SUMMARY_MAX_CHARS:
        summary = summary[: TURN_SUMMARY_MAX_CHARS - 1].rstrip() + "…"
    return {
        "summary": summary,
        "usage": build_usage_request(
            kind="turn_summary", usage=response.get("usage"), model=model
        ),
    }
```

- [ ] **Step 5: Run tests, verify pass**

Run: `.venv/bin/pytest tests/test_summarizer.py -v`
Expected: PASS (6 tests).

- [ ] **Step 6: Commit**

```bash
git add backend/summarizer.py tests/conftest.py tests/test_summarizer.py
git commit -m "feat: add summarizer module with turn-summary LLM call"
```

---

### Task 3: Incremental turn index builder + worker wiring

**Files:**
- Modify: `backend/summarizer.py`
- Modify: `backend/worker.py:53-63`
- Create: `tests/test_turn_index.py`

**Interfaces:**
- Consumes: `postprocess.build_turn_index_entries`, `postprocess._is_probably_pasted_source`, `summarize_turn`, `content_hash`, `config.SUMMARIZER_VERSION`, `config.SUMMARIZER_MIN_CHARS`.
- Produces: `async build_llm_turn_index_entries(conversation: dict, existing_rows: list[dict], summarize_fn=summarize_turn) -> list[dict]`. Each entry keeps the deterministic schema plus `transcript_offset` carries `{"message_index": int, "summarizer_version": int, "source_hash": str}`.

- [ ] **Step 1: Write failing tests** — `tests/test_turn_index.py`

```python
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
```

- [ ] **Step 2: Run tests, verify they fail**

Run: `.venv/bin/pytest tests/test_turn_index.py -v`
Expected: FAIL (`AttributeError: module 'backend.summarizer' has no attribute 'build_llm_turn_index_entries'`).

- [ ] **Step 3: Add the builder to `backend/summarizer.py`**

Add imports at top (merge with existing): `from .postprocess import build_turn_index_entries, _is_probably_pasted_source`.

Append:

```python
def _message_source_text(message: Dict[str, Any]) -> str:
    """The text whose change should invalidate a cached turn summary."""
    if message.get("role") == "user":
        return message.get("content", "") or ""
    if message.get("error"):
        return f"error:{message.get('error', {}).get('message', '')}"
    return message.get("stage3", {}).get("response", "") or ""


def _should_use_llm_for_turn(message: Dict[str, Any]) -> bool:
    """Assistant/error turns and long/structured user turns use the LLM."""
    role = message.get("role")
    if role != "user":
        return bool(_message_source_text(message))
    content = message.get("content", "") or ""
    if _is_probably_pasted_source(content):
        return True
    return len(content.strip()) > config.SUMMARIZER_MIN_CHARS


def _existing_by_turn(existing_rows: List[Dict[str, Any]]) -> Dict[int, Dict[str, Any]]:
    return {row.get("turn_number"): row for row in existing_rows or []}


async def build_llm_turn_index_entries(
    conversation: Dict[str, Any],
    existing_rows: List[Dict[str, Any]],
    summarize_fn=None,
) -> List[Dict[str, Any]]:
    """Deterministic floor overlaid with cached/fresh LLM turn summaries."""
    # Resolve at call time so monkeypatching summarizer.summarize_turn works.
    summarize_fn = summarize_fn or summarize_turn
    entries = build_turn_index_entries(conversation)
    messages = conversation.get("messages", [])
    cache = _existing_by_turn(existing_rows)
    version = config.SUMMARIZER_VERSION

    for entry, message in zip(entries, messages):
        source_hash = content_hash(_message_source_text(message))
        entry["transcript_offset"] = {
            **entry.get("transcript_offset", {}),
            "summarizer_version": version,
            "source_hash": source_hash,
        }

        cached = cache.get(entry["turn_number"])
        if cached:
            cached_offset = cached.get("transcript_offset") or {}
            if (
                cached_offset.get("summarizer_version") == version
                and cached_offset.get("source_hash") == source_hash
                and cached.get("short_highlight")
            ):
                entry["short_highlight"] = cached["short_highlight"]
                continue

        if not _enabled() or not _should_use_llm_for_turn(message):
            continue  # keep deterministic floor

        result = await summarize_fn(
            message.get("role", "assistant"),
            message.get("content", "") or "",
            message.get("stage3", {}).get("response", "") or "",
        )
        if result and result.get("summary"):
            entry["short_highlight"] = result["summary"]

    return entries
```

- [ ] **Step 4: Run tests, verify pass**

Run: `.venv/bin/pytest tests/test_turn_index.py -v`
Expected: PASS (6 tests).

- [ ] **Step 5: Wire the worker `index_turns` job** — `backend/worker.py`

Replace the body of the `index_turns` branch (lines 53-63):

```python
    if job["job_type"] == "index_turns":
        existing_rows = postgres_store.get_conversation_turn_index(conversation_id)
        entries = await build_llm_turn_index_entries(conversation, existing_rows)
        if not postgres_store.replace_turn_index(conversation_id, entries):
            raise RuntimeError(f"Unable to replace turn index for {conversation_id}")

        logger.info(
            "stored_turn_index conversation_id=%s entries=%s",
            conversation_id,
            len(entries),
        )
        return
```

Update the import at the top of `worker.py`:

```python
from .postprocess import build_memory_record, build_turn_index_entries
from .summarizer import build_llm_turn_index_entries
```

- [ ] **Step 6: Run the full suite**

Run: `.venv/bin/pytest -q`
Expected: PASS (all tests so far).

- [ ] **Step 7: Commit**

```bash
git add backend/summarizer.py backend/worker.py tests/test_turn_index.py
git commit -m "feat: incremental LLM turn-index builder wired into worker"
```

---

### Task 4: LLM rolling memory

**Files:**
- Modify: `backend/postprocess.py:600-692` (extract render helper)
- Modify: `backend/summarizer.py`
- Modify: `backend/worker.py:30-51`
- Create: `tests/test_memory.py`

**Interfaces:**
- Consumes: `postprocess.build_memory_record`, `postprocess.render_memory_text`, `summarize_turn` output, `config.SUMMARIZER_ENABLED`.
- Produces:
  - `postprocess.render_memory_text(summary_json: dict, latest_stage3: str = "", max_tokens: int = DEFAULT_MEMORY_MAX_TOKENS) -> tuple[str, int]` (returns `summary_text`, `token_estimate`).
  - `async summarizer.summarize_memory(summary_json_seed: dict, turn_summaries: list[str]) -> dict | None` (returns a validated `summary_json` fields dict or None).
  - `async summarizer.build_llm_memory_record(conversation: dict, turn_summaries: list[str], max_tokens: int) -> dict` (same shape as `build_memory_record`).

- [ ] **Step 1: Write a characterization test for the refactor** — `tests/test_memory.py`

```python
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
```

- [ ] **Step 2: Run it, verify it fails**

Run: `.venv/bin/pytest tests/test_memory.py::test_render_memory_text_matches_build_record -v`
Expected: FAIL (`AttributeError: ... has no attribute 'render_memory_text'`).

- [ ] **Step 3: Extract `render_memory_text` in `backend/postprocess.py`**

Add this function above `build_memory_record`:

```python
def render_memory_text(
    summary_json: Dict[str, Any],
    latest_stage3: str = "",
    max_tokens: int = DEFAULT_MEMORY_MAX_TOKENS,
) -> tuple[str, int]:
    """Render the human-readable summary text + token estimate from fields."""
    lines = [
        "Conversation Memory",
        f"- Current goal: {summary_json.get('current_goal') or 'No current goal recorded.'}",
    ]
    if (
        summary_json.get("user_objective")
        and summary_json["user_objective"] != summary_json.get("current_goal")
    ):
        lines.append(f"- Original objective: {summary_json['user_objective']}")
    if summary_json.get("background_context_notes"):
        lines.append("- Background context:")
        lines.extend(f"  - {item}" for item in summary_json["background_context_notes"])
    if summary_json.get("stable_constraints"):
        lines.append("- Stable constraints:")
        lines.extend(f"  - {item}" for item in summary_json["stable_constraints"])
    if summary_json.get("recent_decisions"):
        lines.append("- Recent decisions:")
        lines.extend(f"  - {item}" for item in summary_json["recent_decisions"])
    if summary_json.get("open_threads"):
        lines.append("- Open threads:")
        lines.extend(f"  - {item}" for item in summary_json["open_threads"])
    if summary_json.get("active_bundle", {}).get("name"):
        lines.append(f"- Active bundle: {summary_json['active_bundle']['name']}")

    latest_verdict_anchor = _prepare_snippet(latest_stage3, 200) if latest_stage3 else ""
    if latest_verdict_anchor and latest_verdict_anchor not in summary_json.get("recent_decisions", []):
        lines.append(f"- Latest verdict anchor: {latest_verdict_anchor}")

    summary_text = "\n".join(lines)
    if len(summary_text) > DEFAULT_MEMORY_MAX_CHARS:
        summary_text = _clip_text(summary_text, DEFAULT_MEMORY_MAX_CHARS)
    token_estimate = _approx_token_estimate(summary_text)
    if token_estimate > max_tokens:
        summary_text = _clip_text(summary_text, max_tokens * 4)
        token_estimate = _approx_token_estimate(summary_text)
    return summary_text, token_estimate
```

Then replace the rendering block inside `build_memory_record` (the `lines = [...]` through the `token_estimate` recompute, lines ~640-685) with:

```python
    summary_text, token_estimate = render_memory_text(
        summary_json, latest_stage3_response, max_tokens
    )
    summary_json["token_estimate"] = token_estimate
```

Keep the existing `return {...}` block that follows.

- [ ] **Step 4: Run characterization test, verify pass**

Run: `.venv/bin/pytest tests/test_memory.py::test_render_memory_text_matches_build_record -v`
Expected: PASS.

- [ ] **Step 5: Write failing tests for the LLM memory builder** — append to `tests/test_memory.py`

```python
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


async def test_summarize_memory_rejects_missing_keys(enable_summarizer, monkeypatch):
    async def fake_query_model(model, messages, timeout=120.0, max_attempts=2):
        return {"content": '{"current_goal": "x"}', "usage": None}  # missing required keys
    monkeypatch.setattr(summarizer, "query_model", fake_query_model)
    assert await summarizer.summarize_memory({}, ["t1"]) is None
```

- [ ] **Step 6: Run, verify they fail**

Run: `.venv/bin/pytest tests/test_memory.py -v`
Expected: FAIL (`summarize_memory` / `build_llm_memory_record` undefined).

- [ ] **Step 7: Implement memory functions in `backend/summarizer.py`**

Add `from .postprocess import build_memory_record, render_memory_text, build_turn_index_entries, _is_probably_pasted_source` (merge with the existing postprocess import). Add constant near the top: `MEMORY_REQUIRED_KEYS = ("current_goal", "user_objective", "stable_constraints", "recent_decisions", "open_threads", "background_context_notes")`.

Append:

```python
_MEMORY_TIMEOUT = 30.0


def _memory_prompt(turn_summaries: List[str]) -> str:
    joined = "\n".join(f"- {line}" for line in turn_summaries if line)
    keys = ", ".join(MEMORY_REQUIRED_KEYS)
    return (
        "You maintain rolling memory for a multi-turn AI council conversation. "
        "From the ordered turn summaries below, output a JSON object with EXACTLY "
        f"these keys: {keys}. "
        "current_goal and user_objective are strings; the rest are arrays of short "
        "strings. Use [] for empty arrays and \"\" for empty strings. "
        "Output only the JSON.\n\nTurn summaries:\n"
        f"{joined}\n\nJSON:"
    )


async def summarize_memory(
    summary_json_seed: Dict[str, Any], turn_summaries: List[str]
) -> Optional[Dict[str, Any]]:
    """Return validated memory fields from the LLM, or None to fall back."""
    if not _enabled():
        return None
    model = _model()
    messages = [{"role": "user", "content": _memory_prompt(turn_summaries)}]
    response = await query_model(model, messages, timeout=_MEMORY_TIMEOUT)
    if not response:
        return None
    parsed = parse_json_block(response.get("content") or "")
    if not isinstance(parsed, dict):
        return None
    if not all(key in parsed for key in MEMORY_REQUIRED_KEYS):
        return None
    return parsed


async def build_llm_memory_record(
    conversation: Dict[str, Any],
    turn_summaries: List[str],
    max_tokens: int,
) -> Dict[str, Any]:
    """Deterministic memory record with LLM-filled fields when available."""
    record = build_memory_record(conversation, max_tokens=max_tokens)
    if not _enabled():
        return record

    fields = await summarize_memory(record["summary_json"], turn_summaries)
    if not fields:
        return record

    summary_json = {**record["summary_json"], **fields}
    latest_stage3 = next(
        (
            m.get("stage3", {}).get("response", "")
            for m in reversed(conversation.get("messages", []))
            if m.get("role") == "assistant" and m.get("stage3", {}).get("response")
        ),
        "",
    )
    summary_text, token_estimate = render_memory_text(summary_json, latest_stage3, max_tokens)
    summary_json["token_estimate"] = token_estimate
    return {
        "summary_text": summary_text,
        "summary_json": summary_json,
        "token_estimate": token_estimate,
        "source_turn_count": record["source_turn_count"],
    }
```

- [ ] **Step 8: Run memory tests, verify pass**

Run: `.venv/bin/pytest tests/test_memory.py -v`
Expected: PASS (4 tests).

- [ ] **Step 9: Wire the worker `refresh_memory` job** — `backend/worker.py`

Add a helper near the top of `worker.py` (after imports):

```python
def _turn_summary_lines(conversation_id: str) -> list:
    rows = postgres_store.get_conversation_turn_index(conversation_id)
    return [row.get("short_highlight", "") for row in rows if row.get("short_highlight")]
```

Replace the `refresh_memory` branch body (lines 30-51) so it builds via the LLM:

```python
    if job["job_type"] == "refresh_memory":
        turn_summaries = _turn_summary_lines(conversation_id)
        memory_record = await build_llm_memory_record(
            conversation,
            turn_summaries,
            max_tokens=ROLLING_MEMORY_MAX_TOKENS,
        )
        version = postgres_store.store_conversation_memory(
            conversation_id,
            memory_record["summary_text"],
            memory_record["summary_json"],
            memory_record["token_estimate"],
            memory_record["source_turn_count"],
        )
        if version is None:
            raise RuntimeError(f"Unable to store rolling memory for {conversation_id}")

        logger.info(
            "stored_memory conversation_id=%s version=%s token_estimate=%s",
            conversation_id,
            version,
            memory_record["token_estimate"],
        )
        return
```

Update the summarizer import in `worker.py`:

```python
from .summarizer import build_llm_turn_index_entries, build_llm_memory_record
```

- [ ] **Step 10: Run full suite**

Run: `.venv/bin/pytest -q`
Expected: PASS.

- [ ] **Step 11: Commit**

```bash
git add backend/postprocess.py backend/summarizer.py backend/worker.py tests/test_memory.py
git commit -m "feat: LLM rolling memory with deterministic fallback"
```

---

### Task 5: LLM entity/theme tagging

**Files:**
- Modify: `backend/entity_extraction.py:142-187`
- Modify: `backend/summarizer.py`
- Modify: `backend/worker.py:89-99`
- Create: `tests/test_tagging.py`

**Interfaces:**
- Consumes: `entity_extraction.build_exact_entities`, `entity_extraction.build_inferred_entities`, `entity_extraction.build_conversation_entities`, `config.SUMMARIZER_ENABLED`.
- Produces:
  - `entity_extraction.build_exact_entities(conversation: dict) -> list[dict]` (bundle + model only).
  - `entity_extraction.build_inferred_entities(conversation: dict) -> list[dict]` (capitalized + theme regex, unchanged behavior).
  - `async summarizer.extract_tags(turn_summaries: list[str], memory_text: str) -> list[dict] | None` (entity/theme dicts).
  - `async summarizer.build_llm_conversation_entities(conversation: dict, turn_summaries: list[str], memory_text: str) -> list[dict]`.

- [ ] **Step 1: Write characterization + behavior tests** — `tests/test_tagging.py`

```python
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
```

- [ ] **Step 2: Run, verify they fail**

Run: `.venv/bin/pytest tests/test_tagging.py -v`
Expected: FAIL (`build_exact_entities` undefined).

- [ ] **Step 3: Split `build_conversation_entities` in `backend/entity_extraction.py`**

Replace `build_conversation_entities` (lines 142-187) with three functions that preserve behavior:

```python
def _new_collector():
    seen = set()
    entities: List[Dict[str, Any]] = []

    def add_entity(entity_type: str, canonical_name: str, link_type: str, metadata: Dict[str, Any]):
        normalized_name = canonical_name.strip()
        if not normalized_name:
            return
        key = (entity_type, normalized_name.lower(), link_type)
        if key in seen:
            return
        seen.add(key)
        entities.append(
            {
                "entity_type": entity_type,
                "canonical_name": normalized_name,
                "link_type": link_type,
                "metadata": metadata,
            }
        )

    return entities, add_entity


def build_exact_entities(conversation: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Bundle and model links derived from exact message metadata."""
    entities, add_entity = _new_collector()
    for bundle_name in sorted(set(_iter_message_bundles(conversation))):
        add_entity("bundle", bundle_name, "uses_bundle", {"source": "message_bundle"})
    for model_id in sorted(set(_iter_model_ids(conversation))):
        add_entity("model", model_id, "mentions_model", {"source": "message_metadata"})
    return entities


def build_inferred_entities(conversation: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Capitalized entities and theme keywords from summary text (deterministic)."""
    entities, add_entity = _new_collector()
    summary_texts = _summary_text_sources(conversation)
    for name, metadata in _extract_capitalized_entities(conversation.get("title", ""), summary_texts):
        add_entity("entity", name, "mentioned", metadata)
    for theme, metadata in _extract_theme_terms(summary_texts):
        add_entity("theme", theme, "theme", metadata)
    return entities


def build_conversation_entities(conversation: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Deterministic entity/theme links for one conversation (exact + inferred)."""
    entities, add_entity = _new_collector()
    for entity in build_exact_entities(conversation) + build_inferred_entities(conversation):
        add_entity(entity["entity_type"], entity["canonical_name"], entity["link_type"], entity["metadata"])
    return entities
```

- [ ] **Step 4: Run tagging characterization tests, verify pass**

Run: `.venv/bin/pytest tests/test_tagging.py::test_exact_plus_inferred_equals_original tests/test_tagging.py::test_exact_entities_have_no_inferred_types -v`
Expected: PASS.

- [ ] **Step 5: Add tag functions to `backend/summarizer.py`**

Add `from .entity_extraction import build_exact_entities, build_inferred_entities` and `_TAG_TIMEOUT = 30.0`.

Append:

```python
_VALID_TAG_TYPES = {"entity", "theme"}
_VALID_TAG_KEYS = {"entity_type", "canonical_name", "link_type"}


def _tags_prompt(turn_summaries: List[str], memory_text: str) -> str:
    joined = "\n".join(f"- {line}" for line in turn_summaries if line)
    return (
        "Extract the salient named entities and recurring themes from this "
        "conversation. Return a JSON array of objects, each with keys "
        '"entity_type" ("entity" for proper nouns/projects/products, "theme" for '
        'topic keywords), "canonical_name", and "link_type" ("mentioned" for '
        'entities, "theme" for themes). Max 12 items. Output only the JSON array.'
        f"\n\nMemory:\n{memory_text}\n\nTurn summaries:\n{joined}\n\nJSON:"
    )


def _coerce_tag(item: Any) -> Optional[Dict[str, Any]]:
    if not isinstance(item, dict):
        return None
    if not _VALID_TAG_KEYS.issubset(item.keys()):
        return None
    entity_type = item["entity_type"]
    name = (item.get("canonical_name") or "").strip()
    if entity_type not in _VALID_TAG_TYPES or not name:
        return None
    link_type = item["link_type"] if item["link_type"] in {"mentioned", "theme"} else (
        "mentioned" if entity_type == "entity" else "theme"
    )
    return {
        "entity_type": entity_type,
        "canonical_name": name,
        "link_type": link_type,
        "metadata": {"source": "llm"},
    }


async def extract_tags(
    turn_summaries: List[str], memory_text: str
) -> Optional[List[Dict[str, Any]]]:
    """LLM entity/theme tags, or None to fall back to deterministic."""
    if not _enabled():
        return None
    model = _model()
    messages = [{"role": "user", "content": _tags_prompt(turn_summaries, memory_text)}]
    response = await query_model(model, messages, timeout=_TAG_TIMEOUT)
    if not response:
        return None
    parsed = parse_json_block(response.get("content") or "")
    if not isinstance(parsed, list):
        return None
    tags = [coerced for coerced in (_coerce_tag(item) for item in parsed) if coerced]
    return tags or None


async def build_llm_conversation_entities(
    conversation: Dict[str, Any],
    turn_summaries: List[str],
    memory_text: str,
) -> List[Dict[str, Any]]:
    """Exact bundle/model links plus LLM (or deterministic) entity/theme tags."""
    entities, add_entity = _entity_collector()
    for entity in build_exact_entities(conversation):
        add_entity(entity)

    inferred = None
    if _enabled():
        inferred = await extract_tags(turn_summaries, memory_text)
    if inferred is None:
        inferred = build_inferred_entities(conversation)

    for entity in inferred:
        add_entity(entity)
    return entities


def _entity_collector():
    seen = set()
    entities: List[Dict[str, Any]] = []

    def add_entity(entity: Dict[str, Any]):
        name = (entity.get("canonical_name") or "").strip()
        if not name:
            return
        key = (entity["entity_type"], name.lower(), entity["link_type"])
        if key in seen:
            return
        seen.add(key)
        entities.append(entity)

    return entities, add_entity
```

- [ ] **Step 6: Run tagging tests, verify pass**

Run: `.venv/bin/pytest tests/test_tagging.py -v`
Expected: PASS (5 tests).

- [ ] **Step 7: Wire the worker `extract_entities` job** — `backend/worker.py`

Replace the `extract_entities` branch body (lines 89-99):

```python
    if job["job_type"] == "extract_entities":
        turn_summaries = _turn_summary_lines(conversation_id)
        memory = postgres_store.get_latest_conversation_memory(conversation_id) or {}
        memory_text = memory.get("summary_text", "") if isinstance(memory, dict) else ""
        entities = await build_llm_conversation_entities(
            conversation, turn_summaries, memory_text
        )
        if not postgres_store.replace_conversation_entities(conversation_id, entities):
            raise RuntimeError(f"Unable to store extracted entities for {conversation_id}")

        logger.info(
            "stored_entities conversation_id=%s entities=%s",
            conversation_id,
            len(entities),
        )
        return
```

Update imports in `worker.py`:

```python
from .entity_extraction import build_conversation_entities
from .summarizer import (
    build_llm_turn_index_entries,
    build_llm_memory_record,
    build_llm_conversation_entities,
)
```

- [ ] **Step 8: Run full suite**

Run: `.venv/bin/pytest -q`
Expected: PASS (all tests).

- [ ] **Step 9: Commit**

```bash
git add backend/entity_extraction.py backend/summarizer.py backend/worker.py tests/test_tagging.py
git commit -m "feat: LLM entity/theme tagging with deterministic fallback"
```

---

### Task 6: End-to-end worker smoke test + manual verification

**Files:**
- Create: `tests/test_worker_jobs.py`

**Interfaces:**
- Consumes: `worker.process_job`, monkeypatched `postgres_store` + `storage` + `summarizer` calls.

- [ ] **Step 1: Write the worker smoke test** — `tests/test_worker_jobs.py`

```python
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
    monkeypatch.setattr(postgres_store, "store_conversation_memory", lambda *a: 1)
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

    assert stub_storage["turns"][1]["short_highlight"] == "ESSENCE"
    assert any(e["canonical_name"] == "csv import" for e in stub_storage["entities"])
```

> **Why this works:** `build_llm_memory_record` / `build_llm_conversation_entities` call `summarize_memory(...)` / `extract_tags(...)` as module-level names, and `build_llm_turn_index_entries` resolves `summarize_fn or summarize_turn` at call time (Task 3 fix), so `monkeypatch.setattr(summarizer, ...)` reaches all three.

- [ ] **Step 2: Run the worker tests, verify pass**

Run: `.venv/bin/pytest tests/test_worker_jobs.py -v`
Expected: PASS (2 tests).

- [ ] **Step 3: Run the full suite**

Run: `.venv/bin/pytest -q`
Expected: PASS (all tests).

- [ ] **Step 4: Manual verification against a real model (optional but recommended)**

With `OPENROUTER_API_KEY` set and `COUNCIL_SUMMARIZER_MODEL` pointed at the verified slug, run a quick script from repo root:

```bash
.venv/bin/python -c "
import asyncio
from backend import summarizer
print(asyncio.run(summarizer.summarize_turn('assistant', '', 'The council recommends streaming the CSV row by row using the standard library to avoid memory blowups on large files.')))
"
```
Expected: a one-sentence essence printed (confirms slug + connectivity). If it errors or returns None, fix the slug in config before shipping.

- [ ] **Step 5: Commit**

```bash
git add tests/test_worker_jobs.py
git commit -m "test: end-to-end worker job coverage for summarizer passes"
```

---

## Self-Review

**Spec coverage:**
- Config (model/enabled/version/min_chars) → Task 1. ✓
- `summarizer.py` with 3 passes → Tasks 2,4,5. ✓
- Incremental per-turn caching (version + hash in `transcript_offset`) → Task 3. ✓
- Skip LLM for very-short user turns; assistant always → Task 3 (`_should_use_llm_for_turn`). ✓
- `stage3_excerpt` stays verbatim → unchanged (builder overlays only `short_highlight`). ✓
- Memory consumes cached turn summaries; same `summary_json` keys → Task 4. ✓
- Tagging keeps bundle/model deterministic, replaces entity/theme → Task 5. ✓
- Graceful degradation + `SUMMARIZER_ENABLED=False` global → every builder + Task 6 disabled test. ✓
- Usage wrapping via `build_usage_request` → Tasks 2 (turn). Memory/tags calls also return usage-bearing responses; their builders don't currently surface usage upward (worker logs only). Acceptable per spec ("log it now"). Turn-summary usage is attached but not yet persisted — consistent with the spec's "minimum: log" stance.

**Note on the spec's open items:** `get_conversation_turn_index` already returns `transcript_offset`, so no SELECT change is needed (spec item resolved). The `gpt-5-nano` slug verification is folded into Task 1's note and Task 6 Step 5.

**Placeholder scan:** No TBD/TODO; all code shown. ✓

**Type consistency:** `summarize_turn` returns `{"summary","usage"}` (Task 2) consumed in Task 3; `summarize_memory` returns fields dict consumed in Task 4; `extract_tags` returns list[dict] consumed in Task 5; worker imports updated cumulatively across Tasks 3/4/5. The Task 6 late-binding fix amends Task 3's signature — implementer applies it when reaching Task 6 (or proactively in Task 3). ✓
