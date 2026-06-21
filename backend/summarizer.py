"""Cheap-LLM summarization and tagging for post-processing passes.

Each builder returns the same schema as its deterministic twin and never
raises; on any failure it returns None so callers fall back to deterministic.
"""

from __future__ import annotations

import hashlib
import json
import re
from typing import Any, Dict, List, Optional

from . import config
from .entity_extraction import build_exact_entities, build_inferred_entities
from .openrouter import query_model
from .postprocess import build_memory_record, render_memory_text, build_turn_index_entries, _is_probably_pasted_source
from .usage import build_usage_request

TURN_SUMMARY_MAX_CHARS = 180
_TURN_TIMEOUT = 30.0
_TAG_TIMEOUT = 30.0

MEMORY_REQUIRED_KEYS = (
    "current_goal", "user_objective", "stable_constraints",
    "recent_decisions", "open_threads", "background_context_notes",
)


def content_hash(text: str) -> str:
    """Stable short hash of turn content for cache invalidation."""
    return hashlib.sha256((text or "").encode("utf-8")).hexdigest()[:16]


def parse_json_block(text: str) -> Optional[Any]:
    """Best-effort parse of a JSON object/array from a model content string."""
    if not text:
        return None
    candidate = text.strip()
    fence = re.search(r"```(?:json)?\s*(.+?)```", candidate, re.DOTALL)
    if fence:
        candidate = fence.group(1).strip()
    try:
        return json.loads(candidate)
    except (ValueError, TypeError):
        pass
    match = re.search(r"(\{.*\}|\[.*\])", candidate, re.DOTALL)
    if not match:
        return None
    try:
        return json.loads(match.group(1))
    except (ValueError, TypeError):
        return None


def _model() -> str:
    return config.SUMMARIZER_MODEL


def _enabled() -> bool:
    return bool(config.SUMMARIZER_ENABLED)


def _turn_prompt(role: str, content: str, stage3_response: str) -> str:
    if role == "assistant":
        body = stage3_response or content
        instruction = (
            "Summarize the council's answer below in one sentence (max 25 words). "
            "Capture the core conclusion, not the preamble."
        )
    else:
        body = content
        instruction = (
            "Summarize this user message in one sentence (max 25 words). "
            "Capture what they are actually asking for."
        )
    return f"{instruction}\n\nText:\n{body}\n\nSummary:"


async def summarize_turn(
    role: str, content: str, stage3_response: str
) -> Optional[Dict[str, Any]]:
    """One-line essence for a single turn, or None to fall back."""
    if not _enabled():
        return None
    model = _model()
    messages = [{"role": "user", "content": _turn_prompt(role, content, stage3_response)}]
    response = await query_model(model, messages, timeout=_TURN_TIMEOUT)
    if not response:
        return None
    summary = (response.get("content") or "").strip().strip('"\'')
    if not summary:
        return None
    if len(summary) > TURN_SUMMARY_MAX_CHARS:
        summary = summary[: TURN_SUMMARY_MAX_CHARS - 1].rstrip() + "…"
    return {
        "summary": summary,
        "usage": build_usage_request(
            kind="turn_summary", usage=response.get("usage"), model=model
        ),
    }


def _message_source_text(message: Dict[str, Any]) -> str:
    """The text whose change should invalidate a cached turn summary."""
    if message.get("role") == "user":
        return message.get("content", "") or ""
    if message.get("error"):
        return f"error:{message.get('error', {}).get('message', '')}"
    return message.get("stage3", {}).get("response", "") or ""


def _should_use_llm_for_turn(message: Dict[str, Any]) -> bool:
    """Assistant/error turns and long/structured user turns use the LLM."""
    role = message.get("role")
    if role != "user":
        return bool(_message_source_text(message))
    content = message.get("content", "") or ""
    if _is_probably_pasted_source(content):
        return True
    return len(content.strip()) > config.SUMMARIZER_MIN_CHARS


def _existing_by_turn(existing_rows: List[Dict[str, Any]]) -> Dict[int, Dict[str, Any]]:
    return {row.get("turn_number"): row for row in existing_rows or []}


async def build_llm_turn_index_entries(
    conversation: Dict[str, Any],
    existing_rows: List[Dict[str, Any]],
    summarize_fn=None,
) -> List[Dict[str, Any]]:
    """Deterministic floor overlaid with cached/fresh LLM turn summaries."""
    # Resolve at call time so monkeypatching summarizer.summarize_turn works.
    summarize_fn = summarize_fn or summarize_turn
    entries = build_turn_index_entries(conversation)
    messages = conversation.get("messages", [])
    cache = _existing_by_turn(existing_rows)
    version = config.SUMMARIZER_VERSION

    for entry, message in zip(entries, messages):
        source_hash = content_hash(_message_source_text(message))
        entry["transcript_offset"] = {
            **entry.get("transcript_offset", {}),
            "summarizer_version": version,
            "source_hash": source_hash,
        }

        cached = cache.get(entry["turn_number"])
        if cached:
            cached_offset = cached.get("transcript_offset") or {}
            if (
                cached_offset.get("summarizer_version") == version
                and cached_offset.get("source_hash") == source_hash
                and cached.get("short_highlight")
            ):
                entry["short_highlight"] = cached["short_highlight"]
                continue

        if not _enabled() or not _should_use_llm_for_turn(message):
            continue  # keep deterministic floor

        result = await summarize_fn(
            message.get("role", "assistant"),
            message.get("content", "") or "",
            message.get("stage3", {}).get("response", "") or "",
        )
        if result and result.get("summary"):
            entry["short_highlight"] = result["summary"]

    return entries


_MEMORY_TIMEOUT = 30.0


def _memory_prompt(turn_summaries: List[str]) -> str:
    joined = "\n".join(f"- {line}" for line in turn_summaries if line)
    keys = ", ".join(MEMORY_REQUIRED_KEYS)
    return (
        "You maintain rolling memory for a multi-turn AI council conversation. "
        "From the ordered turn summaries below, output a JSON object with EXACTLY "
        f"these keys: {keys}. "
        "current_goal and user_objective are strings; the rest are arrays of short "
        "strings. Use [] for empty arrays and \"\" for empty strings. "
        "Output only the JSON.\n\nTurn summaries:\n"
        f"{joined}\n\nJSON:"
    )


async def summarize_memory(
    summary_json_seed: Dict[str, Any], turn_summaries: List[str]
) -> Optional[Dict[str, Any]]:
    """Return validated memory fields from the LLM, or None to fall back."""
    if not _enabled():
        return None
    model = _model()
    messages = [{"role": "user", "content": _memory_prompt(turn_summaries)}]
    response = await query_model(model, messages, timeout=_MEMORY_TIMEOUT)
    if not response:
        return None
    parsed = parse_json_block(response.get("content") or "")
    if not isinstance(parsed, dict):
        return None
    if not all(key in parsed for key in MEMORY_REQUIRED_KEYS):
        return None
    return parsed


async def build_llm_memory_record(
    conversation: Dict[str, Any],
    turn_summaries: List[str],
    max_tokens: int,
) -> Dict[str, Any]:
    """Deterministic memory record with LLM-filled fields when available."""
    record = build_memory_record(conversation, max_tokens=max_tokens)
    if not _enabled():
        return record

    fields = await summarize_memory(record["summary_json"], turn_summaries)
    if not fields:
        return record

    summary_json = {**record["summary_json"], **fields}
    latest_stage3 = next(
        (
            m.get("stage3", {}).get("response", "")
            for m in reversed(conversation.get("messages", []))
            if m.get("role") == "assistant" and m.get("stage3", {}).get("response")
        ),
        "",
    )
    summary_text, token_estimate = render_memory_text(summary_json, latest_stage3, max_tokens)
    summary_json["token_estimate"] = token_estimate
    return {
        "summary_text": summary_text,
        "summary_json": summary_json,
        "token_estimate": token_estimate,
        "source_turn_count": record["source_turn_count"],
    }


_VALID_TAG_TYPES = {"entity", "theme"}
_VALID_TAG_KEYS = {"entity_type", "canonical_name", "link_type"}


def _tags_prompt(turn_summaries: List[str], memory_text: str) -> str:
    joined = "\n".join(f"- {line}" for line in turn_summaries if line)
    return (
        "Extract the salient named entities and recurring themes from this "
        "conversation. Return a JSON array of objects, each with keys "
        '"entity_type" ("entity" for proper nouns/projects/products, "theme" for '
        'topic keywords), "canonical_name", and "link_type" ("mentioned" for '
        'entities, "theme" for themes). Max 12 items. Output only the JSON array.'
        f"\n\nMemory:\n{memory_text}\n\nTurn summaries:\n{joined}\n\nJSON:"
    )


def _coerce_tag(item: Any) -> Optional[Dict[str, Any]]:
    if not isinstance(item, dict):
        return None
    if not _VALID_TAG_KEYS.issubset(item.keys()):
        return None
    entity_type = item["entity_type"]
    name = (item.get("canonical_name") or "").strip()
    if entity_type not in _VALID_TAG_TYPES or not name:
        return None
    link_type = item["link_type"] if item["link_type"] in {"mentioned", "theme"} else (
        "mentioned" if entity_type == "entity" else "theme"
    )
    return {
        "entity_type": entity_type,
        "canonical_name": name,
        "link_type": link_type,
        "metadata": {"source": "llm"},
    }


async def extract_tags(
    turn_summaries: List[str], memory_text: str
) -> Optional[List[Dict[str, Any]]]:
    """LLM entity/theme tags, or None to fall back to deterministic."""
    if not _enabled():
        return None
    model = _model()
    messages = [{"role": "user", "content": _tags_prompt(turn_summaries, memory_text)}]
    response = await query_model(model, messages, timeout=_TAG_TIMEOUT)
    if not response:
        return None
    parsed = parse_json_block(response.get("content") or "")
    if not isinstance(parsed, list):
        return None
    tags = [coerced for coerced in (_coerce_tag(item) for item in parsed) if coerced]
    return tags or None


async def build_llm_conversation_entities(
    conversation: Dict[str, Any],
    turn_summaries: List[str],
    memory_text: str,
) -> List[Dict[str, Any]]:
    """Exact bundle/model links plus LLM (or deterministic) entity/theme tags."""
    entities, add_entity = _entity_collector()
    for entity in build_exact_entities(conversation):
        add_entity(entity)

    inferred = await extract_tags(turn_summaries, memory_text)
    if inferred is None:
        inferred = build_inferred_entities(conversation)

    for entity in inferred:
        add_entity(entity)
    return entities


def _entity_collector():
    seen = set()
    entities: List[Dict[str, Any]] = []

    def add_entity(entity: Dict[str, Any]):
        name = (entity.get("canonical_name") or "").strip()
        if not name:
            return
        key = (entity["entity_type"], name.lower(), entity["link_type"])
        if key in seen:
            return
        seen.add(key)
        entities.append(entity)

    return entities, add_entity
