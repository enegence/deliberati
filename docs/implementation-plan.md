# LLM Council Implementation Plan

This document is the current execution-state checklist for moving the app from the original JSON-only prototype to the Docker/Unraid-ready architecture described in [architecture.md](docs/architecture.md).

Use this as the primary handoff doc for future work. It should answer three questions quickly:

1. What is already real in code?
2. What exists only as schema or deployment scaffolding?
3. What should be built next to stay aligned with the target architecture?

## End State

Target state:

- raw transcripts remain on disk as JSON
- Postgres stores metadata, rolling memory, jobs, and search/index data
- a separate worker performs post-processing asynchronously
- follow-ups use `rolling memory + latest Stage 3 verdict + new user message`
- markdown/export output is written to a mounted share for tools like Obsidian
- the app supports multiple local users with isolated conversations, history, and future search results
- bundle definitions are centrally managed by the instance owner/admin and are read-only for normal users
- the repo is safe for open-source self-hosting with reasonable local-auth defaults, documented secrets handling, and a clear Unraid deployment path

Important current nuance:

- the live prompt path only uses stored rolling memory when Postgres memory already exists
- without Postgres, or before the worker catches up, follow-ups fall back to the latest Stage 3 verdict and then the new user message
- this does not change or downgrade the conversation pane rolling summary behavior
- the overview UI already derives tuned transcript-based fallback memory through `build_memory_record(conversation)` when stored Postgres memory is missing
- that transcript-derived fallback is now also reused on the live prompt path when stored Postgres memory is missing

## Architecture Status

Current state relative to [architecture.md](docs/architecture.md):

- [x] `transcript` exists as the source of truth on disk
- [x] Postgres is integrated for metadata, rolling memory, jobs, and turn index
- [x] `webapp` and `worker` can run as separate processes
- [x] background jobs exist for rolling memory and turn indexing
- [x] compact conversation overview browsing exists
- [x] markdown/export generation exists as a real worker pipeline
- [ ] semantic chunking / embeddings / retrieval are only partially implemented
- [ ] entity/theme extraction is only partially implemented
- [x] first-pass auth, multi-user isolation, and role-aware bundle permissions exist
- [x] worker retry/priority/coalescing behavior is implemented
- [x] secrets ergonomics, auth bootstrap docs, and self-hosting guidance exist in first-pass form
- [ ] open-source release polish and Community Apps packaging are not finalized
- [x] production-ready Dockerfiles / Unraid packaging are finalized
- [x] follow-up prompting always has fresh rolling memory available before the next turn

## Implemented Today

### 1. Storage and Runtime Foundation

- [x] Environment-driven storage contract exists
  - `COUNCIL_DATA_ROOT`
  - `COUNCIL_TRANSCRIPTS_DIR`
  - `COUNCIL_EXPORTS_DIR`
  - `COUNCIL_OBSIDIAN_EXPORTS_DIR`
  - `COUNCIL_BUNDLES_PATH`
  - `DATABASE_URL`
  - `COUNCIL_MEMORY_MAX_TOKENS`

- [x] Transcript JSON remains the source of truth

- [x] Local storage bootstrap creates transcript/export directories and bundle storage

- [x] Initial Postgres schema exists in [001_initial_schema.sql](db/postgres/001_initial_schema.sql)
  - `conversations`
  - `conversation_memory`
  - `conversation_turn_index`
  - `export_jobs`
  - `export_artifacts`
  - `semantic_chunks`
  - `knowledge_entities`
  - `conversation_entity_links`

- [x] Worker scaffold exists as a separate entrypoint
  - `backend.worker`
  - [start.sh](start.sh) launches backend, worker, and frontend together
  - [docker-compose.example.yml](docker-compose.example.yml) models `webapp`, `worker`, `postgres`, and optional `local-llm` services sharing one production image

### 2. Postgres App Integration

- [x] Schema bootstrap is automatic when Postgres is configured and reachable

- [x] Conversation metadata is synced into Postgres when transcripts are saved or backfilled

- [x] Existing conversations can be backfilled into Postgres metadata on startup

- [x] The app still works without Postgres in local development

- [x] Metadata rows track transcript path, bundle id, latest memory version, and latest post-process timestamp

### 3. Background Jobs

- [x] Successful council turns enqueue background jobs
  - `refresh_memory`
  - `index_turns`
  - `export_markdown`
  - `chunk_semantic`
  - `extract_entities`

- [x] The worker claims jobs from `export_jobs` using `FOR UPDATE SKIP LOCKED`

- [x] The worker can complete or fail jobs and persist failure text

- [x] Overview backfill avoids duplicate active jobs when possible

- [x] Worker support is implemented for exactly five job types today
  - `refresh_memory`
  - `index_turns`
  - `export_markdown`
  - `chunk_semantic`
  - `extract_entities`

- [x] Markdown export jobs are implemented
  - deterministic conversation note
  - deterministic highlights note
  - deterministic owner-scoped conversations index note
  - conversation-scoped artifact rows written to `export_artifacts`
  - existing conversations with missing exports are backfilled through the current startup / overview flow
  - archive / restore / rename operations enqueue export refreshes

- [x] Retry, coalescing, and priority behavior are implemented
  - transient failures are retried up to a bounded attempt count with retry delay
  - duplicate pending/running jobs for the same conversation/type are coalesced
  - memory/index/export/search/entity jobs have explicit priority ordering
  - stale running jobs are returned to pending after their worker lease expires

- [x] Search/entity jobs beyond markdown export are implemented in first-pass form
  - `chunk_semantic`
  - `extract_entities`
  - both are queued on successful council turns
  - both can be backfilled for older conversations when data is missing

### 3.5 Markdown Export Pipeline

- [x] `export_markdown` writes deterministic files under `COUNCIL_OBSIDIAN_EXPORTS_DIR`

- [x] First-pass export layout exists
  - `conversations/<conversation-id>.md`
  - `highlights/<conversation-id>.md`
  - owner-scoped `indexes/conversations-<owner-user-id>.md`
  - legacy unowned `indexes/conversations.md`

- [x] Reruns update the same files instead of creating duplicates

- [x] Export notes derive their summary structure from the same tuned rolling-memory builder used by overview fallback

- [ ] No API or UI exists yet for browsing export artifacts directly inside the app

### 3.6 Semantic Search Foundations

- [x] Transcript-derived semantic chunking exists

- [x] Worker support exists for `chunk_semantic`

- [x] Stored chunks can be written into `semantic_chunks` without embeddings

- [x] First-release search direction is explicit
  - transcript JSON is the canonical indexing source
  - retrieval is deterministic lexical search over transcript-derived chunks
  - pgvector stays in the schema as future-ready storage, but embeddings are deferred

- [x] Backend retrieval API exists
  - `GET /api/search?q=...&limit=...`
  - uses stored Postgres chunks when available
  - falls back to transcript-derived search when the chunk index is missing or Postgres is not configured

- [ ] Embeddings are not implemented yet and are not required for the first public self-hosted release

- [x] Basic search UI exists in the frontend
  - sidebar search box
  - date-range filters can constrain results without adding timestamp clutter to result cards
  - archived and active conversations can both be surfaced
  - result cards can open matching conversations
  - result cards can jump to the matched transcript message
  - result card snippets highlight matched query terms
  - matched transcript messages get a temporary in-view cue after jumping

- [x] Search results highlight the matched text inside the full transcript view for user prompts, final responses, and error messages
- [x] Turn timestamps are persisted on transcript messages and shown in transcript/overview browsing surfaces

### 3.7 Entity and Theme Extraction Foundations

- [x] Deterministic entity/theme extraction exists

- [x] Worker support exists for `extract_entities`

- [x] Extracted rows can be written into `knowledge_entities` and `conversation_entity_links`

- [x] Backend read API exists
  - `GET /api/conversations/{conversation_id}/entities`
  - queues extraction if links are missing

- [x] Basic overview UI exists
  - themes and entities section in the conversation overview pane
  - pending / empty / loaded states handled

- [ ] Extraction quality is still heuristic and summary-driven rather than model-driven

### 4. Rolling Memory and Follow-Up Prompting

- [x] Rolling memory is versioned and stored in Postgres

- [x] Rolling memory is bounded by a strict token/character budget

- [x] Deterministic memory builder is substantially improved beyond naive clipping
  - prefers latest concise user ask as `current_goal`
  - prefers concise non-document asks over giant pasted blobs
  - extracts stable constraints from shorter user-authored directive sentences
  - favors recent Stage 3 conclusions as `recent_decisions`
  - detects pasted source material and summarizes it extractively instead of surfacing raw markdown noise
  - stores structured slots in `summary_json` for cleaner display

- [x] Live follow-up prompting uses:
  - latest stored rolling memory when available
  - transcript-derived rolling memory fallback when stored memory is missing
  - latest Stage 3 verdict when available
  - new user message

- [x] Overview API can derive memory directly from transcript when stored Postgres memory is missing

- [x] Live prompt-path fallback derives transcript-based memory when Postgres memory is absent

- [ ] Optional local-LLM summarization path does not exist yet

### 5. Turn Index and Lightweight Browsing

- [x] Turn index rows are generated and stored in Postgres

- [x] Compact overview API exists
  - `GET /api/conversations/{conversation_id}/overview`

- [x] Overview API degrades safely for older conversations
  - transcript-derived memory fallback
  - transcript-derived turn-index fallback
  - backfill jobs queued in the background when needed

- [x] Long conversations default to overview-first loading in the UI

- [x] Overview panel exists in the frontend
  - latest rolling summary
  - turn list
  - jump-to-transcript behavior
  - collapsible layout
  - persistent width controls
  - collapsed numbered turn-chip strip
  - display sanitization for summary rendering
  - hidden visible scrollbars with explicit down-scroll control

- [x] Full transcript is not loaded by default for long conversations

### 6. Bundle Management

- [x] Bundles now have explicit persistent positions

- [x] Bundle ordering is stable in storage and API responses

- [x] Old manually numbered bundle names are normalized

- [x] Bundles can be drag-reordered in the UI

- [x] Bundle dropdown and settings display sorted bundle positions consistently

### 7. Authentication, Multi-User Isolation, and Permissions

Current reality:

- [x] The app now requires local auth when Postgres is configured
- [x] First-admin bootstrap, login, logout, user records, session records, and roles exist
- [x] Legacy unowned conversations are assigned to the first admin user on bootstrap/startup
- [x] Conversations are filtered by authenticated owner in the API/UI
- [x] Search, overview, entities, archive/restore/delete/rename, and message endpoints enforce owner access
- [x] Bundle mutation is admin-only in the API and hidden from non-admin UI
- [x] Markdown conversation exports are per-conversation and owner-scoped indexes avoid cross-user conversation listings

Required end state before deployment:

- [x] Local auth exists with server-side sessions or equivalent durable login state
- [x] Multiple users can sign in and only see their own conversations, search results, memory, and exports
- [x] An `admin` role can manage instance-wide bundles
- [x] A normal `member` role can use configured bundles but cannot create, edit, reorder, or delete them
- [x] API authorization is enforced server-side, not only hidden in the UI

Recommended implementation direction:

- Add a `users` table with at minimum:
  - `id`
  - `username`
  - `password_hash`
  - `role` such as `admin` or `member`
  - `created_at`
  - `disabled_at` optional
- Add session support with:
  - hashed password storage
  - signed cookie sessions for browser use
  - CSRF posture appropriate for cookie auth
  - explicit logout endpoint
- Add ownership columns and filtering:
  - `conversations.owner_user_id`
  - `export_jobs.owner_user_id` optional if useful for auditability
  - any search/entity/export query must filter through conversation ownership
- Keep bundles instance-scoped, not user-scoped, for the first multi-user release
- Disable self-service bundle mutation for non-admin users in both API and UI
- Default user provisioning model for home/Unraid use:
  - registration disabled by default
  - admin creates household users
  - no internet-facing OAuth dependency

### 8. Open-Source, Secrets, and Operational Readiness

Current reality:

- [x] Container packaging works
- [x] Secrets support direct env vars and optional `*_FILE` env variants
- [x] Basic auth bootstrap flow is documented in README
- [x] Unraid-specific auth bootstrap and user-management notes exist
- [x] Backup/restore guidance exists for user accounts plus Postgres plus transcript volume together
- [x] Reverse-proxy / TLS exposure guidance exists

Recommended direction:

- Keep `OPENROUTER_API_KEY` env-var support as the default because that is normal for Unraid templates
- File-based secret support exists for self-hosters:
  - `OPENROUTER_API_KEY_FILE`
  - `DATABASE_URL_FILE`
- Document that on Unraid, secrets are typically handled one of three ways:
  - environment variables in the app template
  - bind-mounted files on the server passed into the container
  - an external reverse proxy / auth stack such as SWAG, Nginx Proxy Manager, or Authelia for internet exposure
- For this repo, local-LAN self-hosting can reasonably use Unraid-managed env vars, but the code should support file-based secrets as a better default for open-source users
- Before public release, document:
  - how to create the first admin user
  - how to rotate the OpenRouter key
  - what paths to back up
  - what is and is not safe to expose publicly

## Present But Not Actually Used Yet

These parts exist in schema or deployment scaffolding, but not as real end-user features yet:

- [ ] Semantic search pipeline is partially complete and currently lexical, not vector-semantic
  - `semantic_chunks` table exists
  - `pgvector` extension is enabled in schema
  - transcript-derived chunking exists
  - backend retrieval API exists
  - sidebar search UI exists
  - embedding column is currently fixed at `VECTOR(1536)`
  - embeddings are still missing
  - transcript-view highlighting exists for matched messages and terms
  - first public release intentionally ships lexical retrieval unless embeddings are implemented later

- [ ] Entities/themes knowledge layer
  - `knowledge_entities` and `conversation_entity_links` tables exist
  - deterministic extraction job exists
  - backend read API exists
  - overview-pane surface exists
  - extraction quality and canonicalization still need refinement

- [ ] Local summarizer / embedder path
  - optional `local-llm` service is modeled in [docker-compose.example.yml](docker-compose.example.yml)
  - no application code currently calls that service

- [x] Docker/Unraid packaging
  - real [Dockerfile](Dockerfile) exists
  - [docker-compose.example.yml](docker-compose.example.yml) now builds a shared `webapp`/`worker` image
  - the built frontend is served by FastAPI inside `webapp`
  - env-driven paths are represented
  - local startup scripts still exist for development
  - Unraid deployment notes live in [docs/unraid-deployment.md](docs/unraid-deployment.md)
  - the published webapp port is configurable through `COUNCIL_WEBAPP_PORT`

## Outstanding Work

This section is the execution queue. A fresh context should work from top to bottom unless the user explicitly reprioritizes.

Current handoff recommendation:

- treat auth, ownership, worker semantics, export isolation, and deployable compose/startup flow as complete enough to build on
- focus new coding work on search quality, entity/theme quality, and final open-source/deployment cleanup
- do not reopen major architecture decisions unless one of the remaining gaps forces it

### 1. Implement Authentication and Multi-User Isolation

Core auth and ownership are implemented. The remaining work in this slice is
hardened browser-security posture.

- [x] Finalize the auth model
  - local username/password auth first
  - cookie-session browser auth first
  - no social login or external IdP for MVP
- [x] Define roles and permissions
  - `admin`: manage users, manage bundles, view system status
  - `member`: run councils, view only own conversations/history/search
- [x] Add database schema for users and sessions
- [x] Attach ownership to conversations and any metadata that must be user-filtered
- [x] Enforce ownership on:
  - list conversations
  - get conversation
  - overview
  - search
  - entities
  - archive / restore / delete / rename
  - send message / stream message
- [x] Lock bundle mutation behind admin-only authorization
- [x] Update frontend for:
  - login screen
  - logout
  - unauthorized states
  - hide bundle-management UI for non-admins
- [x] Decide export isolation model
  - conversation/highlight files are per-conversation with ownership implied by transcript owner
  - generated conversation index files are owner-scoped under `indexes/conversations-<owner-user-id>.md`
  - legacy unowned exports use `indexes/conversations.md`
- [x] Add admin user-management UI
  - admins can create users
  - admins can list users
  - admins can change roles
  - admins can disable/enable users
  - the API prevents disabling or demoting the last enabled admin
- [x] Tighten/document CSRF posture beyond SameSite=Lax session cookies
  - double-submit CSRF cookie/header is enforced for authenticated write requests
  - session cookies are HttpOnly
  - `COUNCIL_SECURE_COOKIES` enables Secure cookies behind HTTPS/TLS

Acceptance criteria:

- a household user can log in and only see their own data
- the admin can create and manage bundles
- a non-admin can choose bundles but cannot mutate them
- no API endpoint leaks other users' conversation metadata or search results

### 2. Finish Semantic Search Quality

- [x] Decide whether transcript chunking remains the canonical source
  - transcript JSON
  - exported markdown is output, not the search source
  - future embedding chunks should still derive from transcripts

- [x] Choose an embedding path
  - embeddings are deferred for the first release
  - likely future options remain:
  - OpenRouter-hosted embeddings
  - local embedding model

- [x] Decide whether embeddings are required before the first public open-source release
  - deterministic lexical search is the first-release behavior
  - embeddings are not required before the first public open-source release

- [ ] Improve the frontend search experience
  - matched substrings now highlight inside the full transcript view
  - decide whether search should live only in the sidebar or also in the main workspace

- [x] Retrieval ranking is better than raw substring matching
  - title matches are weighted more heavily
  - assistant final responses get a small relevance bonus
  - duplicate chunk hits from the same message are deduped
  - result snippets are centered around the first match

- [x] Revisit whether `VECTOR(1536)` should stay fixed before locking in an embedding provider
  - keep the nullable `VECTOR(1536)` column as future-ready schema for now
  - do not rely on it for first-release search behavior

Acceptance criteria:

- search results are consistently relevant on long, messy conversations
- ownership filtering is correct once auth exists
- the indexing approach and embedding decision are explicitly documented

### 3. Finish Entity / Theme Extraction Quality

- [ ] Decide whether this is a separate job or part of export/search indexing
- [x] Extract entities/themes from conversation material in a deterministic first pass
- [x] Populate `knowledge_entities`
- [x] Populate `conversation_entity_links`
- [ ] Improve canonicalization and reduce heuristic noise
- [ ] Decide whether model-assisted extraction is worth adding later
- [ ] Decide whether this layer is needed for user-facing browsing or only for export/search metadata

Specific quality problems to resolve:

- [ ] current theme extraction is summary-keyword-heavy and can produce noisy generic themes
- [ ] canonical entity normalization is not yet strong enough for durable knowledge browsing
- [ ] entity results should be re-evaluated once user isolation exists so cross-user leakage is impossible by design

Acceptance criteria:

- entity/theme output is clearly useful or clearly demoted to metadata-only status
- generic junk terms are substantially reduced
- the plan explicitly states whether this feature is user-facing, export-facing, or both

### 4. Harden Worker Job Semantics

- [x] Add retry behavior for transient worker failures
- [x] Add explicit job coalescing where duplicate jobs are wasteful
- [x] Add priority ordering so `refresh_memory` stays ahead of lower-value indexing/export work when needed
- [x] Decide whether job attempts / last_error / retry_after need first-class schema fields
  - existing `attempts` and `error` fields are used
  - `priority` and `retry_after` are first-class schema fields
- [x] Add observability for stuck or repeatedly failing jobs
  - admin-only `GET /api/system/status` exposes delayed, stale, and recently failed queue state

Acceptance criteria:

- background work is robust enough that a single transient failure does not leave a conversation permanently stale
- job behavior is explicit in code and documented for future maintainers

### 5. Optional Local Summarizer / Embedder Path

- [ ] Decide whether to add actual `local-llm` integration now or defer it explicitly
- [ ] If implementing:
  - choose which jobs may call the local model
  - add env/config surface for base URL and model names
  - define graceful fallback when the local model is unavailable

### 6. Open-Source and Self-Hosting Hardening

- [x] Add secrets ergonomics
  - support `*_FILE` env variants for sensitive values
  - document recommended Unraid usage
- [x] Add admin bootstrap flow
  - first admin creation path
  - behavior when no users exist yet
- [x] Document backup/restore
  - transcripts volume
  - exports volume
  - Postgres data
  - secret material
- [x] Document safe exposure posture
  - LAN-only default
  - reverse proxy / TLS guidance
  - warnings about direct public exposure without additional auth hardening
- [ ] Clean up repo defaults for open source
  - sample env docs
  - example compose env expectations
  - no accidental secret leakage in docs or examples
- [ ] Add release-facing deployment confidence checks
  - smoke-test `./start.sh` from a fresh clone with `.env`
  - smoke-test `docker compose -f docker-compose.example.yml up --build`
  - document any remaining host prerequisites that break the one-script expectation

### 7. Deployment Packaging Follow-Through

Packaging is implemented and verified, but deployment documentation still needs to absorb the auth and open-source work above.

- [x] Replace the example compose setup with a built `webapp`/`worker` topology
- [x] Add real Dockerfiles instead of install-on-startup container commands
- [x] Finalize startup commands for `webapp` and `worker`
- [x] Verify mounted persistent volumes for:
  - transcripts
  - exports
  - Postgres data
- [x] Verify cold-start behavior
  - schema init
  - app startup
  - worker startup
  - old-conversation backfill
- [x] Document the expected Unraid deployment pattern
- [x] Revisit Unraid docs after auth/admin bootstrap exists
- [ ] Create Unraid Community Apps template metadata and decide the final app/worker/Postgres template split

## Recommended Build Order

If work resumes from this document, the recommended sequence is:

1. Finish semantic search quality and lock the sidebar-vs-workspace UX decision.
2. Finish entity/theme quality or explicitly narrow it to metadata-only use.
3. Decide whether local summarizer/embedder integration is in scope for the first public release.
4. Finish open-source/deployment cleanup: repo defaults, smoke tests, published image strategy, and Community Apps metadata.

Reasoning:

- tenant isolation and authorization now exist; the highest remaining product risk is quality/polish, not missing core architecture
- search and entity quality can now be improved against established ownership boundaries
- the repo already has a viable local/dev and compose deployment story, but it still needs final smoke-test confidence and distribution polish
- Unraid/open-source docs should describe the actual auth and secret story, not a temporary one

## Fresh-Context Handoff

If a new context resumes this work, it should do these things first:

1. Read this file completely.
2. Read [docs/architecture.md](docs/architecture.md).
3. Inspect the current implementations in:
   - [backend/main.py](backend/main.py)
   - [backend/storage.py](backend/storage.py)
   - [backend/postgres_store.py](backend/postgres_store.py)
   - [backend/worker.py](backend/worker.py)
   - [backend/semantic_search.py](backend/semantic_search.py)
   - [backend/entity_extraction.py](backend/entity_extraction.py)
   - [frontend/src/App.jsx](frontend/src/App.jsx)
   - [frontend/src/components/Sidebar.jsx](frontend/src/components/Sidebar.jsx)
   - [frontend/src/components/ChatInterface.jsx](frontend/src/components/ChatInterface.jsx)
4. Treat deployment packaging as complete enough for development; remaining deployment work is smoke-test confidence, published-image strategy, and Community Apps metadata.
5. Start with Outstanding Work item 2 unless the user explicitly reprioritizes.

## Acceptance Checklist

Use this as the high-level completion gate:

- [x] Transcript JSON is the source of truth
- [x] Worker exists and processes memory/index jobs
- [x] Overview browsing works for both new and old conversations
- [x] Bundle ordering is stable and user-controlled
- [x] Markdown exports are generated automatically
- [x] Live follow-up prompt path consistently uses rolling memory plus latest verdict
- [x] Multiple users can log in and only access their own conversations/history/search
- [x] Normal users can use admin-provided bundles without mutating them
- [ ] Semantic search works across conversations with production-quality retrieval and UI
- [ ] Entity/theme extraction is implemented with acceptable canonicalization quality if still needed
- [x] Worker retries/coalescing/priority are implemented clearly enough for self-hosted reliability
- [ ] Secrets handling and self-hosting docs are acceptable for open-source release
- [x] Production-ready Docker/Unraid deployment is finalized
