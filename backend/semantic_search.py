"""Transcript-derived semantic chunking and search helpers."""

from __future__ import annotations

import math
from datetime import datetime, timezone
from typing import Any, Dict, List

from . import storage
from .search_utils import normalize_query, query_matches_text, rank_and_dedupe_results

DEFAULT_CHUNK_MAX_CHARS = 1200
DEFAULT_CHUNK_OVERLAP_CHARS = 180


def _parse_search_timestamp(value: str | None) -> datetime | None:
    """Parse an API timestamp filter."""
    if not value:
        return None

    candidate = value.strip()
    if not candidate:
        return None

    try:
        if len(candidate) == 10:
            return datetime.fromisoformat(f"{candidate}T00:00:00+00:00")
        parsed = datetime.fromisoformat(candidate.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            return parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)
    except ValueError:
        return None


def _message_matches_time_filters(
    message: Dict[str, Any],
    *,
    start_at: datetime | None,
    end_at: datetime | None,
) -> bool:
    """Return True when the message timestamp falls inside the requested range."""
    if start_at is None and end_at is None:
        return True

    message_created_at = _parse_search_timestamp(message.get("created_at"))
    if message_created_at is None:
        return False

    if start_at is not None and message_created_at < start_at:
        return False
    if end_at is not None and message_created_at > end_at:
        return False
    return True


def _approx_token_estimate(text: str) -> int:
    """Approximate token count cheaply for chunk metadata."""
    return max(1, math.ceil(len(text) / 4))


def _normalize_text(text: str) -> str:
    """Normalize chunk text while preserving useful paragraph structure."""
    if not text:
        return ""
    normalized = text.replace("\r\n", "\n").replace("\r", "\n").strip()
    lines = [line.rstrip() for line in normalized.split("\n")]
    cleaned_lines = []
    previous_blank = False
    for line in lines:
        is_blank = not line.strip()
        if is_blank:
            if not previous_blank:
                cleaned_lines.append("")
            previous_blank = True
            continue
        cleaned_lines.append(line.strip())
        previous_blank = False
    return "\n".join(cleaned_lines).strip()


def _split_long_text(
    text: str,
    max_chars: int = DEFAULT_CHUNK_MAX_CHARS,
    overlap_chars: int = DEFAULT_CHUNK_OVERLAP_CHARS,
) -> List[str]:
    """Split text into bounded overlapping chunks."""
    normalized = _normalize_text(text)
    if not normalized:
        return []
    if len(normalized) <= max_chars:
        return [normalized]

    chunks: List[str] = []
    start = 0
    while start < len(normalized):
        end = min(len(normalized), start + max_chars)
        if end < len(normalized):
            split_at = normalized.rfind("\n\n", start, end)
            if split_at <= start + (max_chars // 2):
                split_at = normalized.rfind(" ", start, end)
            if split_at > start + (max_chars // 2):
                end = split_at

        chunk = normalized[start:end].strip()
        if chunk:
            chunks.append(chunk)

        if end >= len(normalized):
            break

        next_start = max(end - overlap_chars, start + 1)
        while next_start < len(normalized) and normalized[next_start].isspace():
            next_start += 1
        start = next_start

    return chunks


def build_semantic_chunks(
    conversation: Dict[str, Any],
    max_chars: int = DEFAULT_CHUNK_MAX_CHARS,
) -> List[Dict[str, Any]]:
    """Build transcript-derived searchable chunks for one conversation."""
    conversation_id = conversation["id"]
    conversation_title = conversation.get("title", "New Conversation")
    chunks: List[Dict[str, Any]] = []

    for message_index, message in enumerate(conversation.get("messages", []), start=1):
        role = message.get("role", "unknown")
        bundle_name = (message.get("bundle") or {}).get("name")
        message_created_at = message.get("created_at") or conversation.get("created_at")

        text_variants: List[tuple[str, str]] = []
        if role == "user" and message.get("content"):
            text_variants.append(("user_message", message["content"]))

        if role == "assistant":
            final_response = message.get("stage3", {}).get("response")
            if final_response:
                text_variants.append(("assistant_final", final_response))
            error_message = (message.get("error") or {}).get("message")
            if error_message:
                text_variants.append(("assistant_error", error_message))

        for source_type, raw_text in text_variants:
            for chunk_index, chunk_text in enumerate(_split_long_text(raw_text, max_chars=max_chars)):
                chunks.append(
                    {
                        "conversation_id": conversation_id,
                        "source_type": source_type,
                        "source_ref": f"message:{message_index}",
                        "chunk_index": chunk_index,
                        "chunk_text": chunk_text,
                        "token_estimate": _approx_token_estimate(chunk_text),
                        "metadata": {
                            "conversation_title": conversation_title,
                            "role": role,
                            "message_index": message_index,
                            "bundle_name": bundle_name,
                            "message_created_at": message_created_at,
                        },
                    }
                )

    return chunks


def search_transcripts(
    query: str,
    limit: int = 20,
    *,
    start_at: str | None = None,
    end_at: str | None = None,
    owner_user_id: str | None = None,
) -> List[Dict[str, Any]]:
    """Fallback search by deriving chunks directly from transcript files."""
    normalized_query = normalize_query(query).lower()
    if not normalized_query:
        return []

    parsed_start_at = _parse_search_timestamp(start_at)
    parsed_end_at = _parse_search_timestamp(end_at)

    candidates: List[Dict[str, Any]] = []
    for conversation_id in storage.list_all_conversation_ids():
        conversation = storage.get_conversation(conversation_id)
        if conversation is None:
            continue
        if owner_user_id and conversation.get("owner_user_id") != owner_user_id:
            continue

        title = conversation.get("title", "New Conversation")
        for chunk in build_semantic_chunks(conversation):
            message_index = (chunk.get("metadata") or {}).get("message_index")
            if (
                isinstance(message_index, int)
                and 1 <= message_index <= len(conversation.get("messages", []))
                and not _message_matches_time_filters(
                    conversation["messages"][message_index - 1],
                    start_at=parsed_start_at,
                    end_at=parsed_end_at,
                )
            ):
                continue

            chunk_text = chunk["chunk_text"]
            if not query_matches_text(normalized_query, title, chunk_text):
                continue

            candidates.append(
                {
                    "conversation_id": conversation_id,
                    "title": title,
                    "archived": bool(conversation.get("archived", False)),
                    "source_type": chunk["source_type"],
                    "source_ref": chunk["source_ref"],
                    "chunk_index": chunk["chunk_index"],
                    "chunk_text": chunk_text,
                    "metadata": chunk.get("metadata") or {},
                }
            )

    return rank_and_dedupe_results(candidates, normalized_query, limit)
