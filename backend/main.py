"""FastAPI backend for LLM Council."""

import logging
from pathlib import Path
from fastapi import Depends, FastAPI, HTTPException, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from pydantic import BaseModel
from typing import List, Dict, Any, Optional
import uuid
import json
import asyncio

from . import storage
from . import postgres_store
from . import markdown_exports
from . import auth
from .config import FRONTEND_DIST_DIR
from .semantic_search import search_transcripts
from .council import (
    CouncilQuorumError,
    build_council_usage_metadata,
    run_full_council,
    generate_conversation_title,
    stage1_collect_responses,
    stage2_collect_rankings,
    stage3_synthesize_final,
    calculate_aggregate_rankings,
)
from .postprocess import (
    MEMORY_FORMAT_VERSION,
    build_memory_record,
    build_turn_index_entries,
)
from .usage import summarize_conversation_usage

app = FastAPI(title="LLM Council API")
logger = logging.getLogger("llm_council.api")
LONG_CONVERSATION_MESSAGE_THRESHOLD = 12
GENERIC_PASTED_SUMMARY_PREFIXES = (
    "Pasted technical reference",
    "Pasted source context",
)

# Enable CORS for local development — allow any localhost port
app.add_middleware(
    CORSMiddleware,
    allow_origin_regex=r"http://(localhost|127\.0\.0\.1):\d+",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def csrf_middleware(request: Request, call_next):
    """Require a double-submit CSRF token for authenticated write requests."""
    try:
        auth.validate_csrf_request(request)
    except HTTPException as exc:
        return JSONResponse(
            status_code=exc.status_code,
            content={"detail": exc.detail},
        )
    return await call_next(request)


class CreateConversationRequest(BaseModel):
    """Request to create a new conversation."""
    pass


class AuthRequest(BaseModel):
    """Request payload for username/password auth."""
    username: str
    password: str


class CreateUserRequest(AuthRequest):
    """Request payload for admin-created local users."""
    role: str = "member"


class UpdateUserRequest(BaseModel):
    """Request payload for admin-managed local users."""
    role: Optional[str] = None
    disabled: Optional[bool] = None


class SendMessageRequest(BaseModel):
    """Request to send a message in a conversation."""
    content: str
    bundle_id: Optional[str] = None


class ModelBundlePayload(BaseModel):
    """Request payload for creating or updating a model bundle."""
    name: str
    council_models: List[str]
    chairman_model: str


class BundleReorderPayload(BaseModel):
    """Request payload for reordering bundles."""
    bundle_ids: List[str]


class ConversationTitlePayload(BaseModel):
    """Request payload for renaming a conversation."""
    title: str


class ConversationMetadata(BaseModel):
    """Conversation metadata for list view."""
    id: str
    owner_user_id: Optional[str] = None
    created_at: str
    title: str
    message_count: int
    archived: bool = False
    archived_at: Optional[str] = None


class Conversation(BaseModel):
    """Full conversation with all messages."""
    id: str
    owner_user_id: Optional[str] = None
    created_at: str
    title: str
    archived: bool = False
    archived_at: Optional[str] = None
    messages: List[Dict[str, Any]]


def frontend_dist_available() -> bool:
    """Return True when a built frontend bundle is available to serve."""
    return FRONTEND_DIST_DIR.is_dir() and (FRONTEND_DIST_DIR / "index.html").is_file()


def resolve_frontend_asset(relative_path: str) -> Optional[Path]:
    """Safely resolve a requested frontend asset within the built dist directory."""
    if not frontend_dist_available():
        return None

    normalized_path = relative_path.strip().lstrip("/")
    if not normalized_path or normalized_path.startswith("api/"):
        return None

    try:
        resolved = (FRONTEND_DIST_DIR / normalized_path).resolve()
        resolved.relative_to(FRONTEND_DIST_DIR.resolve())
    except ValueError:
        return None

    if resolved.is_file():
        return resolved
    return None


def serialize_conversation_overview(
    conversation_id: str,
    conversation: Dict[str, Any],
) -> Dict[str, Any]:
    """Build a compact response for indexed conversation browsing."""
    derived_memory = build_memory_record(conversation)
    derived_turn_index = build_turn_index_entries(conversation)
    latest_memory = postgres_store.get_latest_conversation_memory(conversation_id)
    latest_memory_is_current = bool(
        latest_memory
        and latest_memory.get("summary_json", {}).get("format_version") == MEMORY_FORMAT_VERSION
    )

    if latest_memory and latest_memory_is_current:
        memory_payload = {
            "version": latest_memory["version"],
            "summary_text": latest_memory["summary_text"],
            "summary_json": latest_memory.get("summary_json"),
            "token_estimate": latest_memory["token_estimate"],
            "source_turn_count": latest_memory["source_turn_count"],
            "updated_at": latest_memory["created_at"].isoformat(),
            "source": "postgres",
        }
    else:
        memory_payload = {
            "version": 0,
            "summary_text": derived_memory["summary_text"],
            "summary_json": derived_memory["summary_json"],
            "token_estimate": derived_memory["token_estimate"],
            "source_turn_count": derived_memory["source_turn_count"],
            "updated_at": derived_memory["summary_json"]["updated_at"],
            "source": "transcript",
        }

    stored_turn_index = postgres_store.get_conversation_turn_index(conversation_id)
    stored_turn_index_looks_generic = bool(
        stored_turn_index
        and derived_turn_index
        and stored_turn_index[0].get("short_highlight", "").startswith(GENERIC_PASTED_SUMMARY_PREFIXES)
        and stored_turn_index[0].get("short_highlight") != derived_turn_index[0].get("short_highlight")
    )

    if stored_turn_index and not stored_turn_index_looks_generic:
        turn_index = [
            {
                **entry,
                "created_at": entry["created_at"].isoformat(),
            }
            for entry in stored_turn_index
        ]
    else:
        turn_index = [
            {
                **entry,
                "created_at": entry["created_at"],
            }
            for entry in derived_turn_index
        ]

    return {
        "conversation_id": conversation_id,
        "title": conversation.get("title", "New Conversation"),
        "message_count": len(conversation.get("messages", [])),
        "default_transcript_collapsed": len(conversation.get("messages", []))
        > LONG_CONVERSATION_MESSAGE_THRESHOLD,
        "usage_summary": summarize_conversation_usage(conversation),
        "memory": memory_payload,
        "turn_index": turn_index,
    }


def maybe_enqueue_overview_backfill(conversation: Dict[str, Any]) -> Dict[str, bool]:
    """Ensure older conversations eventually get rolling memory, turn index, and exports."""
    if not postgres_store.is_configured():
        return {
            "memory_pending": False,
            "turn_index_pending": False,
        }

    conversation_id = conversation["id"]
    transcript_path = storage.get_conversation_path(conversation_id)
    postgres_store.sync_conversation_metadata(conversation, transcript_path)

    has_messages = bool(conversation.get("messages"))
    if not has_messages:
        return {
            "memory_pending": False,
            "turn_index_pending": False,
        }

    memory_pending = False
    turn_index_pending = False
    payload = {
        "transcript_path": transcript_path,
        "message_count": len(conversation.get("messages", [])),
        "assistant_message_index": len(conversation.get("messages", [])) - 1,
        "backfill": True,
    }

    latest_memory = postgres_store.get_latest_conversation_memory(conversation_id)
    memory_is_stale = bool(
        latest_memory
        and latest_memory.get("summary_json", {}).get("format_version") != MEMORY_FORMAT_VERSION
    )
    if latest_memory is None or memory_is_stale:
        memory_pending = postgres_store.has_active_export_job(conversation_id, "refresh_memory")
        if not memory_pending:
            memory_pending = postgres_store.enqueue_export_job(
                conversation_id,
                "refresh_memory",
                payload,
            )

    stored_turn_index = postgres_store.get_conversation_turn_index(conversation_id)
    has_turn_index = bool(stored_turn_index)
    derived_turn_index = build_turn_index_entries(conversation) if has_turn_index else []
    turn_index_is_stale = bool(
        stored_turn_index
        and derived_turn_index
        and stored_turn_index[0].get("short_highlight", "").startswith(GENERIC_PASTED_SUMMARY_PREFIXES)
        and stored_turn_index[0].get("short_highlight") != derived_turn_index[0].get("short_highlight")
    )
    if not has_turn_index or turn_index_is_stale:
        turn_index_pending = postgres_store.has_active_export_job(conversation_id, "index_turns")
        if not turn_index_pending:
            turn_index_pending = postgres_store.enqueue_export_job(
                conversation_id,
                "index_turns",
                payload,
            )

    if markdown_exports.conversation_exports_missing(conversation_id):
        export_pending = postgres_store.has_active_export_job(conversation_id, "export_markdown")
        if not export_pending:
            postgres_store.enqueue_export_job(
                conversation_id,
                "export_markdown",
                payload,
            )

    has_semantic_chunks = postgres_store.has_semantic_chunks(conversation_id)
    if not has_semantic_chunks:
        semantic_pending = postgres_store.has_active_export_job(conversation_id, "chunk_semantic")
        if not semantic_pending:
            postgres_store.enqueue_export_job(
                conversation_id,
                "chunk_semantic",
                payload,
            )

    has_entity_links = postgres_store.has_conversation_entity_links(conversation_id)
    if not has_entity_links:
        entity_pending = postgres_store.has_active_export_job(conversation_id, "extract_entities")
        if not entity_pending:
            postgres_store.enqueue_export_job(
                conversation_id,
                "extract_entities",
                payload,
            )

    return {
        "memory_pending": memory_pending,
        "turn_index_pending": turn_index_pending,
    }


def backfill_existing_conversations():
    """Sync transcript metadata and queue overview jobs for legacy conversations."""
    for conversation_id in storage.list_all_conversation_ids():
        conversation = storage.get_conversation(conversation_id)
        if conversation is None:
            continue
        maybe_enqueue_overview_backfill(conversation)


def normalize_bundle_payload(payload: ModelBundlePayload) -> Dict[str, Any]:
    """Normalize and validate editable bundle fields."""
    name = payload.name.strip()
    council_models = [
        model.strip()
        for model in payload.council_models
        if model.strip()
    ]
    chairman_model = payload.chairman_model.strip()

    if not name:
        raise HTTPException(status_code=400, detail="Bundle name is required")
    if not council_models:
        raise HTTPException(status_code=400, detail="At least one council model is required")
    if not chairman_model:
        raise HTTPException(status_code=400, detail="Chairman model is required")

    return {
        "name": name,
        "council_models": council_models,
        "chairman_model": chairman_model,
    }


def resolve_bundle(bundle_id: Optional[str]) -> Dict[str, Any]:
    """Resolve a selected bundle or raise a client error."""
    bundle = storage.get_model_bundle(bundle_id)
    if bundle is None:
        raise HTTPException(status_code=404, detail="Model bundle not found")
    return bundle


def validate_auth_payload(username: str, password: str) -> tuple[str, str]:
    """Normalize and validate local auth input."""
    normalized_username = " ".join(username.strip().split())
    if not normalized_username:
        raise HTTPException(status_code=400, detail="Username is required")
    if len(normalized_username) > 80:
        raise HTTPException(status_code=400, detail="Username is too long")
    if len(password) < 8:
        raise HTTPException(status_code=400, detail="Password must be at least 8 characters")
    return normalized_username, password


def require_owned_conversation(
    conversation_id: str,
    user: Dict[str, Any],
) -> Dict[str, Any]:
    """Load a conversation and enforce current-user ownership."""
    conversation = storage.get_conversation(conversation_id)
    if conversation is None or conversation.get("owner_user_id") != user["id"]:
        raise HTTPException(status_code=404, detail="Conversation not found")
    return conversation


def assign_legacy_conversations_to_admin(admin_user: Dict[str, Any]) -> None:
    """Assign pre-auth transcripts/metadata to the first admin user."""
    assigned_count = storage.assign_unowned_conversations(admin_user["id"])
    postgres_store.assign_unowned_conversations(admin_user["id"])
    if assigned_count:
        logger.info(
            "Assigned %s legacy transcript(s) to admin user %s",
            assigned_count,
            admin_user["username"],
        )


def build_council_prompt(conversation: Dict[str, Any], content: str) -> str:
    """Build follow-up context from rolling memory plus the latest final verdict."""
    latest_memory = postgres_store.get_latest_conversation_memory(conversation["id"])
    memory_summary_text = ""
    if latest_memory and latest_memory.get("summary_text"):
        memory_summary_text = latest_memory["summary_text"]
    elif conversation.get("messages"):
        memory_summary_text = build_memory_record(conversation)["summary_text"]

    for message in reversed(conversation["messages"]):
        final_response = message.get("stage3", {}).get("response")
        if message.get("role") == "assistant" and final_response:
            if memory_summary_text:
                return (
                    "Rolling summary:\n"
                    f"{memory_summary_text}\n\n"
                    "Previous final council verdict:\n"
                    f"{final_response}\n\n"
                    "Follow-up question:\n"
                    f"{content}"
                )
            return (
                "Previous final council verdict:\n"
                f"{final_response}\n\n"
                "Follow-up question:\n"
                f"{content}"
            )

    if memory_summary_text:
        return (
            "Rolling summary:\n"
            f"{memory_summary_text}\n\n"
            "Follow-up question:\n"
            f"{content}"
        )

    return content


def enqueue_postprocess_jobs(conversation_id: str):
    """Best-effort enqueue of background jobs after a successful council turn."""
    conversation = storage.get_conversation(conversation_id)
    if conversation is None:
        return

    payload = {
        "transcript_path": storage.get_conversation_path(conversation_id),
        "message_count": len(conversation.get("messages", [])),
        "assistant_message_index": len(conversation.get("messages", [])) - 1,
    }

    for job_type in ("refresh_memory", "index_turns", "export_markdown", "chunk_semantic", "extract_entities"):
        if postgres_store.is_configured() and postgres_store.has_active_export_job(conversation_id, job_type):
            continue
        enqueued = postgres_store.enqueue_export_job(
            conversation_id,
            job_type,
            payload,
        )
        if not enqueued and postgres_store.is_configured():
            logger.warning(
                "Failed to enqueue post-process job %s for conversation %s",
                job_type,
                conversation_id,
            )


def enqueue_export_markdown_job(conversation_id: str):
    """Best-effort enqueue of the markdown export job for metadata-only updates."""
    conversation = storage.get_conversation(conversation_id)
    if conversation is None:
        return

    if not postgres_store.is_configured():
        return

    if postgres_store.has_active_export_job(conversation_id, "export_markdown"):
        return

    payload = {
        "transcript_path": storage.get_conversation_path(conversation_id),
        "message_count": len(conversation.get("messages", [])),
        "assistant_message_index": len(conversation.get("messages", [])) - 1,
        "metadata_only": True,
    }
    enqueued = postgres_store.enqueue_export_job(
        conversation_id,
        "export_markdown",
        payload,
    )
    if not enqueued:
        logger.warning(
            "Failed to enqueue markdown export job for conversation %s",
            conversation_id,
        )


@app.on_event("startup")
async def startup_event():
    """Prepare local storage and opportunistically initialize Postgres."""
    storage.ensure_data_dir()
    storage.ensure_bundle_store()
    logger.info(
        "frontend_dist_dir=%s frontend_built=%s",
        FRONTEND_DIST_DIR,
        frontend_dist_available(),
    )

    if postgres_store.is_configured():
        initialized = postgres_store.ensure_database()
        if not initialized:
            logger.warning("Postgres is configured but metadata initialization is unavailable")
        else:
            first_admin = postgres_store.get_first_admin_user()
            if first_admin:
                assign_legacy_conversations_to_admin(first_admin)
            backfill_existing_conversations()


@app.get("/api/health")
async def health():
    """Health check endpoint for container orchestration."""
    return {"status": "ok", "service": "LLM Council API"}


@app.get("/api/auth/status")
async def auth_status(request: Request, response: Response):
    """Return auth setup status and the current user if logged in."""
    status = auth.auth_status()
    current_user = auth.get_optional_user(request) if status["configured"] else None
    if current_user and not request.cookies.get(auth.CSRF_COOKIE_NAME):
        auth.set_csrf_cookie(response)
    return {
        **status,
        "user": auth.public_user(current_user) if current_user else None,
    }


@app.post("/api/auth/bootstrap")
async def bootstrap_admin(request: AuthRequest, response: Response):
    """Create the first local admin user."""
    status = auth.auth_status()
    if not status["configured"]:
        raise HTTPException(status_code=503, detail="Postgres is required for local auth")
    if not status["bootstrap_required"]:
        raise HTTPException(status_code=409, detail="Admin user already exists")

    username, password = validate_auth_payload(request.username, request.password)
    user = postgres_store.create_user(username, auth.hash_password(password), "admin")
    if user is None:
        raise HTTPException(status_code=400, detail="Could not create admin user")

    assign_legacy_conversations_to_admin(user)
    auth.create_session(response, user)
    return {"user": auth.public_user(user)}


@app.post("/api/auth/login")
async def login(request: AuthRequest, response: Response):
    """Log in with a local username and password."""
    username = request.username.strip()
    user = postgres_store.get_user_by_username(username)
    if (
        user is None
        or user.get("disabled_at") is not None
        or not auth.verify_password(request.password, user.get("password_hash", ""))
    ):
        raise HTTPException(status_code=401, detail="Invalid username or password")

    auth.create_session(response, user)
    return {"user": auth.public_user(user)}


@app.post("/api/auth/logout")
async def logout(request: Request, response: Response):
    """Log out the current browser session."""
    auth.clear_session(request, response)
    return {"status": "logged_out"}


@app.get("/api/auth/me")
async def current_user(
    request: Request,
    response: Response,
    user: Dict[str, Any] = Depends(auth.require_user),
):
    """Return the current authenticated user."""
    if not request.cookies.get(auth.CSRF_COOKIE_NAME):
        auth.set_csrf_cookie(response)
    return {"user": auth.public_user(user)}


@app.get("/api/users")
async def list_users(admin_user: Dict[str, Any] = Depends(auth.require_admin)):
    """List local users. Admin-only."""
    del admin_user
    return {
        "users": [
            auth.public_user(user) | {"disabled_at": user.get("disabled_at")}
            for user in postgres_store.list_users()
        ]
    }


@app.get("/api/system/status")
async def system_status(admin_user: Dict[str, Any] = Depends(auth.require_admin)):
    """Return operational status for the local instance. Admin-only."""
    del admin_user
    return {
        "database_configured": postgres_store.is_configured(),
        "export_jobs": postgres_store.get_export_job_status_summary(),
    }


@app.post("/api/users")
async def create_user(
    request: CreateUserRequest,
    admin_user: Dict[str, Any] = Depends(auth.require_admin),
):
    """Create a local user. Admin-only."""
    del admin_user
    username, password = validate_auth_payload(request.username, request.password)
    role = request.role.strip().lower()
    if role not in {"admin", "member"}:
        raise HTTPException(status_code=400, detail="Role must be admin or member")

    user = postgres_store.create_user(username, auth.hash_password(password), role)
    if user is None:
        raise HTTPException(status_code=400, detail="Could not create user")
    return {"user": auth.public_user(user)}


@app.patch("/api/users/{user_id}")
async def update_user(
    user_id: str,
    request: UpdateUserRequest,
    admin_user: Dict[str, Any] = Depends(auth.require_admin),
):
    """Update a local user's role or enabled state. Admin-only."""
    target_user = postgres_store.get_user_by_id(user_id)
    if target_user is None:
        raise HTTPException(status_code=404, detail="User not found")

    role = request.role.strip().lower() if request.role is not None else None
    if role is not None and role not in {"admin", "member"}:
        raise HTTPException(status_code=400, detail="Role must be admin or member")

    disabling = request.disabled is True and target_user.get("disabled_at") is None
    demoting_enabled_admin = (
        role == "member"
        and target_user.get("role") == "admin"
        and target_user.get("disabled_at") is None
    )

    if target_user["id"] == admin_user["id"] and request.disabled is True:
        raise HTTPException(status_code=400, detail="You cannot disable your own account")

    if (disabling or demoting_enabled_admin) and target_user.get("role") == "admin":
        if postgres_store.count_enabled_admins() <= 1:
            raise HTTPException(status_code=400, detail="At least one enabled admin is required")

    updated = postgres_store.update_user(
        user_id,
        role=role,
        disabled=request.disabled,
    )
    if updated is None:
        raise HTTPException(status_code=400, detail="Could not update user")

    if request.disabled is True:
        postgres_store.delete_user_sessions(user_id)

    return {"user": auth.public_user(updated) | {"disabled_at": updated.get("disabled_at")}}


@app.get("/", include_in_schema=False)
async def root():
    """Serve the built frontend when available, otherwise fall back to API health JSON."""
    if frontend_dist_available():
        return FileResponse(FRONTEND_DIST_DIR / "index.html")
    return {"status": "ok", "service": "LLM Council API"}


@app.get("/api/conversations", response_model=List[ConversationMetadata])
async def list_conversations(
    archived: bool = False,
    user: Dict[str, Any] = Depends(auth.require_user),
):
    """List all conversations (metadata only)."""
    return storage.list_conversations(archived=archived, owner_user_id=user["id"])


@app.get("/api/model-bundles")
async def list_model_bundles(user: Dict[str, Any] = Depends(auth.require_user)):
    """List configured model bundles."""
    del user
    return storage.list_model_bundles()


@app.post("/api/model-bundles")
async def create_model_bundle(
    request: ModelBundlePayload,
    admin_user: Dict[str, Any] = Depends(auth.require_admin),
):
    """Create a model bundle."""
    del admin_user
    bundle = normalize_bundle_payload(request)
    bundle["id"] = str(uuid.uuid4())
    return storage.create_model_bundle(bundle)


@app.put("/api/model-bundles/{bundle_id}")
async def update_model_bundle(
    bundle_id: str,
    request: ModelBundlePayload,
    admin_user: Dict[str, Any] = Depends(auth.require_admin),
):
    """Update a model bundle."""
    del admin_user
    bundle = normalize_bundle_payload(request)
    updated = storage.update_model_bundle(bundle_id, bundle)
    if updated is None:
        raise HTTPException(status_code=404, detail="Model bundle not found")
    return updated


@app.post("/api/model-bundles/reorder")
async def reorder_model_bundles(
    request: BundleReorderPayload,
    admin_user: Dict[str, Any] = Depends(auth.require_admin),
):
    """Reorder bundles by explicit id list."""
    del admin_user
    try:
        return storage.reorder_model_bundles(request.bundle_ids)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/model-bundles/{bundle_id}/default")
async def set_default_model_bundle(
    bundle_id: str,
    admin_user: Dict[str, Any] = Depends(auth.require_admin),
):
    """Set the default bundle used when no user selection is stored."""
    del admin_user
    bundles = storage.set_default_model_bundle(bundle_id)
    if bundles is None:
        raise HTTPException(status_code=404, detail="Model bundle not found")
    return bundles


@app.delete("/api/model-bundles/{bundle_id}")
async def delete_model_bundle(
    bundle_id: str,
    admin_user: Dict[str, Any] = Depends(auth.require_admin),
):
    """Delete a model bundle."""
    del admin_user
    deleted = storage.delete_model_bundle(bundle_id)
    if not deleted:
        raise HTTPException(
            status_code=400,
            detail="Bundle not found or cannot delete the last bundle"
        )
    return {"status": "deleted"}


@app.post("/api/conversations", response_model=Conversation)
async def create_conversation(
    request: CreateConversationRequest,
    user: Dict[str, Any] = Depends(auth.require_user),
):
    """Create a new conversation."""
    del request
    conversation_id = str(uuid.uuid4())
    conversation = storage.create_conversation(conversation_id, owner_user_id=user["id"])
    return conversation


@app.get("/api/conversations/{conversation_id}", response_model=Conversation)
async def get_conversation(
    conversation_id: str,
    user: Dict[str, Any] = Depends(auth.require_user),
):
    """Get a specific conversation with all its messages."""
    return require_owned_conversation(conversation_id, user)


@app.get("/api/conversations/{conversation_id}/overview")
async def get_conversation_overview(
    conversation_id: str,
    user: Dict[str, Any] = Depends(auth.require_user),
):
    """Return compact memory and turn index data for a conversation."""
    conversation = require_owned_conversation(conversation_id, user)
    pending_state = maybe_enqueue_overview_backfill(conversation)
    overview = serialize_conversation_overview(conversation_id, conversation)
    overview.update(pending_state)
    return overview


@app.get("/api/search")
async def search_conversations(
    q: str,
    limit: int = 20,
    start_at: Optional[str] = None,
    end_at: Optional[str] = None,
    user: Dict[str, Any] = Depends(auth.require_user),
):
    """Search conversations and transcript-derived semantic chunks."""
    query = q.strip()
    if not query:
        return {"query": "", "results": []}

    safe_limit = max(1, min(limit, 50))
    has_time_filters = bool((start_at or "").strip() or (end_at or "").strip())
    if has_time_filters:
        results = search_transcripts(
            query,
            safe_limit,
            start_at=start_at,
            end_at=end_at,
            owner_user_id=user["id"],
        )
    elif postgres_store.is_configured():
        results = postgres_store.search_semantic_chunks(query, safe_limit, owner_user_id=user["id"])
        if not results:
            results = search_transcripts(query, safe_limit, owner_user_id=user["id"])
    else:
        results = search_transcripts(query, safe_limit, owner_user_id=user["id"])

    return {
        "query": query,
        "filters": {
            "start_at": start_at,
            "end_at": end_at,
        },
        "results": results,
    }


@app.get("/api/conversations/{conversation_id}/entities")
async def get_conversation_entities(
    conversation_id: str,
    user: Dict[str, Any] = Depends(auth.require_user),
):
    """Return extracted entities and themes for a conversation."""
    conversation = require_owned_conversation(conversation_id, user)

    if not postgres_store.is_configured():
        return {
            "conversation_id": conversation_id,
            "entities": [],
            "pending": False,
        }

    pending = False
    if not postgres_store.has_conversation_entity_links(conversation_id):
        pending = postgres_store.has_active_export_job(conversation_id, "extract_entities")
        if not pending:
            pending = postgres_store.enqueue_export_job(
                conversation_id,
                "extract_entities",
                {
                    "transcript_path": storage.get_conversation_path(conversation_id),
                    "message_count": len(conversation.get("messages", [])),
                    "assistant_message_index": len(conversation.get("messages", [])) - 1,
                    "backfill": True,
                },
            )

    return {
        "conversation_id": conversation_id,
        "entities": postgres_store.get_conversation_entities(conversation_id),
        "pending": pending,
    }


@app.post("/api/conversations/{conversation_id}/archive", response_model=Conversation)
async def archive_conversation(
    conversation_id: str,
    user: Dict[str, Any] = Depends(auth.require_user),
):
    """Archive a conversation so it no longer appears in the main chat list."""
    require_owned_conversation(conversation_id, user)
    conversation = storage.set_conversation_archived(conversation_id, True)
    if conversation is None:
        raise HTTPException(status_code=404, detail="Conversation not found")
    enqueue_export_markdown_job(conversation_id)
    return conversation


@app.post("/api/conversations/{conversation_id}/restore", response_model=Conversation)
async def restore_conversation(
    conversation_id: str,
    user: Dict[str, Any] = Depends(auth.require_user),
):
    """Restore an archived conversation to the main chat list."""
    require_owned_conversation(conversation_id, user)
    conversation = storage.set_conversation_archived(conversation_id, False)
    if conversation is None:
        raise HTTPException(status_code=404, detail="Conversation not found")
    enqueue_export_markdown_job(conversation_id)
    return conversation


@app.patch("/api/conversations/{conversation_id}", response_model=Conversation)
async def rename_conversation(
    conversation_id: str,
    request: ConversationTitlePayload,
    user: Dict[str, Any] = Depends(auth.require_user),
):
    """Rename a conversation."""
    require_owned_conversation(conversation_id, user)
    title = request.title.strip()
    if not title:
        raise HTTPException(status_code=400, detail="Conversation title is required")

    if len(title) > 80:
        title = title[:80]

    storage.update_conversation_title(conversation_id, title)
    conversation = storage.get_conversation(conversation_id)
    if conversation is None:
        raise HTTPException(status_code=404, detail="Conversation not found")
    enqueue_export_markdown_job(conversation_id)
    return conversation


@app.delete("/api/conversations/{conversation_id}")
async def delete_conversation(
    conversation_id: str,
    user: Dict[str, Any] = Depends(auth.require_user),
):
    """Permanently delete a conversation."""
    require_owned_conversation(conversation_id, user)
    deleted = storage.delete_conversation(conversation_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Conversation not found")
    return {"status": "deleted"}


@app.post("/api/conversations/{conversation_id}/message")
async def send_message(
    conversation_id: str,
    request: SendMessageRequest,
    user: Dict[str, Any] = Depends(auth.require_user),
):
    """
    Send a message and run the 3-stage council process.
    Returns the complete response with all stages.
    """
    # Check if conversation exists
    conversation = require_owned_conversation(conversation_id, user)

    bundle = resolve_bundle(request.bundle_id)
    council_prompt = build_council_prompt(conversation, request.content)

    # Check if this is the first message
    is_first_message = len(conversation["messages"]) == 0

    # Add user message
    storage.add_user_message(conversation_id, request.content, bundle)

    title_result = None
    # If this is the first message, generate a title
    if is_first_message:
        title_result = await generate_conversation_title(request.content)
        storage.update_conversation_title(conversation_id, title_result["title"])
        title_usage_requests = [title_result.get("usage")]
    else:
        title_usage_requests = None

    # Run the 3-stage council process
    try:
        stage1_results, stage2_results, stage3_result, metadata = await run_full_council(
            council_prompt,
            bundle["council_models"],
            bundle["chairman_model"],
            bundle,
            extra_usage_requests=title_usage_requests,
        )
    except CouncilQuorumError as e:
        error_metadata = None
        if title_result and title_result.get("usage"):
            error_metadata = {
                "usage": {
                    "requests": [title_result["usage"]],
                    "summary": build_council_usage_metadata(
                        [],
                        [],
                        {"usage": None},
                        extra_requests=[title_result["usage"]],
                    )["summary"],
                },
            }
        storage.add_assistant_error(conversation_id, e.to_payload(), bundle, metadata=error_metadata)
        raise HTTPException(status_code=424, detail=e.to_payload()) from e

    # Add assistant message with all stages
    storage.add_assistant_message(
        conversation_id,
        stage1_results,
        stage2_results,
        stage3_result,
        metadata,
        bundle
    )
    enqueue_postprocess_jobs(conversation_id)

    # Return the complete response with metadata
    return {
        "stage1": stage1_results,
        "stage2": stage2_results,
        "stage3": stage3_result,
        "metadata": metadata
    }


@app.post("/api/conversations/{conversation_id}/message/stream")
async def send_message_stream(
    conversation_id: str,
    request: SendMessageRequest,
    user: Dict[str, Any] = Depends(auth.require_user),
):
    """
    Send a message and stream the 3-stage council process.
    Returns Server-Sent Events as each stage completes.
    """
    # Check if conversation exists
    conversation = require_owned_conversation(conversation_id, user)

    bundle = resolve_bundle(request.bundle_id)
    council_prompt = build_council_prompt(conversation, request.content)

    # Check if this is the first message
    is_first_message = len(conversation["messages"]) == 0

    async def event_generator():
        title_task = None
        title_result = None
        try:
            # Add user message
            storage.add_user_message(conversation_id, request.content, bundle)

            # Start title generation in parallel (don't await yet)
            if is_first_message:
                title_task = asyncio.create_task(generate_conversation_title(request.content))

            # Stage 1: Collect responses
            yield f"data: {json.dumps({'type': 'stage1_start'})}\n\n"
            stage1_results = await stage1_collect_responses(
                council_prompt,
                bundle["council_models"]
            )
            yield f"data: {json.dumps({'type': 'stage1_complete', 'data': stage1_results})}\n\n"

            # Stage 2: Collect rankings
            yield f"data: {json.dumps({'type': 'stage2_start'})}\n\n"
            stage2_results, label_to_model = await stage2_collect_rankings(
                council_prompt,
                stage1_results,
                bundle["council_models"]
            )
            aggregate_rankings = calculate_aggregate_rankings(stage2_results, label_to_model)
            metadata = {
                "label_to_model": label_to_model,
                "aggregate_rankings": aggregate_rankings,
                "bundle": {
                    "id": bundle["id"],
                    "name": bundle["name"],
                    "chairman_model": bundle["chairman_model"],
                    "council_models": bundle["council_models"],
                }
            }
            yield f"data: {json.dumps({'type': 'stage2_complete', 'data': stage2_results, 'metadata': metadata})}\n\n"

            # Stage 3: Synthesize final answer
            yield f"data: {json.dumps({'type': 'stage3_start'})}\n\n"
            stage3_result = await stage3_synthesize_final(
                council_prompt,
                stage1_results,
                stage2_results,
                bundle["chairman_model"]
            )
            metadata["usage"] = build_council_usage_metadata(
                stage1_results,
                stage2_results,
                stage3_result,
            )
            yield f"data: {json.dumps({'type': 'stage3_complete', 'data': stage3_result, 'metadata': metadata})}\n\n"

            # Save complete assistant message
            storage.add_assistant_message(
                conversation_id,
                stage1_results,
                stage2_results,
                stage3_result,
                metadata,
                bundle
            )
            enqueue_postprocess_jobs(conversation_id)

            # Wait for title generation after saving the assistant message, so a
            # slow title request cannot prevent the council result from persisting.
            if title_task:
                title_result = await title_task
                storage.update_conversation_title(conversation_id, title_result["title"])
                metadata["usage"] = build_council_usage_metadata(
                    stage1_results,
                    stage2_results,
                    stage3_result,
                    extra_requests=[title_result.get("usage")],
                )
                storage.merge_latest_assistant_message_metadata(
                    conversation_id,
                    {
                        "usage": metadata["usage"],
                    },
                )
                yield f"data: {json.dumps({'type': 'title_complete', 'data': {'title': title_result['title'], 'usage': title_result.get('usage'), 'usage_summary': metadata['usage']}})}\n\n"

            # Send completion event
            yield f"data: {json.dumps({'type': 'complete'})}\n\n"

        except CouncilQuorumError as e:
            payload = e.to_payload()
            error_metadata = None
            if title_task:
                if title_task.done() and not title_task.cancelled():
                    try:
                        title_result = title_task.result()
                    except Exception:
                        title_result = None
                else:
                    title_task.cancel()

            if title_result and title_result.get("usage"):
                error_metadata = {
                    "usage": {
                        "requests": [title_result["usage"]],
                        "summary": build_council_usage_metadata(
                            [],
                            [],
                            {"usage": None},
                            extra_requests=[title_result["usage"]],
                        )["summary"],
                    },
                }

            if title_result:
                storage.update_conversation_title(conversation_id, title_result["title"])
                yield f"data: {json.dumps({'type': 'title_complete', 'data': {'title': title_result['title'], 'usage': title_result.get('usage'), 'usage_summary': error_metadata['usage'] if error_metadata else None}})}\n\n"

            storage.add_assistant_error(conversation_id, payload, bundle, metadata=error_metadata)
            yield f"data: {json.dumps({'type': 'error', 'message': payload['message'], 'details': payload})}\n\n"
        except Exception as e:
            if title_task:
                title_task.cancel()
            # Send error event
            yield f"data: {json.dumps({'type': 'error', 'message': str(e)})}\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
        }
    )


@app.get("/{full_path:path}", include_in_schema=False)
async def serve_frontend_app(full_path: str):
    """Serve built frontend assets and fall back to the SPA entrypoint."""
    if full_path.startswith("api/"):
        raise HTTPException(status_code=404, detail="Not found")

    asset_path = resolve_frontend_asset(full_path)
    if asset_path is not None:
        return FileResponse(asset_path)

    if frontend_dist_available():
        return FileResponse(FRONTEND_DIST_DIR / "index.html")

    raise HTTPException(status_code=404, detail="Not found")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8002)
