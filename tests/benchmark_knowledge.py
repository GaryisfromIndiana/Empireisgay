#!/usr/bin/env python3
"""Benchmark knowledge graph operations to verify N+1 fixes."""

from __future__ import annotations

import time
import sys
from pathlib import Path

# Add parent to path
sys.path.insert(0, str(Path(__file__).parent.parent))


def benchmark_neighbors(empire_id: str, depth: int = 2) -> float:
    """Benchmark get_neighbors operation."""
    from db.engine import get_session
    from db.repositories.knowledge import KnowledgeRepository
    
    session = get_session()
    try:
        repo = KnowledgeRepository(session)
        entities = repo.get_by_empire(empire_id, limit=5)
        
        if not entities:
            print("No entities found to benchmark")
            return 0.0
        
        start = time.time()
        for entity in entities:
            neighbors = repo.get_neighbors(entity.id, max_depth=depth)
        elapsed = time.time() - start
        
        return elapsed
    finally:
        session.close()


def benchmark_query(empire_id: str) -> float:
    """Benchmark knowledge queries with relations."""
    from core.knowledge.query import KnowledgeQuerier
    
    querier = KnowledgeQuerier(empire_id)
    
    start = time.time()
    answer = querier.ask("What do we know about Claude?", depth=2)
    elapsed = time.time() - start
    
    return elapsed


def benchmark_export_graph(empire_id: str) -> float:
    """Benchmark graph export (tests eager loading)."""
    from core.knowledge.graph import KnowledgeGraph
    
    graph = KnowledgeGraph(empire_id)
    
    start = time.time()
    exported = graph.export_graph()
    elapsed = time.time() - start
    
    return elapsed


def run_benchmarks(empire_id: str = "") -> None:
    """Run all knowledge graph benchmarks."""
    if not empire_id:
        from config.settings import get_settings
        empire_id = get_settings().empire_id or "empire-alpha"
    
    print(f"Benchmarking knowledge graph for empire: {empire_id}")
    print("=" * 60)
    
    # Test 1: Neighbor traversal
    print("\n1. Knowledge graph neighbor traversal (depth=2):")
    try:
        t1 = benchmark_neighbors(empire_id, depth=2)
        print(f"   ✓ Completed in {t1:.2f}s")
        if t1 > 5.0:
            print(f"   ⚠ Slow (expected < 2s). Check if N+1 fixes applied.")
    except Exception as e:
        print(f"   ✗ Failed: {e}")
    
    # Test 2: Knowledge query
    print("\n2. Knowledge query with relations:")
    try:
        t2 = benchmark_query(empire_id)
        print(f"   ✓ Completed in {t2:.2f}s")
        if t2 > 3.0:
            print(f"   ⚠ Slow (expected < 1s). Check if batch fetching applied.")
    except Exception as e:
        print(f"   ✗ Failed: {e}")
    
    # Test 3: Graph export
    print("\n3. Graph export (tests eager loading):")
    try:
        t3 = benchmark_export_graph(empire_id)
        print(f"   ✓ Completed in {t3:.2f}s")
        if t3 > 10.0:
            print(f"   ⚠ Slow (expected < 5s). Check if eager loading applied.")
    except Exception as e:
        print(f"   ✗ Failed: {e}")
    
    print("\n" + "=" * 60)
    print("Benchmark complete.")


if __name__ == "__main__":
    empire_id = sys.argv[1] if len(sys.argv) > 1 else ""
    run_benchmarks(empire_id)
