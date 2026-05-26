# Unraid Deployment Notes

This repo now ships a single production `Dockerfile` that both `webapp` and `worker` use.

## Container Layout

- `webapp`
  Runs FastAPI and serves the built frontend on port `8002`.
- `worker`
  Runs `python -m backend.worker` against the same mounted transcript/export volume.
- `postgres`
  Stores metadata, rolling memory, jobs, turn indexes, chunks, and entity links.
- `local-llm` optional
  Reserved for a future local summarizer or embedder.

## Persistent Volumes

For Unraid, mount persistent storage so these container paths survive restarts:

- `/var/lib/llm-council/conversations`
- `/var/lib/llm-council/exports`
- `/var/lib/llm-council/model_bundles.json`
- Postgres data at `/var/lib/postgresql/data`

The compose example simplifies this by mounting one `council_data` volume at `/var/lib/llm-council` and one `postgres_data` volume for Postgres.

## Environment

Minimum required variables:

```bash
OPENROUTER_API_KEY=sk-or-v1-...
DATABASE_URL=postgresql://llm_council:llm_council@postgres:5432/llm_council
COUNCIL_DATA_ROOT=/var/lib/llm-council
COUNCIL_TRANSCRIPTS_DIR=/var/lib/llm-council/conversations
COUNCIL_EXPORTS_DIR=/var/lib/llm-council/exports
COUNCIL_OBSIDIAN_EXPORTS_DIR=/var/lib/llm-council/exports/obsidian
COUNCIL_BUNDLES_PATH=/var/lib/llm-council/model_bundles.json
```

`COUNCIL_FRONTEND_DIST_DIR` is already baked into the container as `/app/frontend/dist`, so it usually does not need to be overridden.

If the host already uses port `8002`, override the published port with `COUNCIL_WEBAPP_PORT` when launching the compose stack.

## Startup Behavior

On startup:

1. `webapp` ensures transcript/export storage exists.
2. If Postgres is reachable, schema bootstrap runs automatically.
3. Existing transcript conversations are backfilled into metadata and missing jobs are enqueued.
4. `worker` polls `export_jobs` and processes memory, index, export, chunk, and entity work asynchronously.

## Operational Notes

- The app is served directly from `webapp` on `http://<host>:8002`.
- Health checks should use `GET /api/health`.
- Postgres does not need a published host port for normal operation; keep it internal unless you explicitly need external DB access.
- The mounted transcript/export volume is the source of truth and should be backed up.
