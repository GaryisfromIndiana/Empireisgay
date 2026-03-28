"""Qdrant vector store — handles collection management, upsert, and search.

Two collections per empire:
  - {prefix}_memories   — MemoryEntry embeddings
  - {prefix}_entities   — KnowledgeEntity embeddings

Each point stores the DB primary key as its ID and metadata as payload,
so search results can be joined back to the full DB records.
"""

from __future__ import annotations

import hashlib
import logging
import threading
from typing import Any, Optional

logger = logging.getLogger(__name__)

# Qdrant is optional — graceful fallback if not installed/configured
_qdrant_available = False
try:
    from qdrant_client import QdrantClient
    from qdrant_client.models import (
        Distance,
        FieldCondition,
        Filter,
        HasIdCondition,
        HnswConfigDiff,
        MatchAny,
        MatchValue,
        PointStruct,
        VectorParams,
    )
    _qdrant_available = True
except ImportError:
    pass


def _stable_uuid(string_id: str) -> str:
    """Convert a string ID to a deterministic UUID-like hex string for Qdrant point IDs."""
    return hashlib.md5(string_id.encode()).hexdigest()


class VectorStore:
    """Qdrant vector store for Empire embeddings.

    Thread-safe singleton per empire. Falls back gracefully
    when Qdrant is not configured — callers should check `enabled`.
    """

    _instances: dict[str, VectorStore] = {}
    _instance_lock = threading.Lock()

    @classmethod
    def get_instance(cls, empire_id: str = "") -> VectorStore:
        with cls._instance_lock:
            if empire_id not in cls._instances:
                cls._instances[empire_id] = cls(empire_id)
            return cls._instances[empire_id]

    def __init__(self, empire_id: str = ""):
        self._empire_id = empire_id
        self._client: Optional[Any] = None
        self._enabled = False
        self._initialized = False
        self._lock = threading.Lock()

        self._collection_memories = ""
        self._collection_entities = ""
        self._dimension = 1536

        self._init()

    def _init(self) -> None:
        """Initialize Qdrant client and ensure collections exist."""
        if not _qdrant_available:
            logger.debug("qdrant-client not installed — vector store disabled")
            return

        try:
            from config.settings import get_settings
            settings = get_settings()
            qdrant_cfg = settings.qdrant

            if not qdrant_cfg.url:
                logger.debug("EMPIRE_QDRANT__URL not set — vector store disabled")
                return

            self._dimension = qdrant_cfg.embedding_dimension
            prefix = qdrant_cfg.collection_prefix
            self._collection_memories = f"{prefix}_memories"
            self._collection_entities = f"{prefix}_entities"

            # Connect
            kwargs: dict[str, Any] = {"url": qdrant_cfg.url, "timeout": 30}
            if qdrant_cfg.api_key:
                kwargs["api_key"] = qdrant_cfg.api_key

            self._client = QdrantClient(**kwargs)

            # Ensure collections exist
            hnsw = HnswConfigDiff(
                m=qdrant_cfg.hnsw_m,
                ef_construct=qdrant_cfg.hnsw_ef,
            )
            self._ensure_collection(self._collection_memories, hnsw, qdrant_cfg.on_disk)
            self._ensure_collection(self._collection_entities, hnsw, qdrant_cfg.on_disk)

            self._enabled = True
            self._initialized = True
            logger.info(
                "Qdrant vector store connected: %s (collections: %s, %s)",
                qdrant_cfg.url, self._collection_memories, self._collection_entities,
            )
        except Exception as e:
            logger.warning("Qdrant initialization failed (falling back to SQL): %s", e)
            self._enabled = False

    def _ensure_collection(self, name: str, hnsw: Any, on_disk: bool) -> None:
        """Create a collection if it doesn't exist."""
        try:
            self._client.get_collection(name)
        except Exception:
            self._client.create_collection(
                collection_name=name,
                vectors_config=VectorParams(
                    size=self._dimension,
                    distance=Distance.COSINE,
                    on_disk=on_disk,
                ),
                hnsw_config=hnsw,
            )
            logger.info("Created Qdrant collection: %s", name)

    @property
    def enabled(self) -> bool:
        return self._enabled

    # ── Memory operations ─────────────────────────────────────────────

    def upsert_memory(
        self,
        memory_id: str,
        embedding: list[float],
        empire_id: str,
        lieutenant_id: str = "",
        memory_type: str = "",
        importance: float = 0.5,
        decay_factor: float = 1.0,
    ) -> bool:
        """Upsert a memory embedding into Qdrant."""
        if not self._enabled:
            return False
        try:
            point_id = _stable_uuid(memory_id)
            self._client.upsert(
                collection_name=self._collection_memories,
                points=[PointStruct(
                    id=point_id,
                    vector=embedding,
                    payload={
                        "memory_id": memory_id,
                        "empire_id": empire_id,
                        "lieutenant_id": lieutenant_id,
                        "memory_type": memory_type,
                        "importance": importance,
                        "decay_factor": decay_factor,
                    },
                )],
            )
            return True
        except Exception as e:
            logger.error("Qdrant memory upsert failed: %s", e)
            return False

    def upsert_memories_batch(
        self,
        items: list[dict],
    ) -> int:
        """Batch upsert memory embeddings.

        Each item: {memory_id, embedding, empire_id, lieutenant_id, memory_type, importance, decay_factor}
        """
        if not self._enabled or not items:
            return 0
        try:
            points = []
            for item in items:
                point_id = _stable_uuid(item["memory_id"])
                points.append(PointStruct(
                    id=point_id,
                    vector=item["embedding"],
                    payload={
                        "memory_id": item["memory_id"],
                        "empire_id": item.get("empire_id", self._empire_id),
                        "lieutenant_id": item.get("lieutenant_id", ""),
                        "memory_type": item.get("memory_type", ""),
                        "importance": item.get("importance", 0.5),
                        "decay_factor": item.get("decay_factor", 1.0),
                    },
                ))

            # Batch in chunks
            from config.settings import get_settings
            batch_size = get_settings().qdrant.batch_upsert_size
            for i in range(0, len(points), batch_size):
                chunk = points[i:i + batch_size]
                self._client.upsert(
                    collection_name=self._collection_memories,
                    points=chunk,
                )
            return len(points)
        except Exception as e:
            logger.error("Qdrant batch memory upsert failed: %s", e)
            return 0

    def search_memories(
        self,
        embedding: list[float],
        empire_id: str,
        lieutenant_id: str | None = None,
        memory_types: list[str] | None = None,
        limit: int = 10,
        min_score: float = 0.35,
    ) -> list[dict]:
        """Search for similar memories in Qdrant.

        Returns: list of {memory_id, score} dicts, sorted by similarity.
        """
        if not self._enabled:
            return []
        try:
            must_conditions = [
                FieldCondition(key="empire_id", match=MatchValue(value=empire_id)),
            ]
            if lieutenant_id:
                must_conditions.append(
                    FieldCondition(key="lieutenant_id", match=MatchValue(value=lieutenant_id))
                )
            if memory_types:
                must_conditions.append(
                    FieldCondition(key="memory_type", match=MatchAny(any=memory_types))
                )

            results = self._client.search(
                collection_name=self._collection_memories,
                query_vector=embedding,
                query_filter=Filter(must=must_conditions),
                limit=limit,
                score_threshold=min_score,
            )

            return [
                {
                    "memory_id": hit.payload.get("memory_id", ""),
                    "score": hit.score,
                    "memory_type": hit.payload.get("memory_type", ""),
                }
                for hit in results
            ]
        except Exception as e:
            logger.error("Qdrant memory search failed: %s", e)
            return []

    def delete_memory(self, memory_id: str) -> bool:
        """Delete a memory from Qdrant."""
        if not self._enabled:
            return False
        try:
            point_id = _stable_uuid(memory_id)
            self._client.delete(
                collection_name=self._collection_memories,
                points_selector=[point_id],
            )
            return True
        except Exception as e:
            logger.error("Qdrant memory delete failed: %s", e)
            return False

    # ── Entity operations ─────────────────────────────────────────────

    def upsert_entity(
        self,
        entity_id: str,
        embedding: list[float],
        empire_id: str,
        entity_type: str = "",
        name: str = "",
        importance: float = 0.5,
    ) -> bool:
        """Upsert a knowledge entity embedding into Qdrant."""
        if not self._enabled:
            return False
        try:
            point_id = _stable_uuid(entity_id)
            self._client.upsert(
                collection_name=self._collection_entities,
                points=[PointStruct(
                    id=point_id,
                    vector=embedding,
                    payload={
                        "entity_id": entity_id,
                        "empire_id": empire_id,
                        "entity_type": entity_type,
                        "name": name,
                        "importance": importance,
                    },
                )],
            )
            return True
        except Exception as e:
            logger.error("Qdrant entity upsert failed: %s", e)
            return False

    def upsert_entities_batch(self, items: list[dict]) -> int:
        """Batch upsert entity embeddings.

        Each item: {entity_id, embedding, empire_id, entity_type, name, importance}
        """
        if not self._enabled or not items:
            return 0
        try:
            points = []
            for item in items:
                point_id = _stable_uuid(item["entity_id"])
                points.append(PointStruct(
                    id=point_id,
                    vector=item["embedding"],
                    payload={
                        "entity_id": item["entity_id"],
                        "empire_id": item.get("empire_id", self._empire_id),
                        "entity_type": item.get("entity_type", ""),
                        "name": item.get("name", ""),
                        "importance": item.get("importance", 0.5),
                    },
                ))

            from config.settings import get_settings
            batch_size = get_settings().qdrant.batch_upsert_size
            for i in range(0, len(points), batch_size):
                chunk = points[i:i + batch_size]
                self._client.upsert(
                    collection_name=self._collection_entities,
                    points=chunk,
                )
            return len(points)
        except Exception as e:
            logger.error("Qdrant batch entity upsert failed: %s", e)
            return 0

    def search_entities(
        self,
        embedding: list[float],
        empire_id: str,
        entity_type: str = "",
        limit: int = 10,
        min_score: float = 0.5,
    ) -> list[dict]:
        """Search for similar entities in Qdrant.

        Returns: list of {entity_id, score, name, entity_type} dicts.
        """
        if not self._enabled:
            return []
        try:
            must_conditions = [
                FieldCondition(key="empire_id", match=MatchValue(value=empire_id)),
            ]
            if entity_type:
                must_conditions.append(
                    FieldCondition(key="entity_type", match=MatchValue(value=entity_type))
                )

            results = self._client.search(
                collection_name=self._collection_entities,
                query_vector=embedding,
                query_filter=Filter(must=must_conditions),
                limit=limit,
                score_threshold=min_score,
            )

            return [
                {
                    "entity_id": hit.payload.get("entity_id", ""),
                    "score": hit.score,
                    "name": hit.payload.get("name", ""),
                    "entity_type": hit.payload.get("entity_type", ""),
                }
                for hit in results
            ]
        except Exception as e:
            logger.error("Qdrant entity search failed: %s", e)
            return []

    def delete_entity(self, entity_id: str) -> bool:
        """Delete an entity from Qdrant."""
        if not self._enabled:
            return False
        try:
            point_id = _stable_uuid(entity_id)
            self._client.delete(
                collection_name=self._collection_entities,
                points_selector=[point_id],
            )
            return True
        except Exception as e:
            logger.error("Qdrant entity delete failed: %s", e)
            return False

    # ── Admin operations ──────────────────────────────────────────────

    def get_stats(self) -> dict:
        """Get collection statistics."""
        if not self._enabled:
            return {"enabled": False}
        try:
            mem_info = self._client.get_collection(self._collection_memories)
            ent_info = self._client.get_collection(self._collection_entities)
            return {
                "enabled": True,
                "memories": {
                    "collection": self._collection_memories,
                    "points": mem_info.points_count or 0,
                    "status": mem_info.status.value if hasattr(mem_info.status, 'value') else str(mem_info.status),
                },
                "entities": {
                    "collection": self._collection_entities,
                    "points": ent_info.points_count or 0,
                    "status": ent_info.status.value if hasattr(ent_info.status, 'value') else str(ent_info.status),
                },
            }
        except Exception as e:
            return {"enabled": True, "error": str(e)}

    def drop_collections(self) -> None:
        """Drop all collections (for testing/reset)."""
        if not self._enabled:
            return
        try:
            self._client.delete_collection(self._collection_memories)
            self._client.delete_collection(self._collection_entities)
            logger.warning("Dropped Qdrant collections")
        except Exception as e:
            logger.error("Failed to drop collections: %s", e)
