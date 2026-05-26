"""Markdown export helpers for Obsidian-style note output."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

from . import postgres_store, storage
from .config import OBSIDIAN_EXPORTS_DIR
from .postprocess import build_memory_record, build_turn_index_entries


def ensure_obsidian_export_dirs() -> dict[str, Path]:
    """Ensure the Obsidian export directory tree exists."""
    conversations_dir = OBSIDIAN_EXPORTS_DIR / "conversations"
    highlights_dir = OBSIDIAN_EXPORTS_DIR / "highlights"
    indexes_dir = OBSIDIAN_EXPORTS_DIR / "indexes"

    for directory in (conversations_dir, highlights_dir, indexes_dir):
        directory.mkdir(parents=True, exist_ok=True)

    return {
        "root": OBSIDIAN_EXPORTS_DIR,
        "conversations": conversations_dir,
        "highlights": highlights_dir,
        "indexes": indexes_dir,
    }


def get_conversation_export_paths(conversation_id: str) -> dict[str, Path]:
    """Return deterministic export paths for one conversation."""
    directories = ensure_obsidian_export_dirs()
    return {
        "conversation": directories["conversations"] / f"{conversation_id}.md",
        "highlights": directories["highlights"] / f"{conversation_id}.md",
        "index": directories["indexes"] / "conversations.md",
    }


def conversation_exports_missing(conversation_id: str) -> bool:
    """Return True when the primary markdown exports for a conversation do not exist yet."""
    paths = get_conversation_export_paths(conversation_id)
    return not paths["conversation"].exists() or not paths["highlights"].exists()


def _relative_export_path(path: Path) -> str:
    """Return a path relative to the Obsidian export root."""
    return str(path.relative_to(OBSIDIAN_EXPORTS_DIR))


def _resolve_memory_payload(conversation_id: str, conversation: Dict[str, Any]) -> Dict[str, Any]:
    """Resolve stored rolling memory or derive it from the transcript."""
    latest_memory = postgres_store.get_latest_conversation_memory(conversation_id)
    if latest_memory:
        return {
            "version": latest_memory["version"],
            "summary_text": latest_memory["summary_text"],
            "summary_json": latest_memory.get("summary_json") or {},
            "token_estimate": latest_memory["token_estimate"],
            "source_turn_count": latest_memory["source_turn_count"],
            "updated_at": latest_memory["created_at"].isoformat(),
            "source": "postgres",
        }

    derived_memory = build_memory_record(conversation)
    return {
        "version": 0,
        "summary_text": derived_memory["summary_text"],
        "summary_json": derived_memory["summary_json"],
        "token_estimate": derived_memory["token_estimate"],
        "source_turn_count": derived_memory["source_turn_count"],
        "updated_at": derived_memory["summary_json"]["updated_at"],
        "source": "transcript",
    }


def _resolve_turn_index(conversation_id: str, conversation: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Resolve stored turn index rows or derive them from the transcript."""
    stored_turn_index = postgres_store.get_conversation_turn_index(conversation_id)
    if stored_turn_index:
        return [
            {
                **entry,
                "created_at": entry["created_at"].isoformat(),
            }
            for entry in stored_turn_index
        ]

    return build_turn_index_entries(conversation)


def _clean_single_line(text: str) -> str:
    """Collapse newlines for compact bullets and metadata lines."""
    return " ".join((text or "").split())


def _render_list_or_text_section(lines: list[str], title: str, content: Any):
    """Render one summary section into markdown."""
    if not content:
        return

    lines.append(f"### {title}")
    if isinstance(content, list):
        for item in content:
            cleaned = _clean_single_line(str(item))
            if cleaned:
                lines.append(f"- {cleaned}")
    else:
        lines.append(str(content).strip())
    lines.append("")


def _build_memory_sections(memory: Dict[str, Any]) -> list[tuple[str, Any]]:
    """Mirror the overview-pane memory section ordering for markdown exports."""
    summary_json = memory.get("summary_json") or {}

    current_goal = summary_json.get("current_goal") or summary_json.get("latest_user_request") or summary_json.get("user_objective") or ""
    objective = summary_json.get("user_objective") or ""
    background_context = summary_json.get("background_context_notes") or []
    constraints = summary_json.get("stable_constraints") or summary_json.get("persistent_constraints") or []
    decisions = summary_json.get("recent_decisions") or summary_json.get("recent_council_conclusions") or []
    open_threads = [
        item
        for item in (summary_json.get("open_threads") or summary_json.get("recent_user_requests") or [])
        if item and item != current_goal
    ]
    active_bundle = (summary_json.get("active_bundle") or {}).get("name") or ""

    sections: list[tuple[str, Any]] = []
    if current_goal:
        sections.append(("Current Goal", current_goal))
    if objective and objective != current_goal:
        sections.append(("Original Objective", objective))
    if background_context:
        sections.append(("Background Context", background_context))
    if constraints:
        sections.append(("Stable Constraints", constraints))
    if decisions:
        sections.append(("Recent Decisions", decisions))
    if open_threads:
        sections.append(("Open Threads", open_threads))
    if active_bundle:
        sections.append(("Active Bundle", active_bundle))

    if not sections and memory.get("summary_text"):
        sections.append(("Conversation Memory", memory["summary_text"]))

    return sections


def _render_aggregate_rankings(lines: list[str], rankings: list[Dict[str, Any]]):
    """Render aggregate model rankings into markdown."""
    if not rankings:
        return

    lines.append("#### Aggregate Rankings")
    for rank, entry in enumerate(rankings, start=1):
        model = entry.get("model", "unknown")
        average_rank = entry.get("average_rank")
        rankings_count = entry.get("rankings_count")
        average_rank_text = (
            f"{float(average_rank):.2f}"
            if isinstance(average_rank, (int, float))
            else str(average_rank)
        )
        lines.append(
            f"{rank}. `{model}` - average rank {average_rank_text} across {rankings_count} review(s)"
        )
    lines.append("")


def _render_assistant_message(lines: list[str], message: Dict[str, Any]):
    """Render one assistant message block."""
    bundle = message.get("bundle") or {}
    if bundle.get("name"):
        lines.append(f"- Bundle: `{bundle['name']}`")
    if bundle.get("chairman_model"):
        lines.append(f"- Chairman: `{bundle['chairman_model']}`")

    error = message.get("error")
    if error:
        lines.append("")
        lines.append("#### Error")
        lines.append("```text")
        lines.append(_clean_single_line(error.get("message", "Council request failed.")))
        details = error.get("details") or error.get("raw") or error.get("type")
        if details:
            lines.append(_clean_single_line(str(details)))
        lines.append("```")
        lines.append("")
        return

    final_response = message.get("stage3", {}).get("response", "").strip()
    if final_response:
        lines.append("")
        lines.append("#### Final Council Response")
        lines.append(final_response)
        lines.append("")

    aggregate_rankings = (message.get("metadata") or {}).get("aggregate_rankings") or []
    _render_aggregate_rankings(lines, aggregate_rankings)


def render_conversation_markdown(
    conversation: Dict[str, Any],
    memory: Dict[str, Any],
    turn_index: List[Dict[str, Any]],
) -> str:
    """Render the main conversation markdown note."""
    conversation_id = conversation["id"]
    title = conversation.get("title", "New Conversation")
    messages = conversation.get("messages", [])
    lines = [
        f"# {title}",
        "",
        f"- Conversation ID: `{conversation_id}`",
        f"- Created: `{conversation.get('created_at', '')}`",
        f"- Messages: {len(messages)}",
        f"- Archived: {'yes' if conversation.get('archived') else 'no'}",
        f"- Rolling memory source: `{memory.get('source', 'unknown')}`",
        f"- Rolling memory updated: `{memory.get('updated_at', '')}`",
        "",
        f"[Highlights](../highlights/{conversation_id}.md) | [Conversations Index](../indexes/conversations.md)",
        "",
        "## Rolling Summary",
        "",
    ]

    for section_title, section_content in _build_memory_sections(memory):
        _render_list_or_text_section(lines, section_title, section_content)

    lines.extend([
        "## Turn Highlights",
        "",
    ])
    if turn_index:
        for entry in turn_index:
            highlight = _clean_single_line(entry.get("short_highlight", ""))
            role = entry.get("role", "unknown").capitalize()
            turn_number = entry.get("turn_number", "?")
            lines.append(f"- Turn {turn_number} ({role}): {highlight}")
    else:
        lines.append("_No indexed turns yet._")
    lines.append("")

    lines.extend([
        "## Transcript",
        "",
    ])

    for index, message in enumerate(messages, start=1):
        role = message.get("role", "unknown").capitalize()
        lines.append(f"### Message {index} - {role}")
        if message.get("role") == "user":
            bundle = message.get("bundle") or {}
            if bundle.get("name"):
                lines.append(f"- Bundle: `{bundle['name']}`")
            lines.append("")
            lines.append("```text")
            lines.append((message.get("content") or "").rstrip())
            lines.append("```")
            lines.append("")
            continue

        _render_assistant_message(lines, message)

    return "\n".join(lines).rstrip() + "\n"


def render_highlights_markdown(
    conversation: Dict[str, Any],
    memory: Dict[str, Any],
    turn_index: List[Dict[str, Any]],
) -> str:
    """Render the compact highlights markdown note."""
    conversation_id = conversation["id"]
    title = conversation.get("title", "New Conversation")
    latest_verdict = next(
        (
            message.get("stage3", {}).get("response", "").strip()
            for message in reversed(conversation.get("messages", []))
            if message.get("role") == "assistant" and message.get("stage3", {}).get("response")
        ),
        "",
    )

    lines = [
        f"# Highlights - {title}",
        "",
        f"- Conversation: [Open conversation](../conversations/{conversation_id}.md)",
        f"- Conversation ID: `{conversation_id}`",
        f"- Updated: `{datetime.now(timezone.utc).isoformat()}`",
        "",
        "## Rolling Summary",
        "",
    ]

    for section_title, section_content in _build_memory_sections(memory):
        _render_list_or_text_section(lines, section_title, section_content)

    lines.extend([
        "## Turn Index",
        "",
    ])
    if turn_index:
        for entry in turn_index:
            turn_number = entry.get("turn_number", "?")
            role = entry.get("role", "unknown").capitalize()
            highlight = _clean_single_line(entry.get("short_highlight", ""))
            lines.append(f"### Turn {turn_number} - {role}")
            lines.append(f"- Highlight: {highlight}")
            stage3_excerpt = _clean_single_line(entry.get("stage3_excerpt", ""))
            if stage3_excerpt:
                lines.append(f"- Final response excerpt: {stage3_excerpt}")
            created_at = entry.get("created_at")
            if created_at:
                lines.append(f"- Timestamp: `{created_at}`")
            lines.append("")
    else:
        lines.append("_No indexed turns yet._")
        lines.append("")

    if latest_verdict:
        lines.extend([
            "## Latest Final Verdict",
            "",
            latest_verdict,
            "",
        ])

    return "\n".join(lines).rstrip() + "\n"


def render_conversations_index_markdown() -> str:
    """Render the global conversations index note."""
    active_conversations = storage.list_conversations(archived=False)
    archived_conversations = storage.list_conversations(archived=True)
    updated_at = datetime.now(timezone.utc).isoformat()

    lines = [
        "# LLM Council Conversations",
        "",
        f"- Updated: `{updated_at}`",
        f"- Active conversations: {len(active_conversations)}",
        f"- Archived conversations: {len(archived_conversations)}",
        "",
        "## Active",
        "",
    ]

    if active_conversations:
        for conversation in active_conversations:
            conversation_id = conversation["id"]
            title = conversation.get("title", "New Conversation")
            lines.append(
                f"- [{title}](../conversations/{conversation_id}.md) | "
                f"[Highlights](../highlights/{conversation_id}.md) | "
                f"{conversation.get('message_count', 0)} messages | "
                f"created `{conversation.get('created_at', '')}`"
            )
    else:
        lines.append("_No active conversations._")
    lines.append("")

    lines.extend([
        "## Archived",
        "",
    ])
    if archived_conversations:
        for conversation in archived_conversations:
            conversation_id = conversation["id"]
            title = conversation.get("title", "New Conversation")
            archived_at = conversation.get("archived_at") or ""
            lines.append(
                f"- [{title}](../conversations/{conversation_id}.md) | "
                f"[Highlights](../highlights/{conversation_id}.md) | "
                f"{conversation.get('message_count', 0)} messages | "
                f"archived `{archived_at}`"
            )
    else:
        lines.append("_No archived conversations._")
    lines.append("")

    return "\n".join(lines).rstrip() + "\n"


def export_conversation_markdown(
    conversation_id: str,
    conversation: Dict[str, Any] | None = None,
) -> list[Dict[str, Any]]:
    """Write deterministic markdown exports and return artifact rows to persist."""
    conversation = conversation or storage.get_conversation(conversation_id)
    if conversation is None:
        raise ValueError(f"Conversation {conversation_id} not found")

    paths = get_conversation_export_paths(conversation_id)
    memory = _resolve_memory_payload(conversation_id, conversation)
    turn_index = _resolve_turn_index(conversation_id, conversation)

    conversation_markdown = render_conversation_markdown(conversation, memory, turn_index)
    highlights_markdown = render_highlights_markdown(conversation, memory, turn_index)
    conversations_index_markdown = render_conversations_index_markdown()

    paths["conversation"].write_text(conversation_markdown, encoding="utf-8")
    paths["highlights"].write_text(highlights_markdown, encoding="utf-8")
    paths["index"].write_text(conversations_index_markdown, encoding="utf-8")

    return [
        {
            "artifact_type": "obsidian_conversation_markdown",
            "file_path": _relative_export_path(paths["conversation"]),
            "metadata": {
                "title": conversation.get("title", "New Conversation"),
                "message_count": len(conversation.get("messages", [])),
                "scope": "conversation",
            },
        },
        {
            "artifact_type": "obsidian_highlights_markdown",
            "file_path": _relative_export_path(paths["highlights"]),
            "metadata": {
                "title": conversation.get("title", "New Conversation"),
                "turn_count": len(turn_index),
                "scope": "conversation",
            },
        },
        {
            "artifact_type": "obsidian_conversations_index_markdown",
            "file_path": _relative_export_path(paths["index"]),
            "metadata": {
                "scope": "global",
                "active_conversation_count": len(storage.list_conversations(archived=False)),
                "archived_conversation_count": len(storage.list_conversations(archived=True)),
            },
            "global": True,
        },
    ]
