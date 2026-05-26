# LLM Council Architecture

This document describes the target architecture for running LLM Council as a Dockerized app on Unraid without changing the council's core behavior.

## Goals

- Keep council orchestration latency on the web app request path only.
- Keep raw transcripts as the source of truth on persistent storage.
- Move memory, indexing, markdown export, and semantic search into asynchronous background work.
- Support a future local summarizer or embedding model without making the council dependent on it.

## Runtime Topology

Recommended container layout:

- `webapp`
  Runs FastAPI and serves the built frontend.
- `worker`
  Runs asynchronous post-processing jobs:
  rolling memory refresh, timestamped highlights, markdown export, semantic chunking, entity/theme extraction.
- `postgres`
  Stores metadata, rolling memory, export jobs, and future semantic search indexes.
- `local-llm` optional
  A local model endpoint such as Ollama for cheap summarization and indexing jobs.

The `webapp` and `worker` can share the same image and differ only by startup command.

## Data Contracts

Each conversation is intentionally split into three artifacts:

- `transcript`
  Raw source of truth stored on disk as JSON.
- `memory`
  A compact rolling summary for follow-up prompting.
- `index/export`
  Searchable markdown, semantic chunks, timestamps, themes, entities, and backlinks.

Only `memory + latest Stage 3 verdict + new user message` should be used for follow-up prompting.
The export/index layer must never be injected into the live council prompt path.

## Filesystem Contract

The app should run with a mounted storage root such as:

```text
/appdata/llm-council/
  conversations/
    <conversation-id>.json
  exports/
    obsidian/
      conversations/
      highlights/
      themes/
      entities/
      indexes/
```

Configurable environment variables:

- `COUNCIL_DATA_ROOT`
- `COUNCIL_TRANSCRIPTS_DIR`
- `COUNCIL_EXPORTS_DIR`
- `COUNCIL_OBSIDIAN_EXPORTS_DIR`
- `COUNCIL_BUNDLES_PATH`

Defaults still point at the current local `data/` tree so existing behavior is preserved.

## Database Contract

The schema lives in [001_initial_schema.sql](db/postgres/001_initial_schema.sql).

Core tables:

- `conversations`
  Metadata and transcript path.
- `conversation_memory`
  Versioned rolling summaries for prompting.
- `conversation_turn_index`
  Lightweight turn-level highlights and timestamps for browsing.
- `export_jobs`
  Background job queue state.
- `export_artifacts`
  Generated markdown and other output files.
- `semantic_chunks`
  Searchable chunks with optional embeddings.
- `knowledge_entities`
  Canonical entities extracted from conversations.
- `conversation_entity_links`
  Links between conversations and entities.

Raw Stage 1/2/3 payloads are deliberately not normalized into relational tables yet.
They remain in transcript JSON files so the storage model stays simple and resilient.

## Request Path

The synchronous request path should remain:

1. Load current conversation.
2. Build council prompt from:
   rolling memory, latest Stage 3 verdict, new user message.
3. Run Stage 1, Stage 2, Stage 3.
4. Persist transcript JSON to disk.
5. Upsert conversation metadata in Postgres.
6. Enqueue background jobs in `export_jobs`.

## Worker Path

The worker should poll `export_jobs` and process jobs such as:

- `refresh_memory`
- `index_turns`
- `export_markdown`
- `extract_entities`
- `chunk_semantic`

The worker may call a local LLM container for summarization, theme extraction, or chunk labeling.
Failures here should not affect the council response that was already returned to the user.

## Deployment Notes For Unraid

- Mount one persistent volume for transcripts and exports.
- Mount Postgres storage separately according to normal Unraid practice.
- Prefer environment-variable configuration over baking paths into container images.
- Keep the app stateless except for mounted file storage.
- If local inference is added later, isolate it in a separate container so model restarts do not restart the web app.
