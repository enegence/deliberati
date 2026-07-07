"""Post-processing helpers for rolling memory and transcript indexing."""

from __future__ import annotations

import math
import re
from datetime import datetime, timezone
from typing import Any, Dict, List


DEFAULT_MEMORY_MAX_TOKENS = 900
DEFAULT_MEMORY_MAX_CHARS = 3200
PASTED_SOURCE_SUMMARY_MAX_CHARS = 240
MEMORY_FORMAT_VERSION = 2
DOCUMENT_BLOCK_START_RE = re.compile(
    r"\n\s*\n(?=(?:PRD\s*#?\d+|#{1,6}\s+|Product:|Working category:|Status:|Date:|Phase\s+[A-Z]:|V\d+:|##\s+|\d+\.\s+[A-Z]))",
    re.IGNORECASE,
)


def _clean_whitespace(text: str) -> str:
    """Normalize whitespace into a single readable line."""
    return " ".join((text or "").split())


def _strip_markdown_artifacts(text: str) -> str:
    """Remove obvious markdown scaffolding for memory/index extraction."""
    if not text:
        return ""

    normalized = text.replace("\r\n", "\n").replace("\r", "\n")
    normalized = re.sub(r"```[\s\S]*?```", " ", normalized)
    normalized = re.sub(r"!\[([^\]]*)\]\([^)]+\)", r"\1", normalized)
    normalized = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", normalized)

    cleaned_lines = []
    for line in normalized.split("\n"):
        line = line.strip()
        if not line:
            continue
        if re.fullmatch(r"[-=]{3,}", line):
            continue

        line = re.sub(r"^#{1,6}\s+", "", line)
        line = re.sub(r"^>\s+", "", line)
        line = re.sub(r"^[-*+]\s+", "", line)
        line = re.sub(r"^\d+(?:\.\d+){0,4}[.):-]?\s+", "", line)
        line = re.sub(r"[`*_~]+", "", line)
        line = line.strip()

        if line:
            cleaned_lines.append(line)

    return _clean_whitespace(" ".join(cleaned_lines))


def _clip_text(text: str, max_chars: int) -> str:
    """Clip text to a maximum character count without exploding whitespace."""
    normalized = _clean_whitespace(text)
    if len(normalized) <= max_chars:
        return normalized

    clipped = normalized[:max_chars].rsplit(" ", 1)[0].rstrip(" ,;:")
    return f"{clipped}..."


def _prepare_snippet(text: str, max_chars: int) -> str:
    """Strip noisy formatting and clip the result."""
    return _clip_text(_strip_markdown_artifacts(text), max_chars)


def _split_pasted_preface_and_body(text: str) -> tuple[str, str]:
    """Split a mixed message into a human preface and a large pasted body when possible."""
    if not text:
        return "", ""

    match = DOCUMENT_BLOCK_START_RE.search(text)
    if not match:
        return "", text

    preface = text[:match.start()].strip()
    body = text[match.start():].strip()

    if len(_strip_markdown_artifacts(preface)) < 40:
        return "", text

    return preface, body


def _extract_inline_user_request(text: str, max_chars: int = 240) -> str:
    """Pull out the clearest explicit ask from freeform user prose."""
    cleaned = _strip_markdown_artifacts(text)
    if not cleaned:
        return ""

    sentences = [
        sentence.strip()
        for sentence in re.split(r"(?<=[.!?])\s+", cleaned)
        if sentence.strip()
    ]
    if not sentences:
        return ""

    request_markers = (
        "can you",
        "could you",
        "would you",
        "help me",
        "help us",
        "please",
        "any insights",
        "what do you think",
        "give me",
        "suggest",
        "summarize",
        "compare",
        "review",
        "name for it",
        "pitch line",
        "why",
        "how",
    )
    candidates: List[tuple[int, str]] = []

    for sentence in sentences:
        lowered = sentence.lower()
        if len(sentence) > 320:
            continue
        if "?" in sentence or any(marker in lowered for marker in request_markers):
            clipped = _clip_text(sentence, max_chars)
            score = 0

            if "?" in sentence:
                score += 2
            for marker in request_markers:
                if marker in lowered:
                    score += 3

            sentence_len = len(clipped)
            if sentence_len >= 80:
                score += 3
            elif sentence_len >= 40:
                score += 2
            elif sentence_len >= 20:
                score += 1

            if re.match(r"^[A-Z]\)\s+", clipped):
                score -= 6
            if re.match(r"^\s*(option|choice)\b", lowered):
                score -= 4
            if "something else entirely" in lowered:
                score -= 5
            if len(clipped.split()) <= 5:
                score -= 3

            candidates.append((score, clipped))

    if candidates:
        candidates.sort(key=lambda item: (item[0], len(item[1])), reverse=True)
        return candidates[0][1]

    # Fall back to the tail of the prose, which often holds the actual ask.
    return _clip_text(" ".join(sentences[-2:]), max_chars)


def _extract_pasted_user_focus(text: str, max_chars: int = 240) -> str:
    """Prefer the human-authored ask/preface for mixed pasted messages."""
    if not text:
        return ""

    preface, body = _split_pasted_preface_and_body(text)
    if preface:
        preface_snippet = _prepare_snippet(preface, max_chars)
        if preface_snippet:
            return preface_snippet
        request = _extract_inline_user_request(preface, max_chars=max_chars)
        if request:
            return request

    request = _extract_inline_user_request(text, max_chars=max_chars)
    if request:
        return request

    return _extract_pasted_source_summary(body or text, max_chars=max_chars)


def _approx_token_estimate(text: str) -> int:
    """Approximate token count cheaply for bounded summaries."""
    return max(1, math.ceil(len(text) / 4))


def _is_probably_pasted_source(text: str) -> bool:
    """Heuristically detect pasted specs, PRDs, logs, or markdown-heavy source material."""
    if not text:
        return False

    line_count = len([line for line in text.splitlines() if line.strip()])
    markdownish_lines = len(
        [
            line
            for line in text.splitlines()
            if re.match(r"^\s*(#{1,6}\s+|[-*+]\s+|\d+(?:\.\d+){0,4}[.):-]?\s+|>\s+)", line)
        ]
    )

    return (
        "```" in text
        or len(text) > 1800
        or line_count > 22
        or (len(text) > 900 and line_count > 10)
        or (line_count > 10 and markdownish_lines / max(1, line_count) >= 0.35)
        or bool(re.search(r"\n\s*\|.+\|\s*\n", text))
    )


def _summarize_pasted_source_type(text: str) -> str:
    """Return a coarse label for pasted source material."""
    lowered = text.lower()

    if "```" in text:
        if re.search(r"```(?:python|js|javascript|ts|typescript|json|yaml|yml|sql|bash|sh)\b", lowered):
            return "User provided pasted code or config context."
        return "User provided pasted code block context."

    if re.search(r"\bprd\b|\bproduct requirements\b|\brequirements document\b", lowered):
        return "User provided pasted PRD context."

    if re.search(r"\bspec\b|\bspecification\b|\bacceptance criteria\b|\brequirements\b", lowered):
        return "User provided pasted specification context."

    if re.search(r"\berror\b|\btraceback\b|\bexception\b|\bstdout\b|\bstderr\b|\blog\b", lowered):
        return "User provided pasted logs or error output."

    if re.search(r"^\s*(#{1,6}\s+|[-*+]\s+|\d+(?:\.\d+){0,4}[.):-]?\s+)", text, re.MULTILINE):
        return "User provided pasted markdown outline context."

    if bool(re.search(r"\n\s*\|.+\|\s*\n", text)):
        return "User provided pasted table context."

    if re.search(r"\bapi\b|\bendpoint\b|\bschema\b|\bjson\b|\byaml\b", lowered):
        return "User provided pasted technical reference context."

    return "User provided long pasted source context."


def _compact_source_label(text: str) -> str:
    """Return a short source-type label suitable for inline summaries."""
    lowered = text.lower()

    if "```" in text:
        return "Pasted code/config"
    if re.search(r"\bprd\b|\bproduct requirements\b|\brequirements document\b", lowered):
        return "Pasted PRD"
    if re.search(r"\bspec\b|\bspecification\b|\bacceptance criteria\b|\brequirements\b", lowered):
        return "Pasted specification"
    if re.search(r"\berror\b|\btraceback\b|\bexception\b|\bstdout\b|\bstderr\b|\blog\b", lowered):
        return "Pasted logs/errors"
    if bool(re.search(r"\n\s*\|.+\|\s*\n", text)):
        return "Pasted table"
    if re.search(r"\bapi\b|\bendpoint\b|\bschema\b|\bjson\b|\byaml\b", lowered):
        return "Pasted technical reference"
    if re.search(r"^\s*(#{1,6}\s+|[-*+]\s+|\d+(?:\.\d+){0,4}[.):-]?\s+)", text, re.MULTILINE):
        return "Pasted markdown outline"
    return "Pasted source context"


def _dedupe_preserve_order(items: List[str]) -> List[str]:
    """Remove duplicates while preserving original order."""
    seen = set()
    deduped = []
    for item in items:
        normalized = item.lower()
        if normalized in seen:
            continue
        seen.add(normalized)
        deduped.append(item)
    return deduped


def _extract_pasted_source_summary(text: str, max_chars: int = PASTED_SOURCE_SUMMARY_MAX_CHARS) -> str:
    """Build a concise extractive synopsis for pasted source material."""
    if not text:
        return ""

    normalized = text.replace("\r\n", "\n").replace("\r", "\n")
    lines = [line.rstrip() for line in normalized.split("\n") if line.strip()]
    if not lines:
        return _compact_source_label(text)

    heading_candidates: List[str] = []
    prioritized_sections: List[str] = []
    bullets: List[str] = []
    short_paragraphs: List[str] = []
    sentence_candidates: List[str] = []

    section_keywords = (
        "objective",
        "goal",
        "problem",
        "overview",
        "summary",
        "scope",
        "requirements",
        "acceptance criteria",
        "deliverables",
        "constraints",
        "non-goals",
        "implementation",
        "success criteria",
        "key features",
    )

    for raw_line in lines:
        cleaned = _strip_markdown_artifacts(raw_line)
        if not cleaned:
            continue

        is_heading = bool(
            re.match(r"^\s*(#{1,6}\s+|\d+(?:\.\d+){0,4}\s+)", raw_line)
            or (raw_line.strip().endswith(":") and len(cleaned) <= 80)
        )
        is_bullet = bool(re.match(r"^\s*([-*+]\s+|\d+(?:\.\d+){0,4}[.):-]?\s+)", raw_line))

        if is_heading and len(cleaned) <= 90:
            heading_candidates.append(cleaned.rstrip(":"))
            lowered = cleaned.lower()
            if any(keyword in lowered for keyword in section_keywords):
                prioritized_sections.append(cleaned.rstrip(":"))
            continue

        if is_bullet:
            if 12 <= len(cleaned) <= 180:
                bullets.append(_clip_text(cleaned, 110))
            continue

        if len(cleaned) <= 180:
            short_paragraphs.append(_clip_text(cleaned, 130))

        for sentence in re.split(r"(?<=[.!?])\s+", cleaned):
            sentence = sentence.strip()
            if 20 <= len(sentence) <= 180:
                sentence_candidates.append(_clip_text(sentence, 140))

    heading_candidates = _dedupe_preserve_order(heading_candidates)
    prioritized_sections = _dedupe_preserve_order(prioritized_sections)
    bullets = _dedupe_preserve_order(bullets)
    short_paragraphs = _dedupe_preserve_order(short_paragraphs)
    sentence_candidates = _dedupe_preserve_order(sentence_candidates)

    title = ""
    if heading_candidates:
        title = heading_candidates[0]
    elif short_paragraphs:
        title = short_paragraphs[0]
    elif sentence_candidates:
        title = sentence_candidates[0]

    label = _compact_source_label(text)
    pieces: List[str] = []
    is_prose_fallback = (
        bool(sentence_candidates)
        and not heading_candidates
        and not bullets
        and not prioritized_sections
    )

    if title:
        if is_prose_fallback:
            pieces.append(title)
        else:
            pieces.append(f"{label}: {title}")
    else:
        pieces.append(label)

    if bullets:
        pieces.append(f"Key points: {'; '.join(bullets[:2])}")
    elif short_paragraphs:
        context_line = next(
            (
                paragraph
                for paragraph in short_paragraphs
                if paragraph.lower() != title.lower()
            ),
            "",
        )
        if context_line:
            pieces.append(f"Summary: {context_line}")
    elif sentence_candidates:
        supporting_sentences = [
            sentence
            for sentence in sentence_candidates
            if not title or sentence.lower() != title.lower()
        ]
        if supporting_sentences:
            pieces.append(f"Summary: {' '.join(supporting_sentences[:2])}")

    remaining_sections = [
        section
        for section in prioritized_sections
        if not title or section.lower() != title.lower()
    ]
    if remaining_sections:
        pieces.append(f"Sections: {', '.join(remaining_sections[:3])}")

    return _clip_text(". ".join(piece for piece in pieces if piece), max_chars)


def _iter_user_messages(conversation: Dict[str, Any]) -> List[str]:
    """Return raw user-authored message content."""
    return [
        message.get("content", "")
        for message in conversation.get("messages", [])
        if message.get("role") == "user" and message.get("content")
    ]


def _extract_current_goal(conversation: Dict[str, Any]) -> str:
    """Return the latest concise user ask, preferring non-document turns."""
    for raw_text in reversed(_iter_user_messages(conversation)):
        if _is_probably_pasted_source(raw_text):
            focused = _extract_pasted_user_focus(raw_text)
            if focused:
                return focused
            continue
        cleaned = _prepare_snippet(raw_text, 240)
        if cleaned:
            return cleaned

    latest_user_message = next(
        (
            message.get("content", "")
            for message in reversed(conversation.get("messages", []))
            if message.get("role") == "user" and message.get("content")
        ),
        "",
    )
    if _is_probably_pasted_source(latest_user_message):
        return _extract_pasted_user_focus(latest_user_message)
    return _prepare_snippet(latest_user_message, 240)


def _extract_user_objective(conversation: Dict[str, Any]) -> str:
    """Return the earliest concise user ask, not the earliest pasted blob."""
    document_context_summaries: List[str] = []
    for raw_text in _iter_user_messages(conversation):
        if _is_probably_pasted_source(raw_text):
            focused = _extract_pasted_user_focus(raw_text)
            if focused:
                return focused
            document_context_summaries.append(_extract_pasted_source_summary(raw_text))
            continue
        cleaned = _prepare_snippet(raw_text, 240)
        if cleaned:
            return cleaned

    if document_context_summaries:
        return document_context_summaries[0]
    return "No user objective recorded."


def _extract_recent_user_messages(conversation: Dict[str, Any], limit: int = 3) -> List[str]:
    """Return the most recent user messages."""
    messages = []
    document_context_summaries: List[str] = []

    for raw_text in _iter_user_messages(conversation):
        if _is_probably_pasted_source(raw_text):
            focused = _extract_pasted_user_focus(raw_text, max_chars=220)
            if focused:
                messages.append(focused)
            else:
                document_context_summaries.append(_extract_pasted_source_summary(raw_text))
            continue

        cleaned = _prepare_snippet(raw_text, 220)
        if cleaned:
            messages.append(cleaned)

    if not messages and document_context_summaries:
        return _dedupe_preserve_order(document_context_summaries)[:1]

    return messages[-limit:]


def _extract_recent_stage3_responses(conversation: Dict[str, Any], limit: int = 2) -> List[str]:
    """Return compact excerpts from recent Stage 3 assistant responses."""
    responses = []
    for message in conversation.get("messages", []):
        if message.get("role") != "assistant":
            continue

        stage3_response = message.get("stage3", {}).get("response")
        if stage3_response:
            responses.append(_prepare_snippet(stage3_response, 240))

    return responses[-limit:]


def _extract_persistent_constraints(conversation: Dict[str, Any], limit: int = 4) -> List[str]:
    """Extract stable user constraints from user-authored turns."""
    patterns = ("need", "want", "must", "should", "avoid", "don't", "do not", "keep")
    constraints: List[str] = []
    seen = set()

    for message in conversation.get("messages", []):
        if message.get("role") != "user":
            continue

        raw_text = message.get("content", "")
        if _is_probably_pasted_source(raw_text):
            continue

        text = _strip_markdown_artifacts(raw_text)
        if not text:
            continue

        sentences = re.split(r"(?<=[.!?])\s+", text)
        for sentence in sentences:
            lowered = sentence.lower()
            if not any(pattern in lowered for pattern in patterns):
                continue
            if sentence.strip().endswith("?"):
                continue
            if lowered.startswith("do you want"):
                continue
            if len(sentence) > 220:
                continue

            clipped = _clip_text(sentence, 160)
            if clipped and clipped.lower() not in seen:
                seen.add(clipped.lower())
                constraints.append(clipped)

    return constraints[-limit:]


def _extract_background_context_notes(conversation: Dict[str, Any]) -> List[str]:
    """Return coarse-grained notes when users pasted large source documents."""
    summaries = []

    for raw_text in _iter_user_messages(conversation):
        if not _is_probably_pasted_source(raw_text):
            continue

        _, body = _split_pasted_preface_and_body(raw_text)
        summaries.append(_extract_pasted_source_summary(body or raw_text))

    return _dedupe_preserve_order(summaries)[:3]


def _extract_open_threads(
    conversation: Dict[str, Any],
    current_goal: str,
    limit: int = 2,
) -> List[str]:
    """Return recent non-document asks that are still useful as open threads."""
    open_threads: List[str] = []
    seen = {current_goal.lower()} if current_goal else set()

    for raw_text in reversed(_iter_user_messages(conversation)):
        if _is_probably_pasted_source(raw_text):
            cleaned = _extract_pasted_user_focus(raw_text, max_chars=180)
            if cleaned:
                normalized = cleaned.lower()
                if normalized not in seen:
                    seen.add(normalized)
                    open_threads.append(cleaned)
                    if len(open_threads) >= limit:
                        break
            continue

        cleaned = _prepare_snippet(raw_text, 180)
        if not cleaned:
            continue

        normalized = cleaned.lower()
        if normalized in seen:
            continue

        seen.add(normalized)
        open_threads.append(cleaned)
        if len(open_threads) >= limit:
            break

    return list(reversed(open_threads))


def _extract_active_bundle(conversation: Dict[str, Any]) -> Dict[str, str]:
    """Return the latest selected bundle metadata."""
    for message in reversed(conversation.get("messages", [])):
        bundle = message.get("bundle")
        if bundle:
            return {
                "id": bundle.get("id", ""),
                "name": bundle.get("name", ""),
            }
    return {"id": "", "name": ""}


def render_memory_text(
    summary_json: Dict[str, Any],
    latest_stage3: str = "",
    max_tokens: int = DEFAULT_MEMORY_MAX_TOKENS,
) -> tuple[str, int]:
    """Render the human-readable summary text + token estimate from fields."""
    lines = [
        "Conversation Memory",
        f"- Current goal: {summary_json.get('current_goal') or 'No current goal recorded.'}",
    ]
    if (
        summary_json.get("user_objective")
        and summary_json["user_objective"] != summary_json.get("current_goal")
    ):
        lines.append(f"- Original objective: {summary_json['user_objective']}")
    if summary_json.get("background_context_notes"):
        lines.append("- Background context:")
        lines.extend(f"  - {item}" for item in summary_json["background_context_notes"])
    if summary_json.get("stable_constraints"):
        lines.append("- Stable constraints:")
        lines.extend(f"  - {item}" for item in summary_json["stable_constraints"])
    if summary_json.get("recent_decisions"):
        lines.append("- Recent decisions:")
        lines.extend(f"  - {item}" for item in summary_json["recent_decisions"])
    if summary_json.get("open_threads"):
        lines.append("- Open threads:")
        lines.extend(f"  - {item}" for item in summary_json["open_threads"])
    if summary_json.get("active_bundle", {}).get("name"):
        lines.append(f"- Active bundle: {summary_json['active_bundle']['name']}")

    latest_verdict_anchor = _prepare_snippet(latest_stage3, 200) if latest_stage3 else ""
    if latest_verdict_anchor and latest_verdict_anchor not in summary_json.get("recent_decisions", []):
        lines.append(f"- Latest verdict anchor: {latest_verdict_anchor}")

    summary_text = "\n".join(lines)
    if len(summary_text) > DEFAULT_MEMORY_MAX_CHARS:
        summary_text = _clip_text(summary_text, DEFAULT_MEMORY_MAX_CHARS)
    token_estimate = _approx_token_estimate(summary_text)
    if token_estimate > max_tokens:
        summary_text = _clip_text(summary_text, max_tokens * 4)
        token_estimate = _approx_token_estimate(summary_text)
    return summary_text, token_estimate


def build_memory_record(
    conversation: Dict[str, Any],
    max_tokens: int = DEFAULT_MEMORY_MAX_TOKENS,
) -> Dict[str, Any]:
    """Build a compact structured rolling memory payload for a conversation."""
    messages = conversation.get("messages", [])
    latest_stage3_response = next(
        (
            message.get("stage3", {}).get("response", "")
            for message in reversed(messages)
            if message.get("role") == "assistant" and message.get("stage3", {}).get("response")
        ),
        "",
    )
    active_bundle = _extract_active_bundle(conversation)
    current_goal = _extract_current_goal(conversation)
    user_objective = _extract_user_objective(conversation)
    stable_constraints = _extract_persistent_constraints(conversation)
    recent_user_requests = _extract_recent_user_messages(conversation)
    recent_decisions = _extract_recent_stage3_responses(conversation, limit=3)
    background_context_notes = _extract_background_context_notes(conversation)
    open_threads = _extract_open_threads(conversation, current_goal)

    summary_json = {
        "format_version": MEMORY_FORMAT_VERSION,
        "current_goal": current_goal,
        "user_objective": user_objective,
        "latest_user_request": current_goal,
        "stable_constraints": stable_constraints,
        "persistent_constraints": stable_constraints,
        "recent_user_requests": recent_user_requests,
        "recent_decisions": recent_decisions,
        "recent_council_conclusions": recent_decisions,
        "background_context_notes": background_context_notes,
        "open_threads": open_threads,
        "active_bundle": active_bundle,
        "turn_count": len(messages),
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }

    summary_text, token_estimate = render_memory_text(
        summary_json, latest_stage3_response, max_tokens
    )
    summary_json["token_estimate"] = token_estimate
    return {
        "summary_text": summary_text,
        "summary_json": summary_json,
        "token_estimate": token_estimate,
        "source_turn_count": len(messages),
    }


def build_turn_index_entries(conversation: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Build turn-level index rows from a transcript."""
    entries = []

    for turn_number, message in enumerate(conversation.get("messages", []), start=1):
        role = message.get("role", "unknown")
        created_at = message.get("created_at") or conversation.get("created_at")

        if role == "user":
            raw_content = message.get("content", "")
            if _is_probably_pasted_source(raw_content):
                short_highlight = _extract_pasted_user_focus(raw_content, max_chars=180)
            else:
                short_highlight = _prepare_snippet(raw_content, 180) or "User message"
            stage3_excerpt = None
        elif message.get("error"):
            error_message = message.get("error", {}).get("message", "Council error")
            short_highlight = _prepare_snippet(f"Council error: {error_message}", 180)
            stage3_excerpt = None
        else:
            stage3_response = message.get("stage3", {}).get("response", "")
            short_highlight = _prepare_snippet(stage3_response, 180) or "Council response"
            stage3_excerpt = _prepare_snippet(stage3_response, 420) if stage3_response else None

        entries.append(
            {
                "turn_number": turn_number,
                "role": role,
                "created_at": created_at,
                "short_highlight": short_highlight,
                "stage3_excerpt": stage3_excerpt,
                "transcript_offset": {"message_index": turn_number - 1},
            }
        )

    return entries


def merge_turn_index_entries(
    stored_entries: List[Dict[str, Any]],
    derived_entries: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """Prefer stored (worker-written) entries; fill missing turns from derived.

    The derived index always covers the full transcript, so it governs length.
    """
    stored_by_turn = {entry["turn_number"]: entry for entry in stored_entries}
    return [
        stored_by_turn.get(entry["turn_number"], entry)
        for entry in derived_entries
    ]
