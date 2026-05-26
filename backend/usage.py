"""Usage normalization and aggregation helpers."""

from __future__ import annotations

from typing import Any, Dict, Iterable, List, Optional


def _as_int(value: Any) -> Optional[int]:
    if value is None:
        return None

    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _as_float(value: Any) -> Optional[float]:
    if value is None:
        return None

    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def normalize_openrouter_usage(
    model: str,
    response_data: Dict[str, Any],
    response_headers: Optional[Dict[str, str]] = None,
) -> Optional[Dict[str, Any]]:
    """Normalize OpenRouter usage details into a provider-agnostic record."""
    usage = response_data.get("usage")
    if not isinstance(usage, dict):
        return None

    prompt_details = usage.get("prompt_tokens_details") or {}
    completion_details = usage.get("completion_tokens_details") or {}
    cost_details = usage.get("cost_details") or {}
    response_headers = {
        str(key).lower(): value
        for key, value in (response_headers or {}).items()
    }

    return {
        "provider": "openrouter",
        "model": response_data.get("model") or model,
        "provider_response_id": response_data.get("id"),
        "provider_request_id": response_headers.get("x-request-id"),
        "prompt_tokens": _as_int(usage.get("prompt_tokens")),
        "completion_tokens": _as_int(usage.get("completion_tokens")),
        "total_tokens": _as_int(usage.get("total_tokens")),
        "reasoning_tokens": _as_int(completion_details.get("reasoning_tokens")),
        "cached_tokens": _as_int(prompt_details.get("cached_tokens")),
        "cache_write_tokens": _as_int(prompt_details.get("cache_write_tokens")),
        "audio_tokens": _as_int(prompt_details.get("audio_tokens")),
        "cost": _as_float(usage.get("cost")),
        "upstream_inference_cost": _as_float(cost_details.get("upstream_inference_cost")),
        "currency": "usd",
    }


def build_usage_request(
    *,
    kind: str,
    usage: Optional[Dict[str, Any]],
    model: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    """Annotate a normalized provider usage record with request kind."""
    if not usage:
        return None

    return {
        **usage,
        "kind": kind,
        "model": model or usage.get("model"),
    }


def summarize_usage_requests(requests: Iterable[Optional[Dict[str, Any]]]) -> Dict[str, Any]:
    """Aggregate request-level usage into one summary payload."""
    normalized_requests: List[Dict[str, Any]] = [
        request for request in requests
        if isinstance(request, dict)
    ]

    totals = {
        "request_count": len(normalized_requests),
        "prompt_tokens": 0,
        "completion_tokens": 0,
        "total_tokens": 0,
        "reasoning_tokens": 0,
        "cached_tokens": 0,
        "cache_write_tokens": 0,
        "audio_tokens": 0,
        "cost": 0.0,
        "upstream_inference_cost": 0.0,
        "cost_request_count": 0,
        "cost_missing_request_count": 0,
        "currency": "usd",
        "providers": [],
    }

    providers = set()

    for request in normalized_requests:
        provider = request.get("provider")
        if provider:
            providers.add(provider)

        for field in (
            "prompt_tokens",
            "completion_tokens",
            "total_tokens",
            "reasoning_tokens",
            "cached_tokens",
            "cache_write_tokens",
            "audio_tokens",
        ):
            value = _as_int(request.get(field))
            if value is not None:
                totals[field] += value

        cost = _as_float(request.get("cost"))
        if cost is not None:
            totals["cost"] += cost
            totals["cost_request_count"] += 1
        else:
            totals["cost_missing_request_count"] += 1

        upstream_cost = _as_float(request.get("upstream_inference_cost"))
        if upstream_cost is not None:
            totals["upstream_inference_cost"] += upstream_cost

    totals["providers"] = sorted(providers)
    totals["has_cost"] = totals["cost_request_count"] > 0

    if totals["cost_request_count"] == 0:
        totals["cost"] = None
    else:
        totals["cost"] = round(totals["cost"], 8)

    if totals["upstream_inference_cost"] == 0.0:
        totals["upstream_inference_cost"] = None
    else:
        totals["upstream_inference_cost"] = round(totals["upstream_inference_cost"], 8)

    return totals


def summarize_conversation_usage(conversation: Dict[str, Any]) -> Dict[str, Any]:
    """Aggregate persisted per-message usage summaries for a conversation."""
    totals = {
        "request_count": 0,
        "prompt_tokens": 0,
        "completion_tokens": 0,
        "total_tokens": 0,
        "reasoning_tokens": 0,
        "cached_tokens": 0,
        "cache_write_tokens": 0,
        "audio_tokens": 0,
        "cost": 0.0,
        "upstream_inference_cost": 0.0,
        "cost_request_count": 0,
        "cost_missing_request_count": 0,
        "currency": "usd",
        "providers": set(),
    }

    message_count = 0
    assistant_turns_with_usage = 0

    for message in conversation.get("messages", []):
        message_count += 1
        usage_summary = ((message.get("metadata") or {}).get("usage") or {}).get("summary")
        if not isinstance(usage_summary, dict):
            continue

        assistant_turns_with_usage += 1
        totals["request_count"] += _as_int(usage_summary.get("request_count")) or 0
        for field in (
            "prompt_tokens",
            "completion_tokens",
            "total_tokens",
            "reasoning_tokens",
            "cached_tokens",
            "cache_write_tokens",
            "audio_tokens",
            "cost_request_count",
            "cost_missing_request_count",
        ):
            totals[field] += _as_int(usage_summary.get(field)) or 0

        cost = _as_float(usage_summary.get("cost"))
        if cost is not None:
            totals["cost"] += cost

        upstream_cost = _as_float(usage_summary.get("upstream_inference_cost"))
        if upstream_cost is not None:
            totals["upstream_inference_cost"] += upstream_cost

        for provider in usage_summary.get("providers") or []:
            if provider:
                totals["providers"].add(provider)

    totals["providers"] = sorted(totals["providers"])
    totals["assistant_turns_with_usage"] = assistant_turns_with_usage
    totals["message_count"] = message_count
    totals["has_cost"] = totals["cost_request_count"] > 0

    if totals["cost_request_count"] == 0:
        totals["cost"] = None
    else:
        totals["cost"] = round(totals["cost"], 8)

    if totals["upstream_inference_cost"] == 0.0:
        totals["upstream_inference_cost"] = None
    else:
        totals["upstream_inference_cost"] = round(totals["upstream_inference_cost"], 8)

    return totals
