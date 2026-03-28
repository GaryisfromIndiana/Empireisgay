"""Embedding generation for memory and knowledge graph entries.

Wraps OpenAI embeddings with error handling, truncation, and caching.
Used by MemoryManager.store(), BiTemporalMemory.store_fact(), and
the backfill scheduler job.
"""

from __future__ import annotations

import logging
from typing import Optional

logger = logging.getLogger(__name__)

# text-embedding-3-small max input is 8191 tokens (~32k chars).
# Truncate to be safe.
_MAX_CHARS = 24_000


def generate_embedding(text: str) -> Optional[list[float]]:
    """Generate an embedding vector for text.

    Returns None on any failure (missing API key, rate limit, etc.)
    so callers can store the memory without an embedding and backfill later.
    """
    if not text or not text.strip():
        return None

    try:
        from llm.openai import OpenAIClient
        client = OpenAIClient()
        truncated = text[:_MAX_CHARS]
        return client.create_embedding(truncated)
    except Exception as e:
        logger.debug("Embedding generation failed (will backfill later): %s", e)
        return None


def generate_embeddings_batch(texts: list[str]) -> list[Optional[list[float]]]:
    """Generate embeddings for multiple texts.

    Returns a list parallel to input — None for any that failed.
    Processes in chunks of 100 (OpenAI batch limit).
    """
    if not texts:
        return []

    try:
        from llm.openai import OpenAIClient
        client = OpenAIClient()
    except Exception as e:
        logger.debug("OpenAI client init failed: %s", e)
        return [None] * len(texts)

    results: list[Optional[list[float]]] = [None] * len(texts)
    chunk_size = 100

    for start in range(0, len(texts), chunk_size):
        chunk = texts[start:start + chunk_size]
        truncated = [t[:_MAX_CHARS] if t else "" for t in chunk]

        # Skip empty strings
        non_empty_indices = [i for i, t in enumerate(truncated) if t.strip()]
        if not non_empty_indices:
            continue

        non_empty_texts = [truncated[i] for i in non_empty_indices]

        try:
            embeddings = client.create_embeddings_batch(non_empty_texts)
            for idx, emb in zip(non_empty_indices, embeddings):
                results[start + idx] = emb
        except Exception as e:
            logger.warning("Batch embedding failed for chunk %d: %s", start, e)

    return results
