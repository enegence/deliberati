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
from .openrouter import query_model
from .usage import build_usage_request

TURN_SUMMARY_MAX_CHARS = 180
_TURN_TIMEOUT = 30.0


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
