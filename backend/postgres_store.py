"""Postgres-backed metadata storage for conversations."""

from __future__ import annotations

import json
import logging
import threading
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

from .config import DATABASE_URL
from .search_utils import normalize_query, rank_and_dedupe_results, significant_query_terms

logger = logging.getLogger("llm_council.postgres")

_SCHEMA_STATE_LOCK = threading.Lock()
_SCHEMA_INITIALIZED = False
_LAST_INIT_ATTEMPT = 0.0
_INIT_RETRY_INTERVAL_SECONDS = 30.0
MAX_JOB_ATTEMPTS = 3
STALE_RUNNING_JOB_MINUTES = 30
JOB_PRIORITIES = {
    "refresh_memory": 100,
    "index_turns": 80,
    "export_markdown": 60,
    "chunk_semantic": 40,
    "extract_entities": 30,
}


def _job_priority(job_type: str) -> int:
    """Return scheduling priority for a background job type."""
    return JOB_PRIORITIES.get(job_type, 0)


def _retry_delay_seconds(attempts: int) -> int:
    """Return bounded exponential retry delay for a failed job attempt."""
    return min(300, 5 * (2 ** max(0, attempts - 1)))


def is_configured() -> bool:
    """Return True when a database URL is configured."""
    return bool(DATABASE_URL)


def _parse_timestamp(value: Optional[str]) -> Optional[datetime]:
    """Parse an ISO timestamp and normalize it to UTC."""
    if not value:
        return None

    timestamp = datetime.fromisoformat(value)
    if timestamp.tzinfo is None:
        return timestamp.replace(tzinfo=timezone.utc)
    return timestamp.astimezone(timezone.utc)


def _normalize_user_row(row: Dict[str, Any]) -> Dict[str, Any]:
    """Serialize a user row for API and auth use."""
    normalized = dict(row)
    normalized["id"] = str(normalized["id"])
    for timestamp_key in ("created_at", "disabled_at"):
        timestamp = normalized.get(timestamp_key)
        if timestamp is not None:
            normalized[timestamp_key] = timestamp.isoformat()
    return normalized


def _get_schema_path() -> Path:
    """Return the path to the initial Postgres schema."""
    return Path(__file__).resolve().parent.parent / "db" / "postgres" / "001_initial_schema.sql"


def _connect():
    """Create a Postgres connection."""
    import psycopg

    return psycopg.connect(DATABASE_URL, autocommit=True)


def _connect_transactional():
    """Create a transactional Postgres connection."""
    import psycopg

    return psycopg.connect(DATABASE_URL, autocommit=False)


def ensure_database() -> bool:
    """Initialize the schema if Postgres is configured and reachable."""
    global _SCHEMA_INITIALIZED, _LAST_INIT_ATTEMPT

    if not is_configured():
        return False

    now = time.monotonic()

    with _SCHEMA_STATE_LOCK:
        if _SCHEMA_INITIALIZED:
            return True
        if now - _LAST_INIT_ATTEMPT < _INIT_RETRY_INTERVAL_SECONDS:
            return False
        _LAST_INIT_ATTEMPT = now

    try:
        schema_sql = _get_schema_path().read_text()
        with _connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute(schema_sql)
    except Exception:
        logger.exception("Failed to initialize Postgres schema")
        return False

    with _SCHEMA_STATE_LOCK:
        _SCHEMA_INITIALIZED = True

    logger.info("Postgres schema initialized")
    return True


def count_users() -> int:
    """Return the number of configured local users."""
    if not ensure_database():
        return 0

    try:
        with _connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute("SELECT COUNT(*) FROM users")
                row = cursor.fetchone()
    except Exception:
        logger.exception("Failed to count users")
        return 0

    return int(row[0]) if row else 0


def create_user(username: str, password_hash: str, role: str = "member") -> Optional[Dict[str, Any]]:
    """Create a local user."""
    if not ensure_database():
        return None

    try:
        import psycopg.rows

        with _connect() as connection:
            with connection.cursor(row_factory=psycopg.rows.dict_row) as cursor:
                cursor.execute(
                    """
                    INSERT INTO users (id, username, password_hash, role)
                    VALUES (%s, %s, %s, %s)
                    RETURNING id, username, password_hash, role, created_at, disabled_at
                    """,
                    (uuid.uuid4(), username, password_hash, role),
                )
                row = cursor.fetchone()
    except Exception:
        logger.exception("Failed to create user %s", username)
        return None

    return _normalize_user_row(row) if row else None


def list_users() -> list[Dict[str, Any]]:
    """Return local users ordered for admin management."""
    if not ensure_database():
        return []

    try:
        import psycopg.rows

        with _connect() as connection:
            with connection.cursor(row_factory=psycopg.rows.dict_row) as cursor:
                cursor.execute(
                    """
                    SELECT id, username, password_hash, role, created_at, disabled_at
                    FROM users
                    ORDER BY created_at ASC
                    """
                )
                rows = cursor.fetchall()
    except Exception:
        logger.exception("Failed to list users")
        return []

    return [_normalize_user_row(row) for row in rows]


def get_user_by_username(username: str) -> Optional[Dict[str, Any]]:
    """Return a user by username."""
    if not ensure_database():
        return None

    try:
        import psycopg.rows

        with _connect() as connection:
            with connection.cursor(row_factory=psycopg.rows.dict_row) as cursor:
                cursor.execute(
                    """
                    SELECT id, username, password_hash, role, created_at, disabled_at
                    FROM users
                    WHERE lower(username) = lower(%s)
                    LIMIT 1
                    """,
                    (username,),
                )
                row = cursor.fetchone()
    except Exception:
        logger.exception("Failed to load user %s", username)
        return None

    return _normalize_user_row(row) if row else None


def get_user_by_id(user_id: str) -> Optional[Dict[str, Any]]:
    """Return a user by id."""
    if not ensure_database():
        return None

    try:
        import psycopg.rows

        with _connect() as connection:
            with connection.cursor(row_factory=psycopg.rows.dict_row) as cursor:
                cursor.execute(
                    """
                    SELECT id, username, password_hash, role, created_at, disabled_at
                    FROM users
                    WHERE id = %s
                    LIMIT 1
                    """,
                    (uuid.UUID(user_id),),
                )
                row = cursor.fetchone()
    except Exception:
        logger.exception("Failed to load user by id %s", user_id)
        return None

    return _normalize_user_row(row) if row else None


def get_first_admin_user() -> Optional[Dict[str, Any]]:
    """Return the oldest enabled admin user."""
    if not ensure_database():
        return None

    try:
        import psycopg.rows

        with _connect() as connection:
            with connection.cursor(row_factory=psycopg.rows.dict_row) as cursor:
                cursor.execute(
                    """
                    SELECT id, username, password_hash, role, created_at, disabled_at
                    FROM users
                    WHERE role = 'admin' AND disabled_at IS NULL
                    ORDER BY created_at ASC
                    LIMIT 1
                    """
                )
                row = cursor.fetchone()
    except Exception:
        logger.exception("Failed to load first admin user")
        return None

    return _normalize_user_row(row) if row else None


def count_enabled_admins() -> int:
    """Return the number of enabled admin users."""
    if not ensure_database():
        return 0

    try:
        with _connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT COUNT(*)
                    FROM users
                    WHERE role = 'admin' AND disabled_at IS NULL
                    """
                )
                row = cursor.fetchone()
    except Exception:
        logger.exception("Failed to count enabled admins")
        return 0

    return int(row[0]) if row else 0


def update_user(
    user_id: str,
    *,
    role: Optional[str] = None,
    disabled: Optional[bool] = None,
) -> Optional[Dict[str, Any]]:
    """Update local user role and enabled/disabled state."""
    if not ensure_database():
        return None

    assignments = []
    params: list[Any] = []
    if role is not None:
        assignments.append("role = %s")
        params.append(role)
    if disabled is not None:
        if disabled:
            assignments.append("disabled_at = COALESCE(disabled_at, NOW())")
        else:
            assignments.append("disabled_at = NULL")

    if not assignments:
        return get_user_by_id(user_id)

    params.append(uuid.UUID(user_id))

    try:
        import psycopg.rows

        with _connect() as connection:
            with connection.cursor(row_factory=psycopg.rows.dict_row) as cursor:
                cursor.execute(
                    f"""
                    UPDATE users
                    SET {", ".join(assignments)}
                    WHERE id = %s
                    RETURNING id, username, password_hash, role, created_at, disabled_at
                    """,
                    params,
                )
                row = cursor.fetchone()
    except Exception:
        logger.exception("Failed to update user %s", user_id)
        return None

    return _normalize_user_row(row) if row else None


def create_user_session(
    user_id: str,
    token_hash: str,
    expires_at: datetime,
) -> bool:
    """Persist a browser session for a local user."""
    if not ensure_database():
        return False

    try:
        with _connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO user_sessions (id, user_id, token_hash, expires_at)
                    VALUES (%s, %s, %s, %s)
                    """,
                    (uuid.uuid4(), uuid.UUID(user_id), token_hash, expires_at),
                )
    except Exception:
        logger.exception("Failed to create session for user %s", user_id)
        return False

    return True


def get_user_for_session(token_hash: str) -> Optional[Dict[str, Any]]:
    """Return the enabled user for an unexpired session token hash."""
    if not ensure_database():
        return None

    try:
        import psycopg.rows

        with _connect() as connection:
            with connection.cursor(row_factory=psycopg.rows.dict_row) as cursor:
                cursor.execute(
                    """
                    SELECT users.id, users.username, users.password_hash, users.role,
                           users.created_at, users.disabled_at
                    FROM user_sessions
                    JOIN users ON users.id = user_sessions.user_id
                    WHERE user_sessions.token_hash = %s
                      AND user_sessions.expires_at > NOW()
                      AND users.disabled_at IS NULL
                    LIMIT 1
                    """,
                    (token_hash,),
                )
                row = cursor.fetchone()
                if row:
                    cursor.execute(
                        """
                        UPDATE user_sessions
                        SET last_seen_at = NOW()
                        WHERE token_hash = %s
                        """,
                        (token_hash,),
                    )
    except Exception:
        logger.exception("Failed to load user for session")
        return None

    return _normalize_user_row(row) if row else None


def delete_user_session(token_hash: str) -> bool:
    """Delete a browser session by token hash."""
    if not ensure_database():
        return False

    try:
        with _connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    "DELETE FROM user_sessions WHERE token_hash = %s",
                    (token_hash,),
                )
    except Exception:
        logger.exception("Failed to delete user session")
        return False

    return True


def delete_user_sessions(user_id: str) -> bool:
    """Delete all browser sessions for a local user."""
    if not ensure_database():
        return False

    try:
        with _connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    "DELETE FROM user_sessions WHERE user_id = %s",
                    (uuid.UUID(user_id),),
                )
    except Exception:
        logger.exception("Failed to delete sessions for user %s", user_id)
        return False

    return True


def assign_unowned_conversations(owner_user_id: str) -> bool:
    """Assign legacy metadata rows that do not yet have an owner."""
    if not ensure_database():
        return False

    try:
        with _connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    UPDATE conversations
                    SET owner_user_id = %s
                    WHERE owner_user_id IS NULL
                    """,
                    (uuid.UUID(owner_user_id),),
                )
    except Exception:
        logger.exception("Failed to assign unowned conversations")
        return False

    return True


def _extract_bundle_id(conversation: Dict[str, Any]) -> Optional[str]:
    """Extract the most recent bundle id used in the conversation."""
    for message in reversed(conversation.get("messages", [])):
        bundle_id = message.get("bundle", {}).get("id")
        if bundle_id:
            return bundle_id
    return None


def sync_conversation_metadata(conversation: Dict[str, Any], transcript_path: str) -> bool:
    """Upsert lightweight conversation metadata into Postgres."""
    if not ensure_database():
        return False

    try:
        with _connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO conversations (
                        id,
                        owner_user_id,
                        title,
                        archived,
                        created_at,
                        updated_at,
                        archived_at,
                        bundle_id,
                        transcript_path
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (id) DO UPDATE
                    SET
                        owner_user_id = COALESCE(EXCLUDED.owner_user_id, conversations.owner_user_id),
                        title = EXCLUDED.title,
                        archived = EXCLUDED.archived,
                        updated_at = EXCLUDED.updated_at,
                        archived_at = EXCLUDED.archived_at,
                        bundle_id = EXCLUDED.bundle_id,
                        transcript_path = EXCLUDED.transcript_path
                    """,
                    (
                        uuid.UUID(conversation["id"]),
                        uuid.UUID(conversation["owner_user_id"]) if conversation.get("owner_user_id") else None,
                        conversation.get("title", "New Conversation"),
                        bool(conversation.get("archived", False)),
                        _parse_timestamp(conversation["created_at"]),
                        datetime.now(timezone.utc),
                        _parse_timestamp(conversation.get("archived_at")),
                        _extract_bundle_id(conversation),
                        transcript_path,
                    ),
                )
    except Exception:
        logger.exception("Failed to sync conversation metadata for %s", conversation.get("id"))
        return False

    return True


def delete_conversation_metadata(conversation_id: str) -> bool:
    """Delete conversation metadata from Postgres."""
    if not ensure_database():
        return False

    try:
        with _connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    "DELETE FROM conversations WHERE id = %s",
                    (uuid.UUID(conversation_id),),
                )
    except Exception:
        logger.exception("Failed to delete conversation metadata for %s", conversation_id)
        return False

    return True


def enqueue_export_job(
    conversation_id: str,
    job_type: str,
    payload: Optional[Dict[str, Any]] = None,
) -> bool:
    """Insert or coalesce a background export/index job in Postgres."""
    if not ensure_database():
        return False

    priority = _job_priority(job_type)

    try:
        with _connect_transactional() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT id
                    FROM export_jobs
                    WHERE conversation_id = %s
                      AND job_type = %s
                      AND status IN ('pending', 'running')
                    ORDER BY priority DESC, created_at ASC
                    FOR UPDATE
                    LIMIT 1
                    """,
                    (uuid.UUID(conversation_id), job_type),
                )
                existing = cursor.fetchone()
                if existing:
                    cursor.execute(
                        """
                        UPDATE export_jobs
                        SET
                            payload = %s::jsonb,
                            priority = GREATEST(priority, %s),
                            retry_after = CASE
                                WHEN status = 'pending' THEN NULL
                                ELSE retry_after
                            END,
                            error = NULL
                        WHERE id = %s
                        """,
                        (json.dumps(payload or {}), priority, existing[0]),
                    )
                else:
                    cursor.execute(
                        """
                        INSERT INTO export_jobs (
                            conversation_id,
                            job_type,
                            priority,
                            payload
                        ) VALUES (%s, %s, %s, %s::jsonb)
                        """,
                        (
                            uuid.UUID(conversation_id),
                            job_type,
                            priority,
                            json.dumps(payload or {}),
                        ),
                    )
            connection.commit()
    except Exception:
        logger.exception(
            "Failed to enqueue export job %s for %s",
            job_type,
            conversation_id,
        )
        return False

    return True


def get_pending_job_counts() -> Dict[str, int]:
    """Return runnable and delayed pending job counts grouped by job type."""
    if not ensure_database():
        return {}

    try:
        with _connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT job_type, COUNT(*)
                    FROM export_jobs
                    WHERE status = 'pending'
                      AND (retry_after IS NULL OR retry_after <= NOW())
                    GROUP BY job_type
                    ORDER BY job_type
                    """
                )
                rows = cursor.fetchall()
    except Exception:
        logger.exception("Failed to read pending export job counts")
        return {}

    return {job_type: count for job_type, count in rows}


def get_export_job_status_summary() -> Dict[str, Any]:
    """Return a compact status summary for worker observability."""
    if not ensure_database():
        return {}

    try:
        import psycopg.rows

        with _connect() as connection:
            with connection.cursor(row_factory=psycopg.rows.dict_row) as cursor:
                cursor.execute(
                    """
                    SELECT status, job_type, COUNT(*) AS count
                    FROM export_jobs
                    GROUP BY status, job_type
                    ORDER BY status, job_type
                    """
                )
                by_status = [dict(row) for row in cursor.fetchall()]

                cursor.execute(
                    """
                    SELECT COUNT(*) AS count
                    FROM export_jobs
                    WHERE status = 'pending'
                      AND retry_after > NOW()
                    """
                )
                delayed_pending = int(cursor.fetchone()["count"])

                cursor.execute(
                    """
                    SELECT COUNT(*) AS count
                    FROM export_jobs
                    WHERE status = 'running'
                      AND started_at < NOW() - (%s * INTERVAL '1 minute')
                    """,
                    (STALE_RUNNING_JOB_MINUTES,),
                )
                stale_running = int(cursor.fetchone()["count"])

                cursor.execute(
                    """
                    SELECT id, conversation_id::text AS conversation_id, job_type,
                           attempts, error, finished_at
                    FROM export_jobs
                    WHERE status = 'failed'
                    ORDER BY finished_at DESC NULLS LAST, id DESC
                    LIMIT 10
                    """
                )
                recent_failures = [dict(row) for row in cursor.fetchall()]
    except Exception:
        logger.exception("Failed to read export job status summary")
        return {}

    for failure in recent_failures:
        if failure.get("finished_at") is not None:
            failure["finished_at"] = failure["finished_at"].isoformat()

    return {
        "by_status": by_status,
        "delayed_pending": delayed_pending,
        "stale_running": stale_running,
        "max_attempts": MAX_JOB_ATTEMPTS,
        "stale_running_minutes": STALE_RUNNING_JOB_MINUTES,
        "recent_failures": recent_failures,
    }


def has_active_export_job(conversation_id: str, job_type: str) -> bool:
    """Return True when a conversation already has a pending/running job of this type."""
    if not ensure_database():
        return False

    try:
        with _connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT 1
                    FROM export_jobs
                    WHERE conversation_id = %s
                      AND job_type = %s
                      AND status IN ('pending', 'running')
                    LIMIT 1
                    """,
                    (uuid.UUID(conversation_id), job_type),
                )
                row = cursor.fetchone()
    except Exception:
        logger.exception(
            "Failed to check active export job %s for %s",
            job_type,
            conversation_id,
        )
        return False

    return row is not None


def get_latest_conversation_memory(conversation_id: str) -> Optional[Dict[str, Any]]:
    """Return the latest rolling memory record for a conversation."""
    if not ensure_database():
        return None

    try:
        import psycopg.rows

        with _connect() as connection:
            with connection.cursor(row_factory=psycopg.rows.dict_row) as cursor:
                cursor.execute(
                    """
                    SELECT
                        version,
                        summary_text,
                        summary_json,
                        token_estimate,
                        source_turn_count,
                        created_at
                    FROM conversation_memory
                    WHERE conversation_id = %s
                    ORDER BY version DESC
                    LIMIT 1
                    """,
                    (uuid.UUID(conversation_id),),
                )
                row = cursor.fetchone()
    except Exception:
        logger.exception("Failed to load latest rolling memory for %s", conversation_id)
        return None

    return dict(row) if row else None


def get_conversation_turn_index(conversation_id: str) -> list[Dict[str, Any]]:
    """Return compact turn index rows for a conversation."""
    if not ensure_database():
        return []

    try:
        import psycopg.rows

        with _connect() as connection:
            with connection.cursor(row_factory=psycopg.rows.dict_row) as cursor:
                cursor.execute(
                    """
                    SELECT
                        turn_number,
                        role,
                        created_at,
                        short_highlight,
                        stage3_excerpt,
                        transcript_offset
                    FROM conversation_turn_index
                    WHERE conversation_id = %s
                    ORDER BY turn_number ASC
                    """,
                    (uuid.UUID(conversation_id),),
                )
                rows = cursor.fetchall()
    except Exception:
        logger.exception("Failed to load turn index for %s", conversation_id)
        return []

    return [dict(row) for row in rows]


def has_conversation_turn_index(conversation_id: str) -> bool:
    """Return True when at least one indexed turn row exists for a conversation."""
    if not ensure_database():
        return False

    try:
        with _connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT 1
                    FROM conversation_turn_index
                    WHERE conversation_id = %s
                    LIMIT 1
                    """,
                    (uuid.UUID(conversation_id),),
                )
                row = cursor.fetchone()
    except Exception:
        logger.exception("Failed to check turn index presence for %s", conversation_id)
        return False

    return row is not None


def claim_next_export_job() -> Optional[Dict[str, Any]]:
    """Claim the next pending export job for worker processing."""
    if not ensure_database():
        return None

    try:
        import psycopg.rows

        with _connect_transactional() as connection:
            with connection.cursor(row_factory=psycopg.rows.dict_row) as cursor:
                cursor.execute(
                    """
                    UPDATE export_jobs
                    SET
                        status = 'pending',
                        retry_after = NOW(),
                        error = COALESCE(error, 'Worker lease expired'),
                        started_at = NULL
                    WHERE status = 'running'
                      AND started_at < NOW() - (%s * INTERVAL '1 minute')
                    """,
                    (STALE_RUNNING_JOB_MINUTES,),
                )
                cursor.execute(
                    """
                    WITH next_job AS (
                        SELECT id
                        FROM export_jobs
                        WHERE status = 'pending'
                          AND (retry_after IS NULL OR retry_after <= NOW())
                        ORDER BY priority DESC, created_at ASC
                        FOR UPDATE SKIP LOCKED
                        LIMIT 1
                    )
                    UPDATE export_jobs AS jobs
                    SET
                        status = 'running',
                        attempts = jobs.attempts + 1,
                        started_at = NOW(),
                        retry_after = NULL,
                        error = NULL
                    FROM next_job
                    WHERE jobs.id = next_job.id
                    RETURNING
                        jobs.id,
                        jobs.conversation_id::text AS conversation_id,
                        jobs.job_type,
                        jobs.payload,
                        jobs.attempts,
                        jobs.priority
                    """
                )
                job = cursor.fetchone()
            connection.commit()
    except Exception:
        logger.exception("Failed to claim next export job")
        return None

    return dict(job) if job else None


def complete_export_job(job_id: int) -> bool:
    """Mark an export job as completed."""
    if not ensure_database():
        return False

    try:
        with _connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    UPDATE export_jobs
                    SET
                        status = 'completed',
                        finished_at = NOW(),
                        retry_after = NULL,
                        error = NULL
                    WHERE id = %s
                    """,
                    (job_id,),
                )
    except Exception:
        logger.exception("Failed to complete export job %s", job_id)
        return False

    return True


def fail_export_job(job_id: int, error: str) -> bool:
    """Retry a failed job attempt or mark it permanently failed."""
    if not ensure_database():
        return False

    try:
        with _connect_transactional() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT attempts
                    FROM export_jobs
                    WHERE id = %s
                    FOR UPDATE
                    """,
                    (job_id,),
                )
                row = cursor.fetchone()
                if row is None:
                    connection.rollback()
                    return False

                attempts = int(row[0])
                if attempts < MAX_JOB_ATTEMPTS:
                    retry_delay = _retry_delay_seconds(attempts)
                    cursor.execute(
                        """
                        UPDATE export_jobs
                        SET
                            status = 'pending',
                            retry_after = NOW() + (%s * INTERVAL '1 second'),
                            started_at = NULL,
                            finished_at = NULL,
                            error = %s
                        WHERE id = %s
                        """,
                        (retry_delay, error[:2000], job_id),
                    )
                else:
                    cursor.execute(
                        """
                        UPDATE export_jobs
                        SET
                            status = 'failed',
                            finished_at = NOW(),
                            retry_after = NULL,
                            error = %s
                        WHERE id = %s
                        """,
                        (error[:2000], job_id),
                    )
            connection.commit()
    except Exception:
        logger.exception("Failed to fail export job %s", job_id)
        return False

    return True


def store_conversation_memory(
    conversation_id: str,
    summary_text: str,
    summary_json: Dict[str, Any],
    token_estimate: int,
    source_turn_count: int,
) -> Optional[int]:
    """Persist a new version of rolling memory for a conversation."""
    if not ensure_database():
        return None

    try:
        with _connect_transactional() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT latest_memory_version
                    FROM conversations
                    WHERE id = %s
                    FOR UPDATE
                    """,
                    (uuid.UUID(conversation_id),),
                )
                row = cursor.fetchone()
                if row is None:
                    connection.rollback()
                    logger.warning(
                        "Cannot store memory for conversation %s because metadata row is missing",
                        conversation_id,
                    )
                    return None

                current_version = row[0]
                next_version = current_version + 1

                cursor.execute(
                    """
                    INSERT INTO conversation_memory (
                        conversation_id,
                        version,
                        summary_text,
                        summary_json,
                        token_estimate,
                        source_turn_count
                    ) VALUES (%s, %s, %s, %s::jsonb, %s, %s)
                    """,
                    (
                        uuid.UUID(conversation_id),
                        next_version,
                        summary_text,
                        json.dumps(summary_json),
                        token_estimate,
                        source_turn_count,
                    ),
                )

                cursor.execute(
                    """
                    UPDATE conversations
                    SET latest_memory_version = %s, latest_exported_at = NOW()
                    WHERE id = %s
                    """,
                    (next_version, uuid.UUID(conversation_id)),
                )
            connection.commit()
    except Exception:
        logger.exception("Failed to store rolling memory for %s", conversation_id)
        return None

    return next_version


def replace_turn_index(conversation_id: str, entries: list[Dict[str, Any]]) -> bool:
    """Replace turn index rows for a conversation."""
    if not ensure_database():
        return False

    try:
        with _connect_transactional() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    "DELETE FROM conversation_turn_index WHERE conversation_id = %s",
                    (uuid.UUID(conversation_id),),
                )

                for entry in entries:
                    cursor.execute(
                        """
                        INSERT INTO conversation_turn_index (
                            conversation_id,
                            turn_number,
                            role,
                            created_at,
                            short_highlight,
                            stage3_excerpt,
                            transcript_offset
                        ) VALUES (%s, %s, %s, %s, %s, %s, %s::jsonb)
                        """,
                        (
                            uuid.UUID(conversation_id),
                            entry["turn_number"],
                            entry["role"],
                            _parse_timestamp(entry.get("created_at")) or datetime.now(timezone.utc),
                            entry["short_highlight"],
                            entry.get("stage3_excerpt"),
                            json.dumps(entry.get("transcript_offset", {})),
                        ),
                    )

                cursor.execute(
                    """
                    UPDATE conversations
                    SET latest_exported_at = NOW()
                    WHERE id = %s
                    """,
                    (uuid.UUID(conversation_id),),
                )
            connection.commit()
    except Exception:
        logger.exception("Failed to replace turn index for %s", conversation_id)
        return False

    return True


def store_export_artifacts(conversation_id: str, artifacts: list[Dict[str, Any]]) -> bool:
    """Upsert export artifact rows for a conversation and related shared notes."""
    if not ensure_database():
        return False

    if not artifacts:
        return True

    try:
        with _connect_transactional() as connection:
            with connection.cursor() as cursor:
                for artifact in artifacts:
                    artifact_type = artifact["artifact_type"]
                    file_path = artifact["file_path"]
                    metadata = json.dumps(artifact.get("metadata") or {})

                    if artifact.get("shared") or artifact.get("global"):
                        cursor.execute(
                            """
                            DELETE FROM export_artifacts
                            WHERE artifact_type = %s
                              AND file_path = %s
                            """,
                            (artifact_type, file_path),
                        )

                    cursor.execute(
                        """
                        INSERT INTO export_artifacts (
                            conversation_id,
                            artifact_type,
                            file_path,
                            metadata
                        ) VALUES (%s, %s, %s, %s::jsonb)
                        ON CONFLICT (conversation_id, artifact_type, file_path) DO UPDATE
                        SET metadata = EXCLUDED.metadata, updated_at = NOW()
                        """,
                        (
                            uuid.UUID(conversation_id),
                            artifact_type,
                            file_path,
                            metadata,
                        ),
                    )

                cursor.execute(
                    """
                    UPDATE conversations
                    SET latest_exported_at = NOW()
                    WHERE id = %s
                    """,
                    (uuid.UUID(conversation_id),),
                )
            connection.commit()
    except Exception:
        logger.exception("Failed to store export artifacts for %s", conversation_id)
        return False

    return True


def has_semantic_chunks(conversation_id: str) -> bool:
    """Return True when at least one semantic chunk row exists for a conversation."""
    if not ensure_database():
        return False

    try:
        with _connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT 1
                    FROM semantic_chunks
                    WHERE conversation_id = %s
                    LIMIT 1
                    """,
                    (uuid.UUID(conversation_id),),
                )
                row = cursor.fetchone()
    except Exception:
        logger.exception("Failed to check semantic chunks for %s", conversation_id)
        return False

    return row is not None


def replace_semantic_chunks(conversation_id: str, chunks: list[Dict[str, Any]]) -> bool:
    """Replace semantic chunk rows for a conversation."""
    if not ensure_database():
        return False

    try:
        with _connect_transactional() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    "DELETE FROM semantic_chunks WHERE conversation_id = %s",
                    (uuid.UUID(conversation_id),),
                )

                for chunk in chunks:
                    cursor.execute(
                        """
                        INSERT INTO semantic_chunks (
                            conversation_id,
                            source_type,
                            source_ref,
                            chunk_index,
                            chunk_text,
                            token_estimate,
                            metadata,
                            embedding
                        ) VALUES (%s, %s, %s, %s, %s, %s, %s::jsonb, %s)
                        """,
                        (
                            uuid.UUID(conversation_id),
                            chunk["source_type"],
                            chunk["source_ref"],
                            chunk["chunk_index"],
                            chunk["chunk_text"],
                            chunk["token_estimate"],
                            json.dumps(chunk.get("metadata") or {}),
                            None,
                        ),
                    )

                cursor.execute(
                    """
                    UPDATE conversations
                    SET latest_exported_at = NOW()
                    WHERE id = %s
                    """,
                    (uuid.UUID(conversation_id),),
                )
            connection.commit()
    except Exception:
        logger.exception("Failed to replace semantic chunks for %s", conversation_id)
        return False

    return True


def search_semantic_chunks(
    query: str,
    limit: int = 20,
    owner_user_id: Optional[str] = None,
) -> list[Dict[str, Any]]:
    """Search transcript-derived chunks stored in Postgres."""
    if not ensure_database():
        return []

    normalized_query = normalize_query(query)
    if not normalized_query:
        return []

    wildcard = f"%{normalized_query}%"
    term_wildcards = [f"%{term}%" for term in significant_query_terms(normalized_query)]

    try:
        import psycopg.rows

        with _connect() as connection:
            with connection.cursor(row_factory=psycopg.rows.dict_row) as cursor:
                owner_filter = ""
                term_clauses = []
                params: list[Any] = [wildcard, wildcard, wildcard, wildcard]
                for term_wildcard in term_wildcards:
                    term_clauses.append("(conversations.title ILIKE %s OR chunks.chunk_text ILIKE %s)")
                    params.extend([term_wildcard, term_wildcard])

                term_where = ""
                if term_clauses:
                    term_where = " OR " + " OR ".join(term_clauses)

                if owner_user_id:
                    owner_filter = "AND conversations.owner_user_id = %s"
                    params.append(uuid.UUID(owner_user_id))
                params.append(max(limit * 20, 100))

                cursor.execute(
                    f"""
                    SELECT
                        chunks.conversation_id::text AS conversation_id,
                        conversations.title,
                        conversations.archived,
                        chunks.source_type,
                        chunks.source_ref,
                        chunks.chunk_index,
                        chunks.chunk_text,
                        chunks.metadata,
                        CASE
                            WHEN conversations.title ILIKE %s THEN 3
                            WHEN chunks.chunk_text ILIKE %s THEN 2
                            ELSE 1
                        END AS score
                    FROM semantic_chunks AS chunks
                    JOIN conversations
                      ON conversations.id = chunks.conversation_id
                    WHERE (
                        conversations.title ILIKE %s
                        OR chunks.chunk_text ILIKE %s
                        {term_where}
                    )
                       {owner_filter}
                    ORDER BY
                        conversations.updated_at DESC,
                        chunks.chunk_index ASC
                    LIMIT %s
                    """,
                    params,
                )
                rows = cursor.fetchall()
    except Exception:
        logger.exception("Failed to search semantic chunks")
        return []

    return rank_and_dedupe_results([dict(row) for row in rows], normalized_query, limit)


def has_conversation_entity_links(conversation_id: str) -> bool:
    """Return True when at least one entity link exists for a conversation."""
    if not ensure_database():
        return False

    try:
        with _connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT 1
                    FROM conversation_entity_links
                    WHERE conversation_id = %s
                    LIMIT 1
                    """,
                    (uuid.UUID(conversation_id),),
                )
                row = cursor.fetchone()
    except Exception:
        logger.exception("Failed to check entity links for %s", conversation_id)
        return False

    return row is not None


def replace_conversation_entities(conversation_id: str, entities: list[Dict[str, Any]]) -> bool:
    """Replace entity links for a conversation, upserting canonical entities."""
    if not ensure_database():
        return False

    try:
        with _connect_transactional() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    "DELETE FROM conversation_entity_links WHERE conversation_id = %s",
                    (uuid.UUID(conversation_id),),
                )

                for entity in entities:
                    cursor.execute(
                        """
                        INSERT INTO knowledge_entities (
                            entity_type,
                            canonical_name,
                            metadata
                        ) VALUES (%s, %s, %s::jsonb)
                        ON CONFLICT (entity_type, canonical_name) DO UPDATE
                        SET metadata = EXCLUDED.metadata
                        RETURNING id
                        """,
                        (
                            entity["entity_type"],
                            entity["canonical_name"],
                            json.dumps(entity.get("metadata") or {}),
                        ),
                    )
                    entity_row = cursor.fetchone()
                    if entity_row is None:
                        continue

                    cursor.execute(
                        """
                        INSERT INTO conversation_entity_links (
                            conversation_id,
                            entity_id,
                            link_type,
                            metadata
                        ) VALUES (%s, %s, %s, %s::jsonb)
                        """,
                        (
                            uuid.UUID(conversation_id),
                            entity_row[0],
                            entity["link_type"],
                            json.dumps(entity.get("metadata") or {}),
                        ),
                    )

                cursor.execute(
                    """
                    UPDATE conversations
                    SET latest_exported_at = NOW()
                    WHERE id = %s
                    """,
                    (uuid.UUID(conversation_id),),
                )
            connection.commit()
    except Exception:
        logger.exception("Failed to replace conversation entities for %s", conversation_id)
        return False

    return True


def get_conversation_entities(conversation_id: str) -> list[Dict[str, Any]]:
    """Return extracted entities linked to a conversation."""
    if not ensure_database():
        return []

    try:
        import psycopg.rows

        with _connect() as connection:
            with connection.cursor(row_factory=psycopg.rows.dict_row) as cursor:
                cursor.execute(
                    """
                    SELECT
                        entities.id,
                        entities.entity_type,
                        entities.canonical_name,
                        entities.metadata AS entity_metadata,
                        links.link_type,
                        links.metadata AS link_metadata,
                        links.created_at
                    FROM conversation_entity_links AS links
                    JOIN knowledge_entities AS entities
                      ON entities.id = links.entity_id
                    WHERE links.conversation_id = %s
                    ORDER BY
                        CASE links.link_type
                            WHEN 'theme' THEN 0
                            WHEN 'mentioned' THEN 1
                            WHEN 'uses_bundle' THEN 2
                            WHEN 'mentions_model' THEN 3
                            ELSE 4
                        END,
                        entities.canonical_name ASC
                    """,
                    (uuid.UUID(conversation_id),),
                )
                rows = cursor.fetchall()
    except Exception:
        logger.exception("Failed to load conversation entities for %s", conversation_id)
        return []

    return [
        {
            **dict(row),
            "created_at": row["created_at"].isoformat(),
        }
        for row in rows
    ]
