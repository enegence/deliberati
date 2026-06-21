"""Background worker scaffold for post-processing jobs."""

import asyncio
import logging

from .config import (
    DATABASE_URL,
    OBSIDIAN_EXPORTS_DIR,
    ROLLING_MEMORY_MAX_TOKENS,
    TRANSCRIPTS_DIR,
)
from . import postgres_store, storage
from .entity_extraction import build_conversation_entities
from .markdown_exports import export_conversation_markdown
from .postprocess import build_memory_record, build_turn_index_entries
from .summarizer import build_llm_turn_index_entries
from .semantic_search import build_semantic_chunks


logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("llm_council.worker")


async def process_job(job: dict):
    """Process one claimed export job."""
    conversation_id = job["conversation_id"]
    conversation = storage.get_conversation(conversation_id)
    if conversation is None:
        raise ValueError(f"Conversation {conversation_id} not found for job {job['id']}")

    if job["job_type"] == "refresh_memory":
        memory_record = build_memory_record(
            conversation,
            max_tokens=ROLLING_MEMORY_MAX_TOKENS,
        )
        version = postgres_store.store_conversation_memory(
            conversation_id,
            memory_record["summary_text"],
            memory_record["summary_json"],
            memory_record["token_estimate"],
            memory_record["source_turn_count"],
        )
        if version is None:
            raise RuntimeError(f"Unable to store rolling memory for {conversation_id}")

        logger.info(
            "stored_memory conversation_id=%s version=%s token_estimate=%s",
            conversation_id,
            version,
            memory_record["token_estimate"],
        )
        return

    if job["job_type"] == "index_turns":
        existing_rows = postgres_store.get_conversation_turn_index(conversation_id)
        entries = await build_llm_turn_index_entries(conversation, existing_rows)
        if not postgres_store.replace_turn_index(conversation_id, entries):
            raise RuntimeError(f"Unable to replace turn index for {conversation_id}")

        logger.info(
            "stored_turn_index conversation_id=%s entries=%s",
            conversation_id,
            len(entries),
        )
        return

    if job["job_type"] == "export_markdown":
        artifacts = export_conversation_markdown(conversation_id, conversation)
        if not postgres_store.store_export_artifacts(conversation_id, artifacts):
            raise RuntimeError(f"Unable to store export artifacts for {conversation_id}")

        logger.info(
            "exported_markdown conversation_id=%s artifacts=%s",
            conversation_id,
            len(artifacts),
        )
        return

    if job["job_type"] == "chunk_semantic":
        chunks = build_semantic_chunks(conversation)
        if not postgres_store.replace_semantic_chunks(conversation_id, chunks):
            raise RuntimeError(f"Unable to store semantic chunks for {conversation_id}")

        logger.info(
            "stored_semantic_chunks conversation_id=%s chunks=%s",
            conversation_id,
            len(chunks),
        )
        return

    if job["job_type"] == "extract_entities":
        entities = build_conversation_entities(conversation)
        if not postgres_store.replace_conversation_entities(conversation_id, entities):
            raise RuntimeError(f"Unable to store extracted entities for {conversation_id}")

        logger.info(
            "stored_entities conversation_id=%s entities=%s",
            conversation_id,
            len(entities),
        )
        return

    raise ValueError(f"Unsupported job type: {job['job_type']}")


async def run_worker():
    """Run the background worker loop."""
    logger.info("worker starting")
    logger.info("database_url_configured=%s", bool(DATABASE_URL))
    logger.info("transcripts_dir=%s", TRANSCRIPTS_DIR)
    logger.info("obsidian_exports_dir=%s", OBSIDIAN_EXPORTS_DIR)
    logger.info("worker active")

    while True:
        if not postgres_store.is_configured():
            await asyncio.sleep(30)
            continue

        job = postgres_store.claim_next_export_job()
        if not job:
            await asyncio.sleep(5)
            continue

        logger.info(
            "claimed_job id=%s type=%s conversation_id=%s",
            job["id"],
            job["job_type"],
            job["conversation_id"],
        )
        try:
            await process_job(job)
            postgres_store.complete_export_job(job["id"])
        except Exception as exc:
            logger.exception("Job failed id=%s type=%s", job["id"], job["job_type"])
            postgres_store.fail_export_job(job["id"], str(exc))


def main():
    asyncio.run(run_worker())


if __name__ == "__main__":
    main()
