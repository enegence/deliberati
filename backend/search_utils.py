"""Shared search ranking and excerpt helpers."""

from __future__ import annotations

import re
from typing import Any, Dict, List, Sequence

SNIPPET_RADIUS = 160
SEARCH_STOPWORDS = {
    "a", "an", "and", "are", "as", "at", "be", "but", "by", "for", "from",
    "has", "have", "how", "i", "in", "is", "it", "of", "on", "or", "our",
    "that", "the", "their", "this", "to", "was", "were", "what", "when",
    "where", "which", "who", "why", "with", "you", "your",
}


def normalize_query(query: str) -> str:
    """Normalize a search query for scoring and matching."""
    return " ".join((query or "").strip().split())


def query_terms(query: str) -> list[str]:
    """Split a normalized query into distinct lowercase terms."""
    normalized = normalize_query(query).lower()
    terms: list[str] = []
    seen = set()
    for term in re.findall(r"[a-z0-9_/-]+", normalized):
        if term in seen:
            continue
        seen.add(term)
        terms.append(term)
    return terms


def significant_query_terms(query: str) -> list[str]:
    """Return query terms useful for lexical retrieval."""
    terms = [
        term
        for term in query_terms(query)
        if len(term) > 1 and term not in SEARCH_STOPWORDS
    ]
    return terms or query_terms(query)


def query_matches_text(query: str, *texts: str) -> bool:
    """Return True when texts contain the phrase or every significant term."""
    normalized_query = normalize_query(query).lower()
    if not normalized_query:
        return False

    lowered_texts = [(text or "").lower() for text in texts]
    combined_text = " ".join(lowered_texts)
    if normalized_query in combined_text:
        return True

    terms = significant_query_terms(normalized_query)
    if not terms:
        return False
    return all(term in combined_text for term in terms)


def build_match_snippet(text: str, query: str, radius: int = SNIPPET_RADIUS) -> str:
    """Build a compact excerpt around the first query hit."""
    compact = " ".join((text or "").split())
    if not compact:
        return ""

    normalized_query = normalize_query(query)
    lowered_text = compact.lower()
    lowered_query = normalized_query.lower()

    match_index = lowered_text.find(lowered_query) if lowered_query else -1
    if match_index < 0:
        for term in significant_query_terms(normalized_query):
            match_index = lowered_text.find(term)
            if match_index >= 0:
                break

    if match_index < 0:
        if len(compact) <= radius * 2:
            return compact
        return compact[: radius * 2].rstrip() + "..."

    start = max(0, match_index - radius)
    end = min(len(compact), match_index + max(len(lowered_query), 20) + radius)

    if start > 0:
        split_at = compact.find(" ", start)
        if split_at > 0 and split_at < end:
            start = split_at + 1
    if end < len(compact):
        split_at = compact.rfind(" ", start, end)
        if split_at > start:
            end = split_at

    snippet = compact[start:end].strip()
    if start > 0:
        snippet = "..." + snippet
    if end < len(compact):
        snippet = snippet + "..."
    return snippet


def compute_match_score(
    *,
    query: str,
    title: str,
    chunk_text: str,
    source_type: str,
) -> float:
    """Compute a simple lexical relevance score without embeddings."""
    normalized_query = normalize_query(query).lower()
    if not normalized_query:
        return 0.0

    lowered_title = (title or "").lower()
    lowered_chunk = (chunk_text or "").lower()
    combined_text = f"{lowered_title} {lowered_chunk}"
    terms = significant_query_terms(normalized_query)

    score = 0.0

    if normalized_query in lowered_title:
        score += 10.0
    if normalized_query in lowered_chunk:
        score += 7.0

    matched_terms = [term for term in terms if term in combined_text]
    if terms and len(matched_terms) < len(terms) and normalized_query not in combined_text:
        return 0.0

    if terms:
        score += (len(matched_terms) / len(terms)) * 4.0

    for term in terms:
        title_count = lowered_title.count(term)
        chunk_count = lowered_chunk.count(term)
        if title_count:
            score += 3.0 + min(title_count, 4) * 0.6
        if chunk_count:
            score += min(chunk_count, 8) * 0.7

    source_bonus = {
        "assistant_final": 1.4,
        "user_message": 1.0,
        "assistant_error": 0.3,
    }
    score += source_bonus.get(source_type, 0.5)

    return score


def rank_and_dedupe_results(
    candidates: Sequence[Dict[str, Any]],
    query: str,
    limit: int,
) -> list[Dict[str, Any]]:
    """Rank results and keep only the best hit per message-level source."""
    normalized_query = normalize_query(query)
    scored: list[Dict[str, Any]] = []

    for candidate in candidates:
        title = candidate.get("title", "")
        chunk_text = candidate.get("chunk_text", "")
        source_type = candidate.get("source_type", "")
        score = compute_match_score(
            query=normalized_query,
            title=title,
            chunk_text=chunk_text,
            source_type=source_type,
        )
        if score <= 0:
            continue

        ranked = dict(candidate)
        ranked["score"] = score
        ranked["snippet"] = build_match_snippet(chunk_text, normalized_query)
        scored.append(ranked)

    scored.sort(
        key=lambda entry: (
            -entry["score"],
            entry.get("archived", False),
            entry.get("title", "").lower(),
            entry.get("source_ref", ""),
            entry.get("chunk_index", 0),
        )
    )

    deduped: list[Dict[str, Any]] = []
    seen = set()
    for entry in scored:
        dedupe_key = (
            entry.get("conversation_id"),
            entry.get("source_type"),
            entry.get("source_ref"),
        )
        if dedupe_key in seen:
            continue
        seen.add(dedupe_key)
        deduped.append(entry)
        if len(deduped) >= limit:
            break

    return deduped
