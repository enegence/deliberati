# Turn Bar Freshness + Per-Turn Stage Navigator Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** (1) Fix the turn bar (turn index in the overview panel) not updating after a follow-up message until hard refresh; (2) add a semi-transparent per-turn stage navigation overlay on the right side of the transcript viewer that jumps between the question, model responses (Stage 1), peer rankings (Stage 2), and final verdict (Stage 3).

**Architecture:** The turn-bar bug is a backend issue: after a follow-up, `GET /api/conversations/{id}/overview` returns the *stored* (now stale) turn index and reports `turn_index_pending=false`, so the frontend's 3-second poll loop (App.jsx:678) never starts. Fix by (a) merging freshly derived turn entries over the stored index so new turns appear immediately, and (b) reporting `pending=true` whenever a worker job is active or the stored index lags the transcript. The stage navigator is a new self-contained React component (`StageNavigator.jsx`) with its pure logic split into `stageNavModel.js` for unit testing; it anchors to new per-stage element IDs added in `ChatInterface.jsx`.

**Tech Stack:** FastAPI + pytest (backend, `uv` managed), React 19 + Vite (frontend). Frontend currently has **no test runner** — Task 4 installs vitest + @testing-library/react.

## Global Constraints

- Backend runs on port **8001**; frontend dev server on 5173. Run backend as `python -m backend.main` from project root (relative imports).
- Backend tests: `uv run pytest tests/ -v` from project root. `asyncio_mode = "auto"` is configured, so async test functions need no decorator. If pytest is missing, run `uv sync --extra test` first.
- Frontend tests (after Task 4): `cd frontend && npm test`.
- Frontend is plain JavaScript/JSX — **no TypeScript**.
- Match existing code style exactly (existing files use 2-space JSX indent, 4-space Python indent). Do not reformat or "improve" adjacent code.
- Do not modify anything under `data/` (live conversation transcripts).
- In frontend tests, import vitest APIs explicitly (`import { describe, it, expect, vi } from 'vitest'`) — globals are not enabled.
- Every commit message uses conventional-commit prefixes (`fix:`, `feat:`, `test:`, `chore:`) matching repo history.

## Background: the bug, precisely

Data flow after a follow-up message:

1. Frontend `handleSendMessage` (App.jsx:951) streams the council run; on stream end it calls `refreshConversationPanels` (App.jsx:1162) → `GET /overview`.
2. Backend `send_message_stream` enqueues an `index_turns` worker job via `enqueue_postprocess_jobs` (main.py:441). The worker processes it seconds-to-minutes later.
3. `GET /overview` (main.py:791) calls `maybe_enqueue_overview_backfill` (main.py:231). At main.py:282, `turn_index_pending` is computed **only when the stored index is missing or "generic-stale"**. After a follow-up, a stored index *exists* (from earlier turns), so `turn_index_pending` stays `false` even though an `index_turns` job is active.
4. `serialize_conversation_overview` (main.py:194-217) prefers the stored index over the freshly derived one, so the response's `turn_index` is missing the two new turns.
5. Frontend receives stale turns + `turn_index_pending=false`; the poll effect (App.jsx:678) never fires. Turn bar frozen until the user reloads (by which time the worker has finished).

Fix = backend only. No frontend change needed for the bug; the existing poll loop does the rest once the pending flag is truthful.

---

### Task 1: `merge_turn_index_entries` helper in postprocess.py

**Files:**
- Modify: `backend/postprocess.py` (add function after `build_turn_index_entries`, which ends at line ~731)
- Test: `tests/test_turn_index_merge.py` (new)

**Interfaces:**
- Consumes: nothing new. Turn-index entry shape (see `build_turn_index_entries`, postprocess.py:696): `{turn_number, role, created_at, short_highlight, stage3_excerpt, transcript_offset: {message_index}}`.
- Produces: `merge_turn_index_entries(stored_entries: List[dict], derived_entries: List[dict]) -> List[dict]` — used by Task 2.

- [ ] **Step 1: Write the failing test**

Create `tests/test_turn_index_merge.py`:

```python
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_turn_index_merge.py -v`
Expected: FAIL with `ImportError: cannot import name 'merge_turn_index_entries'`

- [ ] **Step 3: Write minimal implementation**

In `backend/postprocess.py`, add directly after the `build_turn_index_entries` function:

```python
def merge_turn_index_entries(
    stored_entries: List[Dict[str, Any]],
    derived_entries: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """Prefer stored (worker-written) entries; fill missing turns from derived.

    The derived index always covers the full transcript, so it governs length.
    """
    stored_by_turn = {entry["turn_number"]: entry for entry in stored_entries}
    return [
        stored_by_turn.get(entry["turn_number"], entry)
        for entry in derived_entries
    ]
```

(`List`, `Dict`, `Any` are already imported at the top of postprocess.py — verify, do not duplicate imports.)

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_turn_index_merge.py -v`
Expected: 4 PASSED

- [ ] **Step 5: Run the full backend suite to check for regressions**

Run: `uv run pytest tests/ -v`
Expected: all PASS

- [ ] **Step 6: Commit**

```bash
git add backend/postprocess.py tests/test_turn_index_merge.py
git commit -m "feat: add merge_turn_index_entries to overlay stored turn index on derived"
```

---

### Task 2: Overview serialization merges stored + derived turn index

**Files:**
- Modify: `backend/main.py:194-217` (inside `serialize_conversation_overview`) and the import block at main.py:30-34
- Test: `tests/test_overview_freshness.py` (new)

**Interfaces:**
- Consumes: `merge_turn_index_entries(stored, derived)` from Task 1.
- Produces: `serialize_conversation_overview(conversation_id, conversation)` now returns a `turn_index` covering **every** transcript message even when the stored index lags. Also adds module-level helper `serialize_turn_index_entry(entry: dict) -> dict` in main.py.

- [ ] **Step 1: Write the failing test**

Create `tests/test_overview_freshness.py`:

```python
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_overview_freshness.py -v`
Expected: `test_overview_turn_index_includes_new_turns_when_stored_lags` FAILS with `assert 2 == 4` (stored index is returned as-is today). The second test should already pass.

- [ ] **Step 3: Implement**

In `backend/main.py`, extend the postprocess import (main.py:30-34):

```python
from .postprocess import (
    MEMORY_FORMAT_VERSION,
    build_memory_record,
    build_turn_index_entries,
    merge_turn_index_entries,
)
```

Add a module-level helper directly above `serialize_conversation_overview` (main.py:160):

```python
def serialize_turn_index_entry(entry: Dict[str, Any]) -> Dict[str, Any]:
    """Normalize created_at to an ISO string (stored rows carry datetimes)."""
    created_at = entry.get("created_at")
    if hasattr(created_at, "isoformat"):
        created_at = created_at.isoformat()
    return {**entry, "created_at": created_at}
```

Then inside `serialize_conversation_overview`, replace the block at main.py:202-217 (the `if stored_turn_index and not stored_turn_index_looks_generic:` / `else:` construction of `turn_index`) with:

```python
    usable_stored_index = (
        stored_turn_index
        if stored_turn_index and not stored_turn_index_looks_generic
        else []
    )
    turn_index = [
        serialize_turn_index_entry(entry)
        for entry in merge_turn_index_entries(usable_stored_index, derived_turn_index)
    ]
```

Leave the `stored_turn_index_looks_generic` computation (main.py:194-200) untouched.

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_overview_freshness.py -v`
Expected: 2 PASSED

- [ ] **Step 5: Run full backend suite**

Run: `uv run pytest tests/ -v`
Expected: all PASS

- [ ] **Step 6: Commit**

```bash
git add backend/main.py tests/test_overview_freshness.py
git commit -m "fix: overview turn index covers new turns while worker job is in flight"
```

---

### Task 3: Truthful `turn_index_pending` / `memory_pending` flags

**Files:**
- Modify: `backend/main.py:231-323` (`maybe_enqueue_overview_backfill`)
- Test: `tests/test_overview_freshness.py` (append)

**Interfaces:**
- Consumes: `postgres_store.has_active_export_job(conversation_id, job_type)`, `postgres_store.enqueue_export_job(...)` — existing.
- Produces: `maybe_enqueue_overview_backfill(conversation) -> {"memory_pending": bool, "turn_index_pending": bool}` where each flag is `True` whenever a matching worker job is **active**, not only when a backfill was just enqueued. Also enqueues `index_turns` when the stored index lags the transcript.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_overview_freshness.py`:

```python
class _EnqueueRecorder:
    def __init__(self):
        self.calls = []

    def __call__(self, conversation_id, job_type, payload):
        self.calls.append(job_type)
        return True


def _patch_backfill_environment(
    monkeypatch,
    *,
    stored_turns,
    active_job_types=(),
    memory_current=True,
):
    recorder = _EnqueueRecorder()
    monkeypatch.setattr(main.postgres_store, "is_configured", lambda: True)
    monkeypatch.setattr(
        main.postgres_store, "sync_conversation_metadata", lambda conv, path: None
    )
    monkeypatch.setattr(
        main.storage, "get_conversation_path", lambda cid: f"/tmp/{cid}.json"
    )
    monkeypatch.setattr(
        main.postgres_store,
        "get_latest_conversation_memory",
        lambda cid: (
            {"summary_json": {"format_version": main.MEMORY_FORMAT_VERSION}}
            if memory_current
            else None
        ),
    )
    monkeypatch.setattr(
        main.postgres_store,
        "get_conversation_turn_index",
        lambda cid: _stored_entries(stored_turns),
    )
    monkeypatch.setattr(
        main.postgres_store,
        "has_active_export_job",
        lambda cid, job_type: job_type in active_job_types,
    )
    monkeypatch.setattr(main.postgres_store, "enqueue_export_job", recorder)
    monkeypatch.setattr(main.postgres_store, "has_semantic_chunks", lambda cid: True)
    monkeypatch.setattr(
        main.postgres_store, "has_conversation_entity_links", lambda cid: True
    )
    monkeypatch.setattr(
        main.markdown_exports, "conversation_exports_missing", lambda cid: False
    )
    return recorder


def test_pending_true_while_index_job_active_even_with_stored_index(monkeypatch):
    # The exact follow-up scenario: stored index exists but a worker job is running.
    recorder = _patch_backfill_environment(
        monkeypatch, stored_turns=2, active_job_types=("index_turns",)
    )

    pending = main.maybe_enqueue_overview_backfill(_conversation(4))

    assert pending["turn_index_pending"] is True
    assert "index_turns" not in recorder.calls  # active job -> no duplicate enqueue


def test_lagging_stored_index_triggers_enqueue(monkeypatch):
    recorder = _patch_backfill_environment(monkeypatch, stored_turns=2)

    pending = main.maybe_enqueue_overview_backfill(_conversation(4))

    assert pending["turn_index_pending"] is True
    assert "index_turns" in recorder.calls


def test_complete_stored_index_reports_not_pending(monkeypatch):
    recorder = _patch_backfill_environment(monkeypatch, stored_turns=4)

    pending = main.maybe_enqueue_overview_backfill(_conversation(4))

    assert pending["turn_index_pending"] is False
    assert "index_turns" not in recorder.calls


def test_memory_pending_true_while_refresh_job_active(monkeypatch):
    _patch_backfill_environment(
        monkeypatch, stored_turns=4, active_job_types=("refresh_memory",)
    )

    pending = main.maybe_enqueue_overview_backfill(_conversation(4))

    assert pending["memory_pending"] is True
```

- [ ] **Step 2: Run tests to verify the new ones fail**

Run: `uv run pytest tests/test_overview_freshness.py -v`
Expected: `test_pending_true_while_index_job_active_even_with_stored_index`, `test_lagging_stored_index_triggers_enqueue`, and `test_memory_pending_true_while_refresh_job_active` FAIL (pending flags come back `False` today). `test_complete_stored_index_reports_not_pending` passes already.

- [ ] **Step 3: Implement**

In `backend/main.py`, inside `maybe_enqueue_overview_backfill`, replace the memory block (main.py:259-271) with:

```python
    latest_memory = postgres_store.get_latest_conversation_memory(conversation_id)
    memory_is_stale = bool(
        latest_memory
        and latest_memory.get("summary_json", {}).get("format_version") != MEMORY_FORMAT_VERSION
    )
    memory_pending = postgres_store.has_active_export_job(conversation_id, "refresh_memory")
    if not memory_pending and (latest_memory is None or memory_is_stale):
        memory_pending = postgres_store.enqueue_export_job(
            conversation_id,
            "refresh_memory",
            payload,
        )
```

and replace the turn-index block (main.py:273-289) with:

```python
    stored_turn_index = postgres_store.get_conversation_turn_index(conversation_id)
    has_turn_index = bool(stored_turn_index)
    derived_turn_index = build_turn_index_entries(conversation)
    turn_index_is_stale = bool(
        stored_turn_index
        and derived_turn_index
        and stored_turn_index[0].get("short_highlight", "").startswith(GENERIC_PASTED_SUMMARY_PREFIXES)
        and stored_turn_index[0].get("short_highlight") != derived_turn_index[0].get("short_highlight")
    )
    turn_index_is_lagging = len(stored_turn_index) < len(derived_turn_index)
    turn_index_pending = postgres_store.has_active_export_job(conversation_id, "index_turns")
    if not turn_index_pending and (not has_turn_index or turn_index_is_stale or turn_index_is_lagging):
        turn_index_pending = postgres_store.enqueue_export_job(
            conversation_id,
            "index_turns",
            payload,
        )
```

Note the change: `derived_turn_index` is now computed unconditionally (previously only when `has_turn_index` was true), and the initial `memory_pending = False` / `turn_index_pending = False` assignments at main.py:250-251 become dead — delete those two lines.

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_overview_freshness.py -v`
Expected: 6 PASSED

- [ ] **Step 5: Run full backend suite**

Run: `uv run pytest tests/ -v`
Expected: all PASS

- [ ] **Step 6: Commit**

```bash
git add backend/main.py tests/test_overview_freshness.py
git commit -m "fix: report pending overview state while index/memory worker jobs are active"
```

**Why this fixes the user-visible bug:** immediately after a follow-up, the overview response now (a) contains the new turns (Task 2's merge) so the turn bar updates on the very first `refreshConversationPanels` call, and (b) reports `turn_index_pending=true` while the worker runs, so the existing App.jsx:678 poll loop keeps refreshing until the LLM-quality highlights land. No frontend change required.

---

### Task 4: Frontend test infrastructure (vitest + Testing Library)

**Files:**
- Modify: `frontend/package.json` (add `test` script + dev deps via npm)
- Modify: `frontend/vite.config.js`
- Create: `frontend/src/test/setup.js`
- Test: `frontend/src/test/smoke.test.jsx`

**Interfaces:**
- Produces: `npm test` (one-shot) and `npm run test:watch` commands; jsdom environment; `@testing-library/jest-dom` matchers; a `scrollIntoView` stub (jsdom does not implement it). All later frontend tasks rely on this.

- [ ] **Step 1: Install dev dependencies**

```bash
cd frontend
npm install -D vitest jsdom @testing-library/react @testing-library/jest-dom @testing-library/user-event
```

- [ ] **Step 2: Configure vitest**

Replace `frontend/vite.config.js` with:

```js
import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],
  test: {
    environment: 'jsdom',
    setupFiles: './src/test/setup.js',
  },
})
```

Create `frontend/src/test/setup.js`:

```js
import '@testing-library/jest-dom/vitest';

// jsdom does not implement scrollIntoView; components under test call it.
if (!window.HTMLElement.prototype.scrollIntoView) {
  window.HTMLElement.prototype.scrollIntoView = () => {};
}
```

In `frontend/package.json`, add to `"scripts"`:

```json
    "test": "vitest run",
    "test:watch": "vitest"
```

(If the installed vitest version does not pick up the `test` block from `vite.config.js`, change the config's first line to `import { defineConfig } from 'vitest/config'` — same object shape, no other changes.)

- [ ] **Step 3: Write the smoke test**

Create `frontend/src/test/smoke.test.jsx`:

```jsx
import { describe, it, expect } from 'vitest';
import { render, screen } from '@testing-library/react';

describe('test harness', () => {
  it('renders JSX into jsdom', () => {
    render(<div>harness works</div>);
    expect(screen.getByText('harness works')).toBeInTheDocument();
  });
});
```

- [ ] **Step 4: Run and verify**

Run: `cd frontend && npm test`
Expected: 1 passed

Also run: `npm run lint` — expected: no new errors (if eslint flags the test file for undefined globals, that means vitest APIs were not imported explicitly; fix the imports rather than enabling globals).

- [ ] **Step 5: Commit**

```bash
git add frontend/package.json frontend/package-lock.json frontend/vite.config.js frontend/src/test/setup.js frontend/src/test/smoke.test.jsx
git commit -m "chore: add vitest + testing-library harness for frontend"
```

---

### Task 5: Pure navigation model — `stageNavModel.js`

**Files:**
- Create: `frontend/src/components/stageNavModel.js`
- Test: `frontend/src/components/__tests__/stageNavModel.test.js`

**Interfaces:**
- Consumes: conversation `messages` array as held in App state: user messages `{role: 'user', content, created_at}`; assistant messages `{role: 'assistant', stage1, stage2, stage3, error, loading}` where each stage is null until complete.
- Produces (used by Tasks 6-9):
  - `STAGE_LABELS` — `{prompt: 'Question', stage1: 'Responses', stage2: 'Rankings', stage3: 'Verdict'}`
  - `buildStageAnchorId(messageIndex: number, stageKey: string) -> string` — `'conversation-message-{i}'` for `'prompt'`, `'conversation-message-{i}-{stageKey}'` otherwise.
  - `buildStageNavModel(messages) -> Array<{turnNumber, promptIndex, responseIndex, stages: Array<{key, label, messageIndex, anchorId}>}>`
  - `findActiveTurnIndex(navModel, anchorTops: Map<string, number>, viewportTop: number) -> number`

- [ ] **Step 1: Write the failing tests**

Create `frontend/src/components/__tests__/stageNavModel.test.js`:

```js
import { describe, it, expect } from 'vitest';
import {
  buildStageAnchorId,
  buildStageNavModel,
  findActiveTurnIndex,
} from '../stageNavModel';

const fullAssistant = {
  role: 'assistant',
  stage1: [{ model: 'm/a', response: 'r' }],
  stage2: [{ model: 'm/a', ranking: 'FINAL RANKING:\n1. Response A' }],
  stage3: { model: 'm/chair', response: 'final' },
};

describe('buildStageAnchorId', () => {
  it('uses the message anchor for prompts and suffixed anchors for stages', () => {
    expect(buildStageAnchorId(0, 'prompt')).toBe('conversation-message-0');
    expect(buildStageAnchorId(3, 'stage2')).toBe('conversation-message-3-stage2');
  });
});

describe('buildStageNavModel', () => {
  it('pairs a user prompt with its assistant stages as one turn', () => {
    const model = buildStageNavModel([
      { role: 'user', content: 'q1' },
      fullAssistant,
    ]);
    expect(model).toHaveLength(1);
    expect(model[0].turnNumber).toBe(1);
    expect(model[0].promptIndex).toBe(0);
    expect(model[0].responseIndex).toBe(1);
    expect(model[0].stages.map((s) => s.key)).toEqual([
      'prompt', 'stage1', 'stage2', 'stage3',
    ]);
    expect(model[0].stages[2].anchorId).toBe('conversation-message-1-stage2');
  });

  it('creates one entry per question in a multi-turn conversation', () => {
    const model = buildStageNavModel([
      { role: 'user', content: 'q1' },
      fullAssistant,
      { role: 'user', content: 'q2' },
      fullAssistant,
    ]);
    expect(model).toHaveLength(2);
    expect(model[1].turnNumber).toBe(2);
    expect(model[1].promptIndex).toBe(2);
    expect(model[1].stages[1].anchorId).toBe('conversation-message-3-stage1');
  });

  it('omits stages that have not completed yet', () => {
    const model = buildStageNavModel([
      { role: 'user', content: 'q1' },
      { role: 'assistant', stage1: [{ model: 'm/a', response: 'r' }], stage2: null, stage3: null },
    ]);
    expect(model[0].stages.map((s) => s.key)).toEqual(['prompt', 'stage1']);
  });

  it('handles an in-flight turn with no assistant stages yet', () => {
    const model = buildStageNavModel([
      { role: 'user', content: 'q1' },
    ]);
    expect(model).toHaveLength(1);
    expect(model[0].stages.map((s) => s.key)).toEqual(['prompt']);
  });

  it('returns an empty model for empty or missing messages', () => {
    expect(buildStageNavModel([])).toEqual([]);
    expect(buildStageNavModel(undefined)).toEqual([]);
  });
});

describe('findActiveTurnIndex', () => {
  const navModel = buildStageNavModel([
    { role: 'user', content: 'q1' },
    fullAssistant,
    { role: 'user', content: 'q2' },
    fullAssistant,
  ]);

  it('picks the last turn whose first anchor has scrolled to/above the viewport top', () => {
    const tops = new Map([
      ['conversation-message-0', -300],
      ['conversation-message-2', -10],
    ]);
    expect(findActiveTurnIndex(navModel, tops, 0)).toBe(1);
  });

  it('stays on the first turn before any scrolling', () => {
    const tops = new Map([
      ['conversation-message-0', 40],
      ['conversation-message-2', 900],
    ]);
    expect(findActiveTurnIndex(navModel, tops, 0)).toBe(0);
  });

  it('ignores anchors with no measured position', () => {
    expect(findActiveTurnIndex(navModel, new Map(), 0)).toBe(0);
  });
});
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd frontend && npx vitest run src/components/__tests__/stageNavModel.test.js`
Expected: FAIL — cannot resolve `../stageNavModel`

- [ ] **Step 3: Implement**

Create `frontend/src/components/stageNavModel.js`:

```js
export const STAGE_LABELS = {
  prompt: 'Question',
  stage1: 'Responses',
  stage2: 'Rankings',
  stage3: 'Verdict',
};

const ASSISTANT_STAGE_KEYS = ['stage1', 'stage2', 'stage3'];

export function buildStageAnchorId(messageIndex, stageKey) {
  return stageKey === 'prompt'
    ? `conversation-message-${messageIndex}`
    : `conversation-message-${messageIndex}-${stageKey}`;
}

function buildStage(stageKey, messageIndex) {
  return {
    key: stageKey,
    label: STAGE_LABELS[stageKey],
    messageIndex,
    anchorId: buildStageAnchorId(messageIndex, stageKey),
  };
}

export function buildStageNavModel(messages) {
  const turns = [];
  let currentTurn = null;

  (messages || []).forEach((message, messageIndex) => {
    if (message.role === 'user') {
      currentTurn = {
        turnNumber: turns.length + 1,
        promptIndex: messageIndex,
        responseIndex: null,
        stages: [buildStage('prompt', messageIndex)],
      };
      turns.push(currentTurn);
      return;
    }

    if (!currentTurn || currentTurn.responseIndex !== null) {
      currentTurn = {
        turnNumber: turns.length + 1,
        promptIndex: null,
        responseIndex: null,
        stages: [],
      };
      turns.push(currentTurn);
    }

    currentTurn.responseIndex = messageIndex;
    ASSISTANT_STAGE_KEYS.forEach((stageKey) => {
      if (message[stageKey]) {
        currentTurn.stages.push(buildStage(stageKey, messageIndex));
      }
    });
  });

  return turns;
}

export function findActiveTurnIndex(navModel, anchorTops, viewportTop) {
  let activeIndex = 0;

  navModel.forEach((turn, turnIndex) => {
    const firstStage = turn.stages[0];
    if (!firstStage) {
      return;
    }

    const top = anchorTops.get(firstStage.anchorId);
    if (typeof top === 'number' && top <= viewportTop + 8) {
      activeIndex = turnIndex;
    }
  });

  return activeIndex;
}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd frontend && npx vitest run src/components/__tests__/stageNavModel.test.js`
Expected: all PASS

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/stageNavModel.js frontend/src/components/__tests__/stageNavModel.test.js
git commit -m "feat: add pure stage navigation model for per-turn jumping"
```

---

### Task 6: Per-stage anchor IDs in the transcript

**Files:**
- Modify: `frontend/src/components/ChatInterface.jsx` (the three stage cards inside `renderTranscript`, around lines 1095-1148)
- Create: `frontend/src/components/__tests__/fixtures.jsx` (shared test fixtures — reused by Tasks 8 and 9)
- Test: `frontend/src/components/__tests__/ChatInterface.anchors.test.jsx`

**Interfaces:**
- Consumes: the anchor ID convention from Task 5 (`conversation-message-{i}-stage{n}`); existing message anchor `conversation-message-{i}` (ChatInterface.jsx:1033) stays unchanged.
- Produces: DOM ids on the Stage 1/2/3 cards that StageNavigator (Task 7) targets. Also produces `conversationFixture` and `buildBaseProps(overrides)` in `fixtures.jsx` for Tasks 8-9.

- [ ] **Step 1: Create the shared fixtures and write the failing test**

Create `frontend/src/components/__tests__/fixtures.jsx` (a plain module, not a test file — the name must NOT match `*.test.*` so vitest does not try to run it):

```jsx
export const conversationFixture = {
  id: 'conv-1',
  title: 'Test conversation',
  created_at: '2026-07-01T00:00:00Z',
  messages: [
    { role: 'user', content: 'What is the answer?', created_at: '2026-07-01T00:00:00Z' },
    {
      role: 'assistant',
      created_at: '2026-07-01T00:01:00Z',
      stage1: [{ model: 'm/a', response: 'Response body' }],
      stage2: [{ model: 'm/a', ranking: 'FINAL RANKING:\n1. Response A', parsed_ranking: ['Response A'] }],
      stage3: { model: 'm/chair', response: 'The final verdict.' },
    },
  ],
};

export function buildBaseProps(overrides = {}) {
  return {
    conversation: conversationFixture,
    conversationSelected: true,
    conversationOverview: null,
    conversationEntities: null,
    workbookItems: [],
    requestedJumpTarget: null,
    activeSearchMatch: null,
    onSendMessage: () => {},
    onLoadTranscript: () => {},
    onClipSelectionsToWorkbook: () => {},
    onUpdateWorkbookItem: () => {},
    onDeleteWorkbookItem: () => {},
    isLoading: false,
    isOverviewLoading: false,
    overviewError: '',
    isEntitiesLoading: false,
    entitiesError: '',
    isTranscriptLoading: false,
    modelBundles: [],
    selectedBundleId: '',
    onSelectBundle: () => {},
    ...overrides,
  };
}
```

Then create `frontend/src/components/__tests__/ChatInterface.anchors.test.jsx`:

```jsx
import { describe, it, expect } from 'vitest';
import { render } from '@testing-library/react';
import ChatInterface from '../ChatInterface';
import { conversationFixture, buildBaseProps } from './fixtures.jsx';

describe('transcript stage anchors', () => {
  it('exposes ids for the message and each completed stage', () => {
    render(<ChatInterface {...buildBaseProps()} />);
    expect(document.getElementById('conversation-message-0')).not.toBeNull();
    expect(document.getElementById('conversation-message-1-stage1')).not.toBeNull();
    expect(document.getElementById('conversation-message-1-stage2')).not.toBeNull();
    expect(document.getElementById('conversation-message-1-stage3')).not.toBeNull();
  });

  it('omits stage anchors that have not completed', () => {
    const loadingConversation = {
      ...conversationFixture,
      messages: [
        conversationFixture.messages[0],
        { role: 'assistant', created_at: '2026-07-01T00:01:00Z', stage1: null, stage2: null, stage3: null, loading: { stage1: true, stage2: false, stage3: false } },
      ],
    };
    render(<ChatInterface {...buildBaseProps({ conversation: loadingConversation })} />);
    expect(document.getElementById('conversation-message-1-stage1')).toBeNull();
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend && npx vitest run src/components/__tests__/ChatInterface.anchors.test.jsx`
Expected: first test FAILS (`conversation-message-1-stage1` is null); second passes.

- [ ] **Step 3: Implement**

In `frontend/src/components/ChatInterface.jsx`, add an `id` attribute to each of the three stage card divs. Stage 1 card (currently ~line 1095):

```jsx
                  {message.stage1 && (
                    <div
                      id={`conversation-message-${index}-stage1`}
                      className={`stage-selectable-card selectable-card ${getIsSegmentSelected(`segment:${index}:stage1`) ? 'selected' : ''}`}
```

Stage 2 card (currently ~line 1113):

```jsx
                  {message.stage2 && (
                    <div
                      id={`conversation-message-${index}-stage2`}
                      className={`stage-selectable-card selectable-card ${getIsSegmentSelected(`segment:${index}:stage2`) ? 'selected' : ''}`}
```

Stage 3 card (currently ~line 1135):

```jsx
                  {message.stage3 && (
                    <div
                      id={`conversation-message-${index}-stage3`}
                      className={`stage-selectable-card selectable-card ${getIsSegmentSelected(`segment:${index}:stage3`) ? 'selected' : ''}`}
```

Only the `id={...}` lines are new; everything else stays byte-identical.

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd frontend && npx vitest run src/components/__tests__/ChatInterface.anchors.test.jsx`
Expected: 2 PASSED

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/ChatInterface.jsx frontend/src/components/__tests__/fixtures.jsx frontend/src/components/__tests__/ChatInterface.anchors.test.jsx
git commit -m "feat: add per-stage anchor ids to transcript stage cards"
```

---

### Task 7: `StageNavigator` overlay component

**Files:**
- Create: `frontend/src/components/StageNavigator.jsx`
- Create: `frontend/src/components/StageNavigator.css`
- Test: `frontend/src/components/__tests__/StageNavigator.test.jsx`

**Interfaces:**
- Consumes: `buildStageNavModel`, `findActiveTurnIndex` from Task 5; anchor elements from Task 6 (looked up with `document.getElementById`).
- Produces: `<StageNavigator messages={messages} scrollContainerRef={ref} />` — default export. `scrollContainerRef` is a React ref to the scrolling element (`.conversation-panel-scroll`, wired in Task 8). Renders `<nav aria-label="Turn and stage navigation">` or `null` when there are no turns.

- [ ] **Step 1: Write the failing tests**

Create `frontend/src/components/__tests__/StageNavigator.test.jsx`:

```jsx
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { useRef } from 'react';
import { render, screen, fireEvent } from '@testing-library/react';
import StageNavigator from '../StageNavigator';

const fullAssistant = {
  role: 'assistant',
  stage1: [{ model: 'm/a', response: 'r' }],
  stage2: [{ model: 'm/a', ranking: 'FINAL RANKING:\n1. Response A' }],
  stage3: { model: 'm/chair', response: 'final' },
};

const twoTurnMessages = [
  { role: 'user', content: 'q1' },
  fullAssistant,
  { role: 'user', content: 'q2' },
  fullAssistant,
];

function Harness({ messages }) {
  const scrollRef = useRef(null);
  return (
    <div>
      <div ref={scrollRef} data-testid="scroll-container">
        {messages.map((message, index) => (
          <div key={index}>
            <div id={`conversation-message-${index}`} />
            {message.role === 'assistant' && (
              <>
                <div id={`conversation-message-${index}-stage1`} />
                <div id={`conversation-message-${index}-stage2`} />
                <div id={`conversation-message-${index}-stage3`} />
              </>
            )}
          </div>
        ))}
      </div>
      <StageNavigator messages={messages} scrollContainerRef={scrollRef} />
    </div>
  );
}

beforeEach(() => {
  // Fresh stub each test so per-element spies below don't leak between tests.
  window.HTMLElement.prototype.scrollIntoView = vi.fn();
});

describe('StageNavigator', () => {
  it('renders nothing when there are no messages', () => {
    render(<Harness messages={[]} />);
    expect(screen.queryByRole('navigation')).toBeNull();
  });

  it('shows stage buttons for the active turn', () => {
    render(<Harness messages={[twoTurnMessages[0], twoTurnMessages[1]]} />);
    expect(screen.getByRole('navigation', { name: 'Turn and stage navigation' })).toBeInTheDocument();
    expect(screen.getByText('Turn 1/1')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Question' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Responses' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Rankings' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Verdict' })).toBeInTheDocument();
  });

  it('scrolls to the matching stage anchor on click', () => {
    render(<Harness messages={[twoTurnMessages[0], twoTurnMessages[1]]} />);
    const stage2Anchor = document.getElementById('conversation-message-1-stage2');
    stage2Anchor.scrollIntoView = vi.fn();
    fireEvent.click(screen.getByRole('button', { name: 'Rankings' }));
    expect(stage2Anchor.scrollIntoView).toHaveBeenCalledTimes(1);
  });

  it('starts on the last turn in jsdom and moves back with the previous arrow', () => {
    // jsdom reports every rect at top 0, so the mount-time measurement marks
    // the LAST turn active (all anchors read as "at or above" the viewport top).
    render(<Harness messages={twoTurnMessages} />);
    expect(screen.getByText('Turn 2/2')).toBeInTheDocument();

    const turn1Prompt = document.getElementById('conversation-message-0');
    turn1Prompt.scrollIntoView = vi.fn();
    fireEvent.click(screen.getByRole('button', { name: 'Previous turn' }));
    expect(screen.getByText('Turn 1/2')).toBeInTheDocument();
    expect(turn1Prompt.scrollIntoView).toHaveBeenCalledTimes(1);
  });

  it('tracks the active turn from scroll position', () => {
    render(<Harness messages={twoTurnMessages} />);
    expect(screen.getByText('Turn 2/2')).toBeInTheDocument(); // jsdom mount state, see above

    const container = screen.getByTestId('scroll-container');
    container.getBoundingClientRect = () => ({ top: 0 });
    // Both prompts sit BELOW the viewport top -> turn 1 becomes active again.
    document.getElementById('conversation-message-0').getBoundingClientRect = () => ({ top: 40 });
    document.getElementById('conversation-message-2').getBoundingClientRect = () => ({ top: 900 });

    fireEvent.scroll(container);
    expect(screen.getByText('Turn 1/2')).toBeInTheDocument();
  });
});
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd frontend && npx vitest run src/components/__tests__/StageNavigator.test.jsx`
Expected: FAIL — cannot resolve `../StageNavigator`

- [ ] **Step 3: Implement the component**

Create `frontend/src/components/StageNavigator.jsx`:

```jsx
import { useEffect, useMemo, useState } from 'react';
import { buildStageNavModel, findActiveTurnIndex } from './stageNavModel';
import './StageNavigator.css';

export default function StageNavigator({ messages, scrollContainerRef }) {
  const navModel = useMemo(() => buildStageNavModel(messages), [messages]);
  const [activeTurnIndex, setActiveTurnIndex] = useState(0);

  useEffect(() => {
    const container = scrollContainerRef?.current;
    if (!container || navModel.length === 0) {
      return undefined;
    }

    const handleScroll = () => {
      const containerTop = container.getBoundingClientRect().top;
      const anchorTops = new Map();
      navModel.forEach((turn) => {
        const firstStage = turn.stages[0];
        if (!firstStage) {
          return;
        }
        const element = document.getElementById(firstStage.anchorId);
        if (element) {
          anchorTops.set(firstStage.anchorId, element.getBoundingClientRect().top);
        }
      });
      setActiveTurnIndex(findActiveTurnIndex(navModel, anchorTops, containerTop));
    };

    handleScroll();
    container.addEventListener('scroll', handleScroll, { passive: true });
    return () => container.removeEventListener('scroll', handleScroll);
  }, [scrollContainerRef, navModel]);

  if (navModel.length === 0) {
    return null;
  }

  const clampedIndex = Math.min(activeTurnIndex, navModel.length - 1);
  const activeTurn = navModel[clampedIndex];

  const jumpToAnchor = (anchorId) => {
    document.getElementById(anchorId)?.scrollIntoView({ behavior: 'smooth', block: 'start' });
  };

  const goToTurn = (turnIndex) => {
    const turn = navModel[turnIndex];
    if (!turn || turn.stages.length === 0) {
      return;
    }
    setActiveTurnIndex(turnIndex);
    jumpToAnchor(turn.stages[0].anchorId);
  };

  return (
    <nav className="stage-navigator" aria-label="Turn and stage navigation">
      <div className="stage-navigator-turn-row">
        <button
          type="button"
          className="stage-navigator-arrow"
          onClick={() => goToTurn(clampedIndex - 1)}
          disabled={clampedIndex === 0}
          aria-label="Previous turn"
        >
          ▲
        </button>
        <span className="stage-navigator-turn-label">
          Turn {activeTurn.turnNumber}/{navModel.length}
        </span>
        <button
          type="button"
          className="stage-navigator-arrow"
          onClick={() => goToTurn(clampedIndex + 1)}
          disabled={clampedIndex >= navModel.length - 1}
          aria-label="Next turn"
        >
          ▼
        </button>
      </div>
      <div className="stage-navigator-stages">
        {activeTurn.stages.map((stage) => (
          <button
            key={stage.anchorId}
            type="button"
            className={`stage-navigator-stage stage-navigator-stage-${stage.key}`}
            onClick={() => jumpToAnchor(stage.anchorId)}
          >
            {stage.label}
          </button>
        ))}
      </div>
    </nav>
  );
}
```

Create `frontend/src/components/StageNavigator.css`:

```css
.stage-navigator {
  position: absolute;
  top: 14px;
  right: 18px;
  z-index: 30;
  display: flex;
  flex-direction: column;
  gap: 6px;
  padding: 8px;
  border-radius: 10px;
  background: rgba(255, 255, 255, 0.78);
  border: 1px solid rgba(0, 0, 0, 0.08);
  box-shadow: 0 4px 14px rgba(0, 0, 0, 0.06);
  backdrop-filter: blur(6px);
  opacity: 0.45;
  transition: opacity 0.15s ease;
  font-size: 12px;
  user-select: none;
}

.stage-navigator:hover,
.stage-navigator:focus-within {
  opacity: 1;
}

.stage-navigator-turn-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 6px;
}

.stage-navigator-turn-label {
  font-weight: 600;
  color: #444;
  white-space: nowrap;
}

.stage-navigator-arrow {
  border: none;
  background: transparent;
  cursor: pointer;
  padding: 2px 6px;
  border-radius: 6px;
  color: #555;
  font-size: 10px;
  line-height: 1;
}

.stage-navigator-arrow:hover:not(:disabled) {
  background: rgba(0, 0, 0, 0.06);
}

.stage-navigator-arrow:disabled {
  opacity: 0.3;
  cursor: default;
}

.stage-navigator-stages {
  display: flex;
  flex-direction: column;
  gap: 3px;
}

.stage-navigator-stage {
  border: none;
  background: transparent;
  cursor: pointer;
  text-align: left;
  padding: 4px 8px;
  border-radius: 6px;
  color: #333;
  font-size: 12px;
  line-height: 1.2;
}

.stage-navigator-stage:hover {
  background: rgba(74, 144, 226, 0.12);
  color: #2b6cb8;
}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd frontend && npx vitest run src/components/__tests__/StageNavigator.test.jsx`
Expected: 5 PASSED

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/StageNavigator.jsx frontend/src/components/StageNavigator.css frontend/src/components/__tests__/StageNavigator.test.jsx
git commit -m "feat: add StageNavigator overlay for per-turn stage jumping"
```

---

### Task 8: Mount StageNavigator in ChatInterface

**Files:**
- Modify: `frontend/src/components/ChatInterface.jsx` (imports at top; refs near line 571; JSX around line 1596)
- Modify: `frontend/src/components/ChatInterface.css` (`.conversation-panel-body` rule, line ~698)
- Test: `frontend/src/components/__tests__/ChatInterface.navigator.test.jsx`

**Interfaces:**
- Consumes: `StageNavigator` (Task 7); test fixtures `buildBaseProps` from `frontend/src/components/__tests__/fixtures.jsx` (Task 6).
- Produces: the overlay visible in conversation view when a transcript with messages is loaded; hidden in workbook view and when no transcript is loaded.

- [ ] **Step 1: Write the failing test**

Create `frontend/src/components/__tests__/ChatInterface.navigator.test.jsx`:

```jsx
import { describe, it, expect } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import ChatInterface from '../ChatInterface';
import { buildBaseProps } from './fixtures.jsx';

describe('ChatInterface stage navigator integration', () => {
  it('shows the navigator in conversation view when a transcript is loaded', () => {
    render(<ChatInterface {...buildBaseProps()} />);
    expect(
      screen.getByRole('navigation', { name: 'Turn and stage navigation' })
    ).toBeInTheDocument();
  });

  it('hides the navigator when no transcript is loaded', () => {
    render(<ChatInterface {...buildBaseProps({ conversation: null })} />);
    expect(
      screen.queryByRole('navigation', { name: 'Turn and stage navigation' })
    ).toBeNull();
  });

  it('hides the navigator in workbook view', async () => {
    const user = userEvent.setup();
    render(<ChatInterface {...buildBaseProps()} />);
    await user.click(screen.getByRole('tab', { name: 'Workbook' }));
    expect(
      screen.queryByRole('navigation', { name: 'Turn and stage navigation' })
    ).toBeNull();
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend && npx vitest run src/components/__tests__/ChatInterface.navigator.test.jsx`
Expected: first test FAILS (no navigation landmark rendered).

- [ ] **Step 3: Implement**

In `frontend/src/components/ChatInterface.jsx`:

1. Add the import next to the other component imports at the top:

```jsx
import StageNavigator from './StageNavigator';
```

2. Add a ref for the scrolling element, next to the existing refs (near line 571, after `const transcriptScrollRef = useRef(null);`):

```jsx
  const panelScrollRef = useRef(null);
```

3. Change the panel body JSX (currently line ~1596):

```jsx
            <div ref={transcriptScrollRef} className="conversation-panel-body">
              {viewMode === 'conversation' && conversation?.messages?.length > 0 && (
                <StageNavigator
                  messages={conversation.messages}
                  scrollContainerRef={panelScrollRef}
                />
              )}
              <div ref={panelScrollRef} className="conversation-panel-scroll">
```

(The navigator sits inside `.conversation-panel-body` but **outside** `.conversation-panel-scroll` — the scroll container — so it stays pinned while the transcript scrolls under it.)

4. In `frontend/src/components/ChatInterface.css`, add `position: relative;` to the existing `.conversation-panel-body` rule (line ~698):

```css
.conversation-panel-body {
  position: relative;
  flex: 1 1 auto;
  min-height: 0;
  overflow: hidden;
}
```

- [ ] **Step 4: Run all frontend tests**

Run: `cd frontend && npm test`
Expected: all PASS (smoke, stageNavModel, anchors, StageNavigator, navigator integration)

- [ ] **Step 5: Lint and build**

Run: `cd frontend && npm run lint && npm run build`
Expected: no errors

- [ ] **Step 6: Commit**

```bash
git add frontend/src/components/ChatInterface.jsx frontend/src/components/ChatInterface.css frontend/src/components/__tests__/ChatInterface.navigator.test.jsx
git commit -m "feat: mount stage navigator overlay in conversation view"
```

---

### Task 9 (OPTIONAL — user said "maybe"): Stage links in the expanded turn bar

Skip this task if time or budget is constrained; Tasks 1-8 fully deliver the requested outcome. Implement only after Tasks 1-8 are complete and green.

**Files:**
- Modify: `frontend/src/components/ChatInterface.jsx` (turn index list, lines ~1390-1416; jump handlers near line 873; refs near line 567)
- Modify: `frontend/src/components/ChatInterface.css` (append new rules)
- Test: `frontend/src/components/__tests__/ChatInterface.turnIndexLinks.test.jsx`

**Interfaces:**
- Consumes: `buildStageAnchorId` from Task 5; overview `turn_index` entries `{turn_number, role, created_at, short_highlight, transcript_offset: {message_index}}`.
- Produces: Responses / Rankings / Verdict mini-links under each assistant entry in the expanded turn index that scroll to the stage anchor (loading the transcript first if needed).

- [ ] **Step 1: Write the failing test**

Create `frontend/src/components/__tests__/ChatInterface.turnIndexLinks.test.jsx`:

```jsx
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import ChatInterface from '../ChatInterface';
import { buildBaseProps } from './fixtures.jsx';

const overviewFixture = {
  conversation_id: 'conv-1',
  title: 'Test conversation',
  message_count: 2,
  memory: null,
  memory_pending: false,
  turn_index_pending: false,
  turn_index: [
    {
      turn_number: 1,
      role: 'user',
      created_at: '2026-07-01T00:00:00Z',
      short_highlight: 'What is the answer?',
      transcript_offset: { message_index: 0 },
    },
    {
      turn_number: 2,
      role: 'assistant',
      created_at: '2026-07-01T00:01:00Z',
      short_highlight: 'The final verdict.',
      transcript_offset: { message_index: 1 },
    },
  ],
};

beforeEach(() => {
  window.localStorage.clear(); // overview must start expanded
  window.HTMLElement.prototype.scrollIntoView = vi.fn();
});

describe('turn index stage links', () => {
  it('renders stage links for assistant entries only', () => {
    render(<ChatInterface {...buildBaseProps({ conversationOverview: overviewFixture })} />);
    expect(screen.getByRole('button', { name: 'Jump to turn 2 rankings' })).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Jump to turn 1 rankings' })).toBeNull();
  });

  it('scrolls to the stage anchor when a link is clicked', () => {
    render(<ChatInterface {...buildBaseProps({ conversationOverview: overviewFixture })} />);
    const stage2Anchor = document.getElementById('conversation-message-1-stage2');
    stage2Anchor.scrollIntoView = vi.fn();
    fireEvent.click(screen.getByRole('button', { name: 'Jump to turn 2 rankings' }));
    expect(stage2Anchor.scrollIntoView).toHaveBeenCalledTimes(1);
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend && npx vitest run src/components/__tests__/ChatInterface.turnIndexLinks.test.jsx`
Expected: FAIL — no button named "Jump to turn 2 rankings"

- [ ] **Step 3: Implement**

In `frontend/src/components/ChatInterface.jsx`:

1. Add import at the top:

```jsx
import { STAGE_LABELS, buildStageAnchorId } from './stageNavModel';
```

2. Add a ref next to the other refs (near line 567):

```jsx
  const pendingJumpAnchorRef = useRef(null);
```

3. Add handlers after `handleTurnJumpSelection` (near line 900):

```jsx
  const scrollToStageAnchor = (anchorId, fallbackMessageIndex) => {
    const element = document.getElementById(anchorId)
      || document.getElementById(`conversation-message-${fallbackMessageIndex}`);
    element?.scrollIntoView({ behavior: 'smooth', block: 'start' });
  };

  const handleStageJump = async (entry, stageKey) => {
    const messageIndex = entry.transcript_offset?.message_index;
    if (typeof messageIndex !== 'number') {
      return;
    }

    const anchorId = buildStageAnchorId(messageIndex, stageKey);
    if (!conversation) {
      pendingJumpAnchorRef.current = { anchorId, messageIndex };
      await onLoadTranscript();
      return;
    }

    scrollToStageAnchor(anchorId, messageIndex);
  };
```

4. Add an effect after the existing pending-jump effect (lines 723-731):

```jsx
  useEffect(() => {
    if (!pendingJumpAnchorRef.current || !conversation) {
      return;
    }

    const { anchorId, messageIndex } = pendingJumpAnchorRef.current;
    pendingJumpAnchorRef.current = null;
    scrollToStageAnchor(anchorId, messageIndex);
  }, [conversation]);
```

5. Restructure the expanded turn list items (lines ~1391-1415). The `<button className="overview-turn">` is itself a button, so stage links **cannot nest inside it** (invalid HTML). Wrap each entry in a shell div:

```jsx
                        {turnIndex.map((entry) => {
                          const messageIndex = entry.transcript_offset?.message_index;
                          const isSelected = typeof messageIndex === 'number' && getIsTurnSelected(messageIndex);
                          return (
                            <div key={`${entry.turn_number}-${entry.role}`} className="overview-turn-shell">
                              <button
                                className={`overview-turn ${isSelected ? 'selected' : ''}`}
                                type="button"
                                onClick={(event) => handleTurnJumpSelection(entry, event)}
                              >
                                <div className="overview-turn-meta">
                                  <span className={`overview-turn-role overview-turn-role-${entry.role}`}>
                                    {entry.role}
                                  </span>
                                  <span>Turn {entry.turn_number}</span>
                                  {formatTurnTimestamp(entry.created_at) && (
                                    <span className="overview-turn-timestamp">
                                      {formatTurnTimestamp(entry.created_at)}
                                    </span>
                                  )}
                                </div>
                                <div className="overview-turn-highlight">{entry.short_highlight}</div>
                              </button>
                              {entry.role === 'assistant' && (
                                <div className="overview-turn-stage-links">
                                  {['stage1', 'stage2', 'stage3'].map((stageKey) => (
                                    <button
                                      key={stageKey}
                                      type="button"
                                      className="overview-turn-stage-link"
                                      aria-label={`Jump to turn ${entry.turn_number} ${STAGE_LABELS[stageKey].toLowerCase()}`}
                                      onClick={() => handleStageJump(entry, stageKey)}
                                    >
                                      {STAGE_LABELS[stageKey]}
                                    </button>
                                  ))}
                                </div>
                              )}
                            </div>
                          );
                        })}
```

6. Append to `frontend/src/components/ChatInterface.css`:

```css
.overview-turn-shell {
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.overview-turn-stage-links {
  display: flex;
  gap: 4px;
  padding: 0 4px 4px;
}

.overview-turn-stage-link {
  border: none;
  background: transparent;
  cursor: pointer;
  font-size: 11px;
  color: #4a90e2;
  padding: 2px 6px;
  border-radius: 5px;
}

.overview-turn-stage-link:hover {
  background: rgba(74, 144, 226, 0.12);
}
```

- [ ] **Step 4: Run all frontend tests**

Run: `cd frontend && npm test`
Expected: all PASS

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/ChatInterface.jsx frontend/src/components/ChatInterface.css frontend/src/components/__tests__/ChatInterface.turnIndexLinks.test.jsx
git commit -m "feat: add stage jump links to expanded turn index entries"
```

---

### Task 10: Full verification and manual QA

**Files:** none (verification only)

- [ ] **Step 1: Full automated suites**

```bash
uv run pytest tests/ -v
cd frontend && npm test && npm run lint && npm run build
```

Expected: everything passes, build succeeds.

- [ ] **Step 2: Manual QA — turn bar freshness**

Start the app (`./start.sh` from project root launches backend on 8001 and frontend on 5173; requires `OPENROUTER_API_KEY` and `DATABASE_URL` in `.env`). Then:

1. Open an existing conversation (or create one and ask a question).
2. Send a **follow-up** question and wait for the council run to finish.
3. **Without refreshing**, confirm the two new turns (your question + council answer) appear in the turn index within ~3 seconds of the run completing. Highlights may first show as deterministic snippets and then upgrade to LLM summaries as the worker finishes — both states must show the correct number of turns.
4. Confirm the collapsed turn-chip strip also shows the new numbered chips without a refresh.

- [ ] **Step 3: Manual QA — stage navigator**

1. In a conversation with at least two council turns, confirm a faint overlay appears at the top-right of the transcript and becomes fully opaque on hover.
2. Click Question / Responses / Rankings / Verdict — the transcript scrolls smoothly to the matching section.
3. Scroll the transcript manually — the overlay's "Turn N/M" label follows the turn under the viewport top.
4. Use ▲/▼ to move between turns; ▲ disabled on turn 1, ▼ disabled on the last turn.
5. Switch to Workbook view — overlay disappears; switch back — it returns.
6. If Task 9 was done: in the expanded overview panel, click "Rankings" under an assistant turn entry and confirm the transcript scrolls to that turn's Stage 2 card (also test from a long conversation where the transcript starts collapsed — it should load the transcript, then scroll).

- [ ] **Step 4: Commit the plan document (if not already committed)**

```bash
git add docs/superpowers/plans/2026-07-07-turn-bar-freshness-and-stage-navigator.md
git commit -m "docs: add turn bar freshness + stage navigator implementation plan"
```
