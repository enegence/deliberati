"""Deterministic entity and theme extraction helpers."""

from __future__ import annotations

import re
from collections import Counter
from typing import Any, Dict, Iterable, List

from .postprocess import build_memory_record

COMMON_STOPWORDS = {
    "about", "after", "again", "also", "among", "an", "and", "any", "are", "because",
    "been", "being", "between", "both", "but", "can", "could", "did", "does", "doing",
    "each", "even", "for", "from", "get", "had", "has", "have", "here", "into", "its",
    "just", "like", "many", "more", "most", "much", "need", "not", "now", "only", "other",
    "our", "out", "over", "same", "should", "some", "such", "than", "that", "the", "their",
    "them", "then", "there", "these", "they", "this", "those", "through", "under", "very",
    "want", "what", "when", "where", "which", "while", "with", "would", "your",
}

IGNORED_THEME_TERMS = {
    "assistant", "bundle", "bundles", "chairman", "conversation", "conversations", "council",
    "current", "decision", "decisions", "final", "goal", "goals", "immediate", "index",
    "memory", "message", "messages", "objective", "objectives", "open", "overview", "pasted",
    "peer", "prompt", "prompts", "rank", "rankings", "recent", "response", "responses",
    "rolling", "stable", "stage", "stages", "summary", "synthesis", "thread", "threads",
    "next", "step", "strong", "meaningful", "suggest", "yeah",
}

IGNORED_CAPITALIZED_TERMS = {
    "The", "This", "That", "There", "These", "Those", "And", "But", "For", "With",
    "You", "Your", "What", "When", "Where", "Which", "Why", "How", "Council",
    "Stage", "Message", "Conversation", "Pasted", "Summary", "Immediate", "Key",
    "Chairman", "Synthesis", "Current", "Original", "Background", "Recent", "Open",
    "Stable", "Final",
}


def _clean_text(text: str) -> str:
    """Normalize whitespace for extraction."""
    return " ".join((text or "").split())


def _iter_message_bundles(conversation: Dict[str, Any]) -> Iterable[str]:
    """Yield referenced bundle names from messages."""
    for message in conversation.get("messages", []):
        bundle = message.get("bundle") or message.get("metadata", {}).get("bundle") or {}
        bundle_name = bundle.get("name")
        if bundle_name:
            yield bundle_name.strip()


def _iter_model_ids(conversation: Dict[str, Any]) -> Iterable[str]:
    """Yield referenced model ids from bundle metadata and ranking metadata."""
    for message in conversation.get("messages", []):
        bundle = message.get("bundle") or message.get("metadata", {}).get("bundle") or {}
        chairman_model = bundle.get("chairman_model")
        if chairman_model:
            yield chairman_model.strip()
        for model_id in bundle.get("council_models") or []:
            if model_id:
                yield str(model_id).strip()

        label_to_model = (message.get("metadata") or {}).get("label_to_model") or {}
        for model_id in label_to_model.values():
            if model_id:
                yield str(model_id).strip()


def _summary_text_sources(conversation: Dict[str, Any]) -> List[str]:
    """Collect compact summary-oriented text sources for heuristic extraction."""
    memory = build_memory_record(conversation)
    summary_json = memory.get("summary_json") or {}
    texts = [
        conversation.get("title", ""),
        summary_json.get("current_goal", ""),
        summary_json.get("user_objective", ""),
        memory.get("summary_text", ""),
    ]
    texts.extend(summary_json.get("background_context_notes") or [])
    texts.extend(summary_json.get("recent_decisions") or [])
    texts.extend(summary_json.get("open_threads") or [])
    return [_clean_text(text) for text in texts if _clean_text(text)]


def _extract_capitalized_entities(
    title: str,
    texts: List[str],
    limit: int = 8,
) -> List[tuple[str, Dict[str, Any]]]:
    """Extract project-like capitalized terms such as LiveMUD or CarbonSKU."""
    counts: Counter[str] = Counter()
    title_terms = set(re.findall(r"\b[A-Z][A-Za-z0-9_-]{2,}\b", title or ""))
    for text in texts:
        for match in re.findall(r"\b[A-Z][A-Za-z0-9_-]{2,}\b", text):
            if match in IGNORED_CAPITALIZED_TERMS:
                continue
            is_title_term = match in title_terms
            has_internal_signal = (
                any(character.isdigit() for character in match)
                or "-" in match
                or "_" in match
                or sum(1 for character in match if character.isupper()) >= 2
            )
            if not is_title_term and not has_internal_signal:
                continue
            counts[match] += 1

    return [
        (
            name,
            {
                "count": count,
                "source": "summary_capitalized_terms",
            },
        )
        for name, count in counts.most_common(limit)
    ]


def _extract_theme_terms(texts: List[str], limit: int = 8) -> List[tuple[str, Dict[str, Any]]]:
    """Extract stable lower-case theme keywords from summary-oriented text."""
    counts: Counter[str] = Counter()
    for text in texts:
        for token in re.findall(r"\b[a-z][a-z0-9_-]{3,}\b", text.lower()):
            if token in COMMON_STOPWORDS or token in IGNORED_THEME_TERMS:
                continue
            counts[token] += 1

    return [
        (
            token,
            {
                "count": count,
                "source": "summary_keywords",
            },
        )
        for token, count in counts.most_common(limit)
    ]


def _new_collector():
    seen = set()
    entities: List[Dict[str, Any]] = []

    def add_entity(entity_type: str, canonical_name: str, link_type: str, metadata: Dict[str, Any]):
        normalized_name = canonical_name.strip()
        if not normalized_name:
            return
        key = (entity_type, normalized_name.lower(), link_type)
        if key in seen:
            return
        seen.add(key)
        entities.append(
            {
                "entity_type": entity_type,
                "canonical_name": normalized_name,
                "link_type": link_type,
                "metadata": metadata,
            }
        )

    return entities, add_entity


def build_exact_entities(conversation: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Bundle and model links derived from exact message metadata."""
    entities, add_entity = _new_collector()
    for bundle_name in sorted(set(_iter_message_bundles(conversation))):
        add_entity("bundle", bundle_name, "uses_bundle", {"source": "message_bundle"})
    for model_id in sorted(set(_iter_model_ids(conversation))):
        add_entity("model", model_id, "mentions_model", {"source": "message_metadata"})
    return entities


def build_inferred_entities(conversation: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Capitalized entities and theme keywords from summary text (deterministic)."""
    entities, add_entity = _new_collector()
    summary_texts = _summary_text_sources(conversation)
    for name, metadata in _extract_capitalized_entities(conversation.get("title", ""), summary_texts):
        add_entity("entity", name, "mentioned", metadata)
    for theme, metadata in _extract_theme_terms(summary_texts):
        add_entity("theme", theme, "theme", metadata)
    return entities


def build_conversation_entities(conversation: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Deterministic entity/theme links for one conversation (exact + inferred)."""
    entities, add_entity = _new_collector()
    for entity in build_exact_entities(conversation) + build_inferred_entities(conversation):
        add_entity(entity["entity_type"], entity["canonical_name"], entity["link_type"], entity["metadata"])
    return entities
