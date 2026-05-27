CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE IF NOT EXISTS users (
    id UUID PRIMARY KEY,
    username TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    role TEXT NOT NULL DEFAULT 'member',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    disabled_at TIMESTAMPTZ,
    CHECK (role IN ('admin', 'member'))
);

CREATE INDEX IF NOT EXISTS users_role_created_idx
    ON users (role, created_at);

CREATE TABLE IF NOT EXISTS user_sessions (
    id UUID PRIMARY KEY,
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    token_hash TEXT NOT NULL UNIQUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    last_seen_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    expires_at TIMESTAMPTZ NOT NULL
);

CREATE INDEX IF NOT EXISTS user_sessions_token_hash_idx
    ON user_sessions (token_hash);

CREATE INDEX IF NOT EXISTS user_sessions_expires_idx
    ON user_sessions (expires_at);

CREATE TABLE IF NOT EXISTS conversations (
    id UUID PRIMARY KEY,
    owner_user_id UUID REFERENCES users(id) ON DELETE SET NULL,
    title TEXT NOT NULL,
    archived BOOLEAN NOT NULL DEFAULT FALSE,
    created_at TIMESTAMPTZ NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL,
    archived_at TIMESTAMPTZ,
    bundle_id TEXT,
    transcript_path TEXT NOT NULL,
    latest_memory_version INTEGER NOT NULL DEFAULT 0,
    latest_exported_at TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS conversations_archived_created_idx
    ON conversations (archived, created_at DESC);

ALTER TABLE conversations
    ADD COLUMN IF NOT EXISTS owner_user_id UUID REFERENCES users(id) ON DELETE SET NULL;

CREATE INDEX IF NOT EXISTS conversations_owner_archived_created_idx
    ON conversations (owner_user_id, archived, created_at DESC);

CREATE TABLE IF NOT EXISTS conversation_memory (
    conversation_id UUID NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
    version INTEGER NOT NULL,
    summary_text TEXT NOT NULL,
    summary_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    token_estimate INTEGER NOT NULL DEFAULT 0,
    source_turn_count INTEGER NOT NULL DEFAULT 0,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (conversation_id, version)
);

CREATE INDEX IF NOT EXISTS conversation_memory_created_idx
    ON conversation_memory (conversation_id, created_at DESC);

CREATE TABLE IF NOT EXISTS conversation_turn_index (
    conversation_id UUID NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
    turn_number INTEGER NOT NULL,
    role TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    short_highlight TEXT NOT NULL,
    stage3_excerpt TEXT,
    transcript_offset JSONB NOT NULL DEFAULT '{}'::jsonb,
    PRIMARY KEY (conversation_id, turn_number)
);

CREATE INDEX IF NOT EXISTS conversation_turn_index_created_idx
    ON conversation_turn_index (conversation_id, created_at DESC);

CREATE TABLE IF NOT EXISTS export_jobs (
    id BIGSERIAL PRIMARY KEY,
    conversation_id UUID NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
    job_type TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',
    attempts INTEGER NOT NULL DEFAULT 0,
    priority INTEGER NOT NULL DEFAULT 0,
    payload JSONB NOT NULL DEFAULT '{}'::jsonb,
    error TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    retry_after TIMESTAMPTZ,
    started_at TIMESTAMPTZ,
    finished_at TIMESTAMPTZ
);

ALTER TABLE export_jobs
    ADD COLUMN IF NOT EXISTS priority INTEGER NOT NULL DEFAULT 0;

ALTER TABLE export_jobs
    ADD COLUMN IF NOT EXISTS retry_after TIMESTAMPTZ;

CREATE INDEX IF NOT EXISTS export_jobs_status_created_idx
    ON export_jobs (status, created_at);

CREATE INDEX IF NOT EXISTS export_jobs_status_retry_priority_idx
    ON export_jobs (status, retry_after, priority DESC, created_at);

CREATE TABLE IF NOT EXISTS export_artifacts (
    id BIGSERIAL PRIMARY KEY,
    conversation_id UUID NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
    artifact_type TEXT NOT NULL,
    file_path TEXT NOT NULL,
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (conversation_id, artifact_type, file_path)
);

CREATE TABLE IF NOT EXISTS semantic_chunks (
    id BIGSERIAL PRIMARY KEY,
    conversation_id UUID NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
    source_type TEXT NOT NULL,
    source_ref TEXT NOT NULL,
    chunk_index INTEGER NOT NULL,
    chunk_text TEXT NOT NULL,
    token_estimate INTEGER NOT NULL DEFAULT 0,
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    embedding VECTOR(1536),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (conversation_id, source_type, source_ref, chunk_index)
);

CREATE INDEX IF NOT EXISTS semantic_chunks_conversation_idx
    ON semantic_chunks (conversation_id, source_type);

CREATE TABLE IF NOT EXISTS knowledge_entities (
    id BIGSERIAL PRIMARY KEY,
    entity_type TEXT NOT NULL,
    canonical_name TEXT NOT NULL,
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (entity_type, canonical_name)
);

CREATE TABLE IF NOT EXISTS conversation_entity_links (
    conversation_id UUID NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
    entity_id BIGINT NOT NULL REFERENCES knowledge_entities(id) ON DELETE CASCADE,
    link_type TEXT NOT NULL DEFAULT 'mentioned',
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (conversation_id, entity_id, link_type)
);
