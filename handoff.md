# Deliberati — Handoff

_Last updated against HEAD `1960aca` (Merge feature/llm-summarization-tagging)._

Read `docs/implementation-plan.md` and `docs/architecture.md` first, then inspect:
`backend/main.py`, `backend/storage.py`, `backend/postgres_store.py`, `backend/worker.py`,
`backend/semantic_search.py`, `backend/entity_extraction.py`, `backend/summarizer.py`,
`backend/postprocess.py`, `frontend/src/App.jsx`, `frontend/src/components/Sidebar.jsx`,
`frontend/src/components/ChatInterface.jsx`.

## Current repo status

- Worktree clean; on `master`, pushed to `origin/master`.
- HEAD `1960aca`. `feature/llm-summarization-tagging` is **merged and closed** (branch deleted; nothing unmerged).
- `pytest` green: **24 passed**.
- Already implemented and stable: auth, ownership isolation, worker retry/coalescing/priority,
  owner-scoped exports, startup flow, first-pass deployment docs.
- Do not reopen finished architecture/auth/summarization work unless you find a concrete bug.

## Done in the last cycle (LLM summarization & tagging)

- `backend/summarizer.py` — turn-summary LLM call + incremental turn-index builder, wired into the worker.
- LLM rolling memory with deterministic fallback.
- LLM entity/theme tagging with deterministic fallback (`entity_extraction.py`, `postprocess.py`).
- Test suite added (`tests/test_summarizer.py`, `test_tagging.py`, `test_memory.py`,
  `test_turn_index.py`, `test_worker_jobs.py`, `test_config.py`).

## Outstanding (release roadmap)

1. **Semantic search** — still lexical over canonical transcript JSON; no embeddings (explicitly not
   required for first public release). Frontend search UX improvement still open
   (`docs/implementation-plan.md` items at search section). Decide sidebar-only vs main-workspace surface.
2. **Entity / theme extraction** — model-driven path now exists (LLM tagging + deterministic fallback).
   Still open: canonicalization/noise quality, whether the layer is user-facing vs metadata-only, and a
   re-evaluation of cross-user isolation now that ownership exists.
3. **local-llm container integration** — still **undecided / not wired**. Summarizer/tagging use the
   LLM-via-API path with deterministic fallback. The optional `local-llm` compose service is modeled in
   `docker-compose.example.yml` but not implemented. Make the deferred-vs-implement call explicit in docs.
4. **Release / deployment cleanup** — `start.sh`, `setup.sh`, `Dockerfile`,
   `docker-compose.example.yml`, `docs/unraid-deployment.md` all present. NOT verified this cycle:
   fresh-clone `./start.sh` smoke test, `docker compose -f docker-compose.example.yml up --build` smoke
   test, and Unraid Community Apps template metadata (not finalized). No in-app export-browsing UI yet.

## Constraints

- Keep the worktree clean; keep `docs/implementation-plan.md` in sync with reality as you go.
- Prefer narrowing scope cleanly over leaving ambiguous half-features.
- Verify with real commands, not just reasoning. Don't rewrite unrelated areas.
- Keep ownership boundaries airtight for any entity/search work.
