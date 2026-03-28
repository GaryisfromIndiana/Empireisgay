"""Vector database integration — Qdrant-backed similarity search.

Replaces the in-memory cosine similarity with proper ANN search
that scales to millions of vectors with sub-millisecond latency.
"""
