# Unraid Deployment Notes

This repo now ships a single production `Dockerfile` that both `webapp` and `worker` use.

These notes describe the current Docker/compose deployment shape. Publishing through
Unraid Community Apps still needs a public image and CA template XML; the repo does
not yet include those submission artifacts.

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

Minimum required variables for `webapp` and `worker`:

```bash
OPENROUTER_API_KEY=sk-or-v1-...
DATABASE_URL=postgresql://llm_council:llm_council@postgres:5432/llm_council
COUNCIL_DATA_ROOT=/var/lib/llm-council
COUNCIL_TRANSCRIPTS_DIR=/var/lib/llm-council/conversations
COUNCIL_EXPORTS_DIR=/var/lib/llm-council/exports
COUNCIL_OBSIDIAN_EXPORTS_DIR=/var/lib/llm-council/exports/obsidian
COUNCIL_BUNDLES_PATH=/var/lib/llm-council/model_bundles.json
COUNCIL_CSRF_PROTECTION=true
COUNCIL_SECURE_COOKIES=false
```

Sensitive values can also be supplied through mounted files:

```bash
OPENROUTER_API_KEY_FILE=/run/secrets/openrouter_api_key
DATABASE_URL_FILE=/run/secrets/database_url
```

If both the direct variable and the `_FILE` variable are set, the direct variable
wins. This keeps normal Unraid template env vars simple while allowing file-based
secrets for users who prefer bind-mounted secret files.

`COUNCIL_CSRF_PROTECTION` should stay enabled. `COUNCIL_SECURE_COOKIES` should
stay `false` for plain LAN HTTP and should be set to `true` when the app is served
behind HTTPS/TLS.

`COUNCIL_FRONTEND_DIST_DIR` is already baked into the container as `/app/frontend/dist`, so it usually does not need to be overridden.

If the host already uses port `8002`, override the published port with `COUNCIL_WEBAPP_PORT` when launching the compose stack.

Postgres is required for local accounts. If `DATABASE_URL` is missing or unreachable,
the frontend shows a setup error instead of allowing anonymous use.

The Postgres service must use an image with `pgvector`, such as `pgvector/pgvector:pg17`,
because the schema enables the `vector` extension even though embeddings are not
implemented yet.

## Startup Behavior

On startup:

1. `webapp` ensures transcript/export storage exists.
2. If Postgres is reachable, schema bootstrap runs automatically.
3. Existing transcript conversations are backfilled into metadata and missing jobs are enqueued.
4. If no user exists, the frontend prompts for first-admin creation.
5. Existing unowned transcript conversations are assigned to the first admin user.
6. `worker` polls `export_jobs` and processes memory, index, export, chunk, and entity work asynchronously.

Worker jobs are prioritized so rolling memory and turn indexes run ahead of lower
value export/search/entity work. Duplicate active jobs for the same conversation
and job type are coalesced. Transient failures are retried with a bounded delay,
and stale running jobs are returned to the pending queue after their worker lease
expires. Admins can inspect queue health at `GET /api/system/status`.

Search in the current self-hosted release is deterministic lexical retrieval over
transcript-derived chunks. Postgres stores chunks in `semantic_chunks`, and the
schema keeps a nullable pgvector column for future embeddings, but no embedding
provider is required for deployment today.

## User Accounts

- The first browser session creates the first `admin` account.
- Registration is not open after bootstrap.
- Additional users are created by admins from Settings → Users.
- Admins can list users, change roles, and disable or re-enable accounts.
- The app prevents disabling or demoting the last enabled admin account.
- `admin` users can manage model bundles. `member` users can run councils and use
  existing bundles, but cannot create, edit, reorder, or delete bundles.
- Conversations, search results, overviews, entities, and mutation endpoints are
  filtered by conversation owner.

## Exports

- Raw transcripts stay in `/var/lib/llm-council/conversations`.
- Markdown exports are written under `/var/lib/llm-council/exports/obsidian`.
- Conversation and highlight notes are per conversation.
- Conversation index notes are owner-scoped as
  `indexes/conversations-<owner-user-id>.md`, with `indexes/conversations.md`
  reserved for legacy unowned conversations.

## Backup And Restore

Back up these together for a consistent restore:

- `/var/lib/llm-council/conversations`
- `/var/lib/llm-council/exports`
- `/var/lib/llm-council/model_bundles.json`
- Postgres data at `/var/lib/postgresql/data`
- The configured `OPENROUTER_API_KEY` or secret file

Restore by stopping `webapp`, `worker`, and `postgres`, restoring the mounted
paths/Postgres data, then starting Postgres before `webapp` and `worker`.

## Exposure Guidance

The current auth posture is intended for LAN/self-hosted use. Session cookies are
HttpOnly and SameSite=Lax. Authenticated write requests require a CSRF token
header generated from a browser-readable CSRF cookie. Direct public exposure is
still not recommended. For remote access, place the app behind TLS and an
additional reverse proxy/auth layer such as SWAG, Nginx Proxy Manager, Authelia,
or an equivalent setup, and enable `COUNCIL_SECURE_COOKIES=true`.

## Community Apps Status

Before this can be deployed through the Unraid application library, the project
still needs:

- a published image repository, for example GHCR or Docker Hub
- Unraid template XML for the app topology
- a decision on whether Community Apps ships separate templates for `webapp`,
  `worker`, and Postgres, or a single app template plus documented external
  Postgres requirements
- `ca_profile.xml` and required support/project/icon/category metadata

## Operational Notes

- The app is served directly from `webapp` on `http://<host>:8002`.
- Health checks should use `GET /api/health`.
- Postgres does not need a published host port for normal operation; keep it internal unless you explicitly need external DB access.
- The mounted transcript/export volume is the source of truth and should be backed up.
