"""JSON-based storage for conversations."""

import json
import os
import re
from datetime import datetime, timedelta, timezone
from typing import List, Dict, Any, Optional
from pathlib import Path
from . import postgres_store
from .config import (
    TRANSCRIPTS_DIR,
    EXPORTS_DIR,
    OBSIDIAN_EXPORTS_DIR,
    BUNDLES_PATH,
    DEFAULT_COUNCIL_BUNDLES,
)


_MANUAL_BUNDLE_PREFIX_RE = re.compile(r"^#\d+\s*-\s*")


def _timestamp_now() -> str:
    """Return a current UTC timestamp for persisted records."""
    return datetime.now(timezone.utc).isoformat()


def _parse_iso_datetime(value: Optional[str]) -> Optional[datetime]:
    """Parse a stored ISO timestamp."""
    if not value:
        return None

    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            return parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)
    except ValueError:
        return None


def _normalize_message_timestamps(conversation: Dict[str, Any]) -> bool:
    """Backfill per-message timestamps for legacy transcripts that lacked them."""
    messages = conversation.get("messages", [])
    if not isinstance(messages, list) or not messages:
        return False

    changed = False
    fallback_base = _parse_iso_datetime(conversation.get("created_at")) or datetime.now(timezone.utc)

    for index, message in enumerate(messages):
        if message.get("created_at"):
            continue

        # Legacy transcripts did not store turn timestamps. Preserve a stable,
        # ordered fallback derived from the conversation creation time.
        message["created_at"] = (fallback_base + timedelta(seconds=index)).isoformat()
        changed = True

    return changed


def _clean_bundle_name(name: str) -> str:
    """Remove legacy manual numbering prefixes from bundle names."""
    cleaned = _MANUAL_BUNDLE_PREFIX_RE.sub("", (name or "").strip())
    return cleaned or "Untitled Bundle"


def _normalize_bundle_positions(bundles: List[Dict[str, Any]]) -> tuple[List[Dict[str, Any]], bool]:
    """Ensure bundles have stable names and sequential positions."""
    changed = False

    sorted_bundles = sorted(
        bundles,
        key=lambda bundle: (
            bundle.get("position", float("inf")),
            bundle.get("created_at", ""),
            bundle.get("name", ""),
        ),
    )

    normalized_bundles = []
    for index, bundle in enumerate(sorted_bundles, start=1):
        normalized_bundle = dict(bundle)
        cleaned_name = _clean_bundle_name(normalized_bundle.get("name", ""))
        if cleaned_name != normalized_bundle.get("name", ""):
            normalized_bundle["name"] = cleaned_name
            changed = True

        if normalized_bundle.get("position") != index:
            normalized_bundle["position"] = index
            changed = True

        normalized_bundles.append(normalized_bundle)

    default_index = next(
        (index for index, bundle in enumerate(normalized_bundles) if bundle.get("is_default")),
        None,
    )
    if default_index is None and normalized_bundles:
        default_index = 0

    for index, bundle in enumerate(normalized_bundles):
        should_be_default = index == default_index
        if bool(bundle.get("is_default")) != should_be_default:
            bundle["is_default"] = should_be_default
            changed = True

    return normalized_bundles, changed


def ensure_data_dir():
    """Ensure transcript and export directories exist."""
    TRANSCRIPTS_DIR.mkdir(parents=True, exist_ok=True)
    EXPORTS_DIR.mkdir(parents=True, exist_ok=True)
    OBSIDIAN_EXPORTS_DIR.mkdir(parents=True, exist_ok=True)


def ensure_bundle_store():
    """Ensure the model bundle store exists."""
    BUNDLES_PATH.parent.mkdir(parents=True, exist_ok=True)

    if BUNDLES_PATH.exists():
        return

    now = _timestamp_now()
    bundles = []
    for bundle in DEFAULT_COUNCIL_BUNDLES:
        bundles.append({
            **bundle,
            "name": _clean_bundle_name(bundle.get("name", "")),
            "position": len(bundles) + 1,
            "is_default": len(bundles) == 0,
            "created_at": now,
            "updated_at": now,
        })

    with open(BUNDLES_PATH, 'w') as f:
        json.dump({"bundles": bundles}, f, indent=2)


def load_bundle_store() -> Dict[str, Any]:
    """Load model bundles from storage."""
    ensure_bundle_store()

    with open(BUNDLES_PATH, 'r') as f:
        data = json.load(f)

    if "bundles" not in data or not isinstance(data["bundles"], list):
        return {"bundles": []}

    normalized_bundles, changed = _normalize_bundle_positions(data["bundles"])
    if changed:
        data["bundles"] = normalized_bundles
        save_bundle_store(data)

    return data


def save_bundle_store(data: Dict[str, Any]):
    """Save model bundles to storage."""
    Path(BUNDLES_PATH).parent.mkdir(parents=True, exist_ok=True)

    with open(BUNDLES_PATH, 'w') as f:
        json.dump(data, f, indent=2)


def list_model_bundles() -> List[Dict[str, Any]]:
    """List all configured model bundles."""
    data = load_bundle_store()
    return data["bundles"]


def get_model_bundle(bundle_id: Optional[str]) -> Optional[Dict[str, Any]]:
    """Get a model bundle by id, or the default configured bundle if id is empty."""
    bundles = list_model_bundles()
    if not bundles:
        return None

    if not bundle_id:
        return next((bundle for bundle in bundles if bundle.get("is_default")), bundles[0])

    return next((bundle for bundle in bundles if bundle["id"] == bundle_id), None)


def create_model_bundle(bundle: Dict[str, Any]) -> Dict[str, Any]:
    """Create a new model bundle."""
    data = load_bundle_store()
    now = _timestamp_now()
    new_bundle = {
        **bundle,
        "name": _clean_bundle_name(bundle.get("name", "")),
        "position": len(data["bundles"]) + 1,
        "is_default": len(data["bundles"]) == 0,
        "created_at": now,
        "updated_at": now,
    }

    data["bundles"].append(new_bundle)
    save_bundle_store(data)
    return new_bundle


def update_model_bundle(bundle_id: str, updates: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Update an existing model bundle."""
    data = load_bundle_store()

    for index, bundle in enumerate(data["bundles"]):
        if bundle["id"] == bundle_id:
            updated_bundle = {
                **bundle,
                **updates,
                "id": bundle_id,
                "name": _clean_bundle_name(updates.get("name", bundle.get("name", ""))),
                "position": bundle.get("position", index + 1),
                "created_at": bundle.get("created_at", _timestamp_now()),
                "updated_at": _timestamp_now(),
            }
            data["bundles"][index] = updated_bundle
            data["bundles"], _ = _normalize_bundle_positions(data["bundles"])
            save_bundle_store(data)
            return updated_bundle

    return None


def reorder_model_bundles(bundle_ids: List[str]) -> List[Dict[str, Any]]:
    """Reorder bundles by the provided id list and resequence positions."""
    data = load_bundle_store()
    existing_bundles = data["bundles"]

    if len(bundle_ids) != len(existing_bundles):
        raise ValueError("Bundle reorder payload length mismatch")

    bundles_by_id = {bundle["id"]: bundle for bundle in existing_bundles}
    if set(bundle_ids) != set(bundles_by_id):
        raise ValueError("Bundle reorder payload does not match existing bundles")

    reordered_bundles = []
    for position, bundle_id in enumerate(bundle_ids, start=1):
        reordered_bundles.append({
            **bundles_by_id[bundle_id],
            "position": position,
            "updated_at": _timestamp_now(),
        })

    data["bundles"] = reordered_bundles
    save_bundle_store(data)
    return reordered_bundles


def delete_model_bundle(bundle_id: str) -> bool:
    """Delete a model bundle if more than one bundle remains."""
    data = load_bundle_store()
    bundles = data["bundles"]

    if len(bundles) <= 1:
        return False

    next_bundles = [bundle for bundle in bundles if bundle["id"] != bundle_id]
    if len(next_bundles) == len(bundles):
        return False

    data["bundles"] = next_bundles
    data["bundles"], _ = _normalize_bundle_positions(data["bundles"])
    save_bundle_store(data)
    return True


def set_default_model_bundle(bundle_id: str) -> Optional[List[Dict[str, Any]]]:
    """Mark one bundle as the default bundle."""
    data = load_bundle_store()
    bundles = data["bundles"]

    if not any(bundle["id"] == bundle_id for bundle in bundles):
        return None

    now = _timestamp_now()
    updated_bundles = []
    for bundle in bundles:
        updated_bundles.append({
            **bundle,
            "is_default": bundle["id"] == bundle_id,
            "updated_at": now if bundle["id"] == bundle_id or bundle.get("is_default") else bundle.get("updated_at", now),
        })

    data["bundles"], _ = _normalize_bundle_positions(updated_bundles)
    save_bundle_store(data)
    return data["bundles"]


def get_conversation_path(conversation_id: str) -> str:
    """Get the file path for a conversation."""
    return str(TRANSCRIPTS_DIR / f"{conversation_id}.json")


def create_conversation(
    conversation_id: str,
    owner_user_id: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Create a new conversation.

    Args:
        conversation_id: Unique identifier for the conversation

    Returns:
        New conversation dict
    """
    ensure_data_dir()

    conversation = {
        "id": conversation_id,
        "owner_user_id": owner_user_id,
        "created_at": _timestamp_now(),
        "title": "New Conversation",
        "archived": False,
        "archived_at": None,
        "messages": []
    }

    # Save to file
    path = get_conversation_path(conversation_id)
    with open(path, 'w') as f:
        json.dump(conversation, f, indent=2)

    return conversation


def get_conversation(conversation_id: str) -> Optional[Dict[str, Any]]:
    """
    Load a conversation from storage.

    Args:
        conversation_id: Unique identifier for the conversation

    Returns:
        Conversation dict or None if not found
    """
    path = get_conversation_path(conversation_id)

    if not os.path.exists(path):
        return None

    with open(path, 'r') as f:
        conversation = json.load(f)

    if _normalize_message_timestamps(conversation):
        save_conversation(conversation)

    return conversation


def save_conversation(conversation: Dict[str, Any]):
    """
    Save a conversation to storage.

    Args:
        conversation: Conversation dict to save
    """
    ensure_data_dir()

    path = get_conversation_path(conversation['id'])
    with open(path, 'w') as f:
        json.dump(conversation, f, indent=2)

    postgres_store.sync_conversation_metadata(conversation, path)


def list_conversations(
    archived: bool = False,
    owner_user_id: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """
    List all conversations (metadata only).

    Returns:
        List of conversation metadata dicts
    """
    ensure_data_dir()

    conversations = []
    for filename in os.listdir(TRANSCRIPTS_DIR):
        if filename.endswith('.json'):
            path = TRANSCRIPTS_DIR / filename
            with open(path, 'r') as f:
                data = json.load(f)
                is_archived = bool(data.get("archived", False))
                if is_archived != archived:
                    continue
                if owner_user_id and data.get("owner_user_id") != owner_user_id:
                    continue

                # Return metadata only
                conversations.append({
                    "id": data["id"],
                    "owner_user_id": data.get("owner_user_id"),
                    "created_at": data["created_at"],
                    "title": data.get("title", "New Conversation"),
                    "message_count": len(data["messages"]),
                    "archived": is_archived,
                    "archived_at": data.get("archived_at")
                })

    # Sort by creation time, newest first
    conversations.sort(key=lambda x: x["created_at"], reverse=True)

    return conversations


def list_all_conversation_ids() -> List[str]:
    """Return all conversation ids from transcript storage."""
    ensure_data_dir()

    conversation_ids = []
    for filename in os.listdir(TRANSCRIPTS_DIR):
        if filename.endswith(".json"):
            conversation_ids.append(filename.removesuffix(".json"))

    return sorted(conversation_ids)


def assign_unowned_conversations(owner_user_id: str) -> int:
    """Assign legacy transcript files without an owner to the given user."""
    assigned_count = 0
    for conversation_id in list_all_conversation_ids():
        conversation = get_conversation(conversation_id)
        if conversation is None or conversation.get("owner_user_id"):
            continue

        conversation["owner_user_id"] = owner_user_id
        save_conversation(conversation)
        assigned_count += 1

    return assigned_count


def set_conversation_archived(conversation_id: str, archived: bool) -> Optional[Dict[str, Any]]:
    """Archive or restore a conversation."""
    conversation = get_conversation(conversation_id)
    if conversation is None:
        return None

    conversation["archived"] = archived
    conversation["archived_at"] = _timestamp_now() if archived else None
    save_conversation(conversation)
    return conversation


def delete_conversation(conversation_id: str) -> bool:
    """Permanently delete a conversation file."""
    path = get_conversation_path(conversation_id)
    if not os.path.exists(path):
        return False

    os.remove(path)
    postgres_store.delete_conversation_metadata(conversation_id)
    return True


def add_user_message(
    conversation_id: str,
    content: str,
    bundle: Optional[Dict[str, Any]] = None
):
    """
    Add a user message to a conversation.

    Args:
        conversation_id: Conversation identifier
        content: User message content
    """
    conversation = get_conversation(conversation_id)
    if conversation is None:
        raise ValueError(f"Conversation {conversation_id} not found")

    message = {
        "role": "user",
        "content": content,
        "created_at": _timestamp_now(),
    }

    if bundle:
        message["bundle"] = {
            "id": bundle["id"],
            "name": bundle["name"],
        }

    conversation["messages"].append(message)

    save_conversation(conversation)


def add_assistant_message(
    conversation_id: str,
    stage1: List[Dict[str, Any]],
    stage2: List[Dict[str, Any]],
    stage3: Dict[str, Any],
    metadata: Optional[Dict[str, Any]] = None,
    bundle: Optional[Dict[str, Any]] = None
):
    """
    Add an assistant message with all 3 stages to a conversation.

    Args:
        conversation_id: Conversation identifier
        stage1: List of individual model responses
        stage2: List of model rankings
        stage3: Final synthesized response
    """
    conversation = get_conversation(conversation_id)
    if conversation is None:
        raise ValueError(f"Conversation {conversation_id} not found")

    message = {
        "role": "assistant",
        "stage1": stage1,
        "stage2": stage2,
        "stage3": stage3,
        "created_at": _timestamp_now(),
    }

    if metadata:
        message["metadata"] = metadata

    if bundle:
        message["bundle"] = {
            "id": bundle["id"],
            "name": bundle["name"],
            "chairman_model": bundle["chairman_model"],
            "council_models": bundle["council_models"],
        }

    conversation["messages"].append(message)

    save_conversation(conversation)


def add_assistant_error(
    conversation_id: str,
    error: Dict[str, Any],
    bundle: Optional[Dict[str, Any]] = None,
    metadata: Optional[Dict[str, Any]] = None,
):
    """Add an assistant error message to a conversation."""
    conversation = get_conversation(conversation_id)
    if conversation is None:
        raise ValueError(f"Conversation {conversation_id} not found")

    message = {
        "role": "assistant",
        "error": error,
        "created_at": _timestamp_now(),
    }

    if metadata:
        message["metadata"] = metadata

    if bundle:
        message["bundle"] = {
            "id": bundle["id"],
            "name": bundle["name"],
            "chairman_model": bundle["chairman_model"],
            "council_models": bundle["council_models"],
        }

    conversation["messages"].append(message)

    save_conversation(conversation)


def merge_latest_assistant_message_metadata(
    conversation_id: str,
    metadata_patch: Dict[str, Any],
) -> Optional[Dict[str, Any]]:
    """Shallow-merge metadata into the newest assistant message."""
    conversation = get_conversation(conversation_id)
    if conversation is None:
        raise ValueError(f"Conversation {conversation_id} not found")

    for message in reversed(conversation.get("messages", [])):
        if message.get("role") != "assistant":
            continue

        current_metadata = message.get("metadata") or {}
        message["metadata"] = {
            **current_metadata,
            **metadata_patch,
        }
        save_conversation(conversation)
        return message

    return None


def update_conversation_title(conversation_id: str, title: str):
    """
    Update the title of a conversation.

    Args:
        conversation_id: Conversation identifier
        title: New title for the conversation
    """
    conversation = get_conversation(conversation_id)
    if conversation is None:
        raise ValueError(f"Conversation {conversation_id} not found")

    conversation["title"] = title
    save_conversation(conversation)
