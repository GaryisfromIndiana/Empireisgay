"""Memory browsing routes."""

from __future__ import annotations

import logging
from flask import Blueprint, render_template, jsonify, request, current_app

logger = logging.getLogger(__name__)
memory_bp = Blueprint("memory", __name__)


@memory_bp.route("/")
def memory_overview():
    """Memory system overview."""
    empire_id = current_app.config.get("EMPIRE_ID", "")
    try:
        from core.memory.manager import MemoryManager
        mm = MemoryManager(empire_id)
        stats = mm.get_stats()
        recent = mm.recall(limit=10)
        return render_template("memory/overview.html", stats=stats.__dict__, recent=recent)
    except Exception as e:
        return render_template("memory/overview.html", stats={}, recent=[], error=str(e))


@memory_bp.route("/search")
def memory_search():
    """Search memories."""
    empire_id = current_app.config.get("EMPIRE_ID", "")
    query = request.args.get("q", "")
    memory_types = request.args.getlist("type")
    try:
        from core.memory.manager import MemoryManager
        mm = MemoryManager(empire_id)
        results = mm.search(query=query, memory_types=memory_types or None, limit=30)
        return render_template("memory/search.html", query=query, results=results, types=memory_types)
    except Exception as e:
        return render_template("memory/search.html", query=query, results=[], error=str(e))


@memory_bp.route("/by-type/<memory_type>")
def memories_by_type(memory_type: str):
    """List memories by type."""
    empire_id = current_app.config.get("EMPIRE_ID", "")
    try:
        from core.memory.manager import MemoryManager
        mm = MemoryManager(empire_id)
        memories = mm.recall(memory_types=[memory_type], limit=50)
        return jsonify(memories)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@memory_bp.route("/by-lieutenant/<lieutenant_id>")
def memories_by_lieutenant(lieutenant_id: str):
    """List memories for a lieutenant."""
    empire_id = current_app.config.get("EMPIRE_ID", "")
    try:
        from core.memory.manager import MemoryManager
        mm = MemoryManager(empire_id)
        memories = mm.recall(lieutenant_id=lieutenant_id, limit=50)
        return jsonify(memories)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@memory_bp.route("/decay", methods=["POST"])
def run_decay():
    """Manually trigger memory decay."""
    try:
        empire_id = current_app.config.get("EMPIRE_ID", "")
        from core.memory.manager import MemoryManager
        mm = MemoryManager(empire_id)
        decayed = mm.decay()
        return jsonify({"decayed": decayed})
    except Exception as e:
        logger.error("Memory decay error: %s", e)
        return jsonify({"error": str(e)}), 500


@memory_bp.route("/cleanup", methods=["POST"])
def run_cleanup():
    """Manually trigger memory cleanup."""
    try:
        empire_id = current_app.config.get("EMPIRE_ID", "")
        from core.memory.manager import MemoryManager
        mm = MemoryManager(empire_id)
        result = mm.cleanup()
        return jsonify(result)
    except Exception as e:
        logger.error("Memory cleanup error: %s", e)
        return jsonify({"error": str(e)}), 500


@memory_bp.route("/consolidate", methods=["POST"])
def run_consolidate():
    """Manually trigger memory consolidation."""
    try:
        empire_id = current_app.config.get("EMPIRE_ID", "")
        from core.memory.manager import MemoryManager
        mm = MemoryManager(empire_id)
        promoted = mm.consolidate()
        return jsonify({"promoted": promoted})
    except Exception as e:
        logger.error("Memory consolidation error: %s", e)
        return jsonify({"error": str(e)}), 500


@memory_bp.route("/repair", methods=["POST"])
def repair_decay():
    """One-shot repair: restore wrongly-decayed knowledge memories to full strength.

    Semantic, experiential, and design memories should not time-decay
    (only supersession removes them). This resets their decay_factor to 1.0
    unless they've been explicitly superseded.
    """
    empire_id = current_app.config.get("EMPIRE_ID", "")
    from db.engine import session_scope
    from db.models import MemoryEntry
    from sqlalchemy import select

    restored = 0
    by_type = {"semantic": 0, "experiential": 0, "design": 0}

    with session_scope() as session:
        entries = list(session.execute(
            select(MemoryEntry).where(MemoryEntry.empire_id == empire_id)
        ).scalars().all())

        for m in entries:
            if m.memory_type in ("semantic", "experiential", "design"):
                meta = m.metadata_json or {}
                is_superseded = isinstance(meta, dict) and meta.get("superseded_at")
                if not is_superseded and m.decay_factor < 1.0:
                    m.decay_factor = 1.0
                    m.effective_importance = m.importance_score * 1.0
                    by_type[m.memory_type] += 1
                    restored += 1

    return jsonify({"restored": restored, "by_type": by_type})


@memory_bp.route("/qdrant/status")
def qdrant_status():
    """Get Qdrant vector store status and stats."""
    try:
        from core.vector.store import VectorStore
        empire_id = current_app.config.get("EMPIRE_ID", "")
        vs = VectorStore.get_instance(empire_id)
        return jsonify(vs.get_stats())
    except Exception as e:
        return jsonify({"enabled": False, "error": str(e)})


@memory_bp.route("/qdrant/migrate", methods=["POST"])
def qdrant_migrate():
    """Bulk migrate all existing embeddings from Postgres/SQLite into Qdrant.

    One-shot operation — safe to run multiple times (upserts are idempotent).
    """
    empire_id = current_app.config.get("EMPIRE_ID", "")
    try:
        from core.vector.store import VectorStore
        vs = VectorStore.get_instance(empire_id)
        if not vs.enabled:
            return jsonify({"error": "Qdrant not configured. Set EMPIRE_QDRANT__URL."}), 400

        from db.engine import session_scope
        from db.models import MemoryEntry, KnowledgeEntity
        from sqlalchemy import select, and_

        mem_count = 0
        ent_count = 0

        # Migrate ALL memories with embeddings (any empire_id)
        with session_scope() as session:
            entries = list(session.execute(
                select(MemoryEntry).where(and_(
                    MemoryEntry.embedding_json.is_not(None),
                    MemoryEntry.memory_type.in_(["semantic", "experiential", "design"]),
                ))
            ).scalars().all())

            batch = []
            for e in entries:
                if e.embedding_json:
                    batch.append({
                        "memory_id": e.id,
                        "embedding": e.embedding_json,
                        "empire_id": e.empire_id or empire_id,
                        "lieutenant_id": e.lieutenant_id or "",
                        "memory_type": e.memory_type,
                        "importance": e.importance_score or 0.5,
                        "decay_factor": e.decay_factor or 1.0,
                    })
            mem_count = vs.upsert_memories_batch(batch)

        # Migrate ALL entities with embeddings
        with session_scope() as session:
            entities = list(session.execute(
                select(KnowledgeEntity).where(
                    KnowledgeEntity.embedding_json.is_not(None),
                )
            ).scalars().all())

            batch = []
            for e in entities:
                if e.embedding_json:
                    batch.append({
                        "entity_id": e.id,
                        "embedding": e.embedding_json,
                        "empire_id": e.empire_id or empire_id,
                        "entity_type": e.entity_type or "",
                        "name": e.name or "",
                        "importance": e.importance_score or 0.5,
                    })
            ent_count = vs.upsert_entities_batch(batch)

        return jsonify({
            "migrated_memories": mem_count,
            "migrated_entities": ent_count,
        })
    except Exception as e:
        logger.error("Qdrant migration error: %s", e)
        return jsonify({"error": str(e)}), 500


@memory_bp.route("/qdrant/debug")
def qdrant_debug():
    """Debug endpoint to check what the migration query finds."""
    from db.engine import session_scope
    from db.models import MemoryEntry, KnowledgeEntity
    from sqlalchemy import select, and_, func

    result = {}
    with session_scope() as session:
        # Count with embedding
        mem_with = session.execute(
            select(func.count(MemoryEntry.id)).where(
                and_(
                    MemoryEntry.embedding_json.is_not(None),
                    MemoryEntry.memory_type.in_(["semantic", "experiential", "design"]),
                )
            )
        ).scalar() or 0

        # Try fetching one to inspect
        sample = session.execute(
            select(MemoryEntry).where(
                MemoryEntry.embedding_json.is_not(None),
            ).limit(1)
        ).scalars().first()

        sample_info = None
        if sample:
            emb = sample.embedding_json
            sample_info = {
                "id": sample.id,
                "empire_id": sample.empire_id,
                "type": sample.memory_type,
                "embedding_type": type(emb).__name__,
                "embedding_len": len(emb) if isinstance(emb, (list, str)) else 0,
                "embedding_preview": str(emb)[:100] if emb else None,
            }

        ent_with = session.execute(
            select(func.count(KnowledgeEntity.id)).where(
                KnowledgeEntity.embedding_json.is_not(None),
            )
        ).scalar() or 0

        result = {
            "memories_with_embedding": mem_with,
            "entities_with_embedding": ent_with,
            "sample_memory": sample_info,
        }

    return jsonify(result)


@memory_bp.route("/embeddings/status")
def embedding_status():
    """Check how many memories and KG entities have embeddings."""
    empire_id = current_app.config.get("EMPIRE_ID", "")
    from db.engine import get_session
    from db.models import MemoryEntry, KnowledgeEntity
    from sqlalchemy import select, func, and_

    session = get_session()
    try:
        mem_total = session.execute(
            select(func.count(MemoryEntry.id)).where(
                and_(MemoryEntry.empire_id == empire_id,
                     MemoryEntry.memory_type.in_(["semantic", "experiential", "design"]))
            )
        ).scalar() or 0

        mem_with_emb = session.execute(
            select(func.count(MemoryEntry.id)).where(
                and_(MemoryEntry.empire_id == empire_id,
                     MemoryEntry.memory_type.in_(["semantic", "experiential", "design"]),
                     MemoryEntry.embedding_json.is_not(None))
            )
        ).scalar() or 0

        kg_total = session.execute(
            select(func.count(KnowledgeEntity.id)).where(
                KnowledgeEntity.empire_id == empire_id
            )
        ).scalar() or 0

        kg_with_emb = session.execute(
            select(func.count(KnowledgeEntity.id)).where(
                and_(KnowledgeEntity.empire_id == empire_id,
                     KnowledgeEntity.embedding_json.is_not(None))
            )
        ).scalar() or 0

        return jsonify({
            "memories": {"total": mem_total, "with_embeddings": mem_with_emb,
                         "coverage": f"{mem_with_emb/mem_total*100:.1f}%" if mem_total else "0%"},
            "kg_entities": {"total": kg_total, "with_embeddings": kg_with_emb,
                            "coverage": f"{kg_with_emb/kg_total*100:.1f}%" if kg_total else "0%"},
        })
    finally:
        session.close()
