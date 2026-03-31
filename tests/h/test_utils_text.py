"""Fast unit tests for text utility helpers."""

from __future__ import annotations

from utils.text import (
    chunk_text,
    format_cost,
    format_duration,
    format_tokens,
    slugify,
    truncate,
)


def test_truncate_appends_suffix() -> None:
    assert truncate("hello world", 8) == "hello..."


def test_slugify_normalizes_text() -> None:
    assert slugify(" Hello, World! 2026 ") == "hello-world-2026"


def test_formatters_return_expected_units() -> None:
    assert format_cost(0.0009) == "$0.000900"
    assert format_tokens(1500) == "1.5K"
    assert format_duration(90) == "1.5m"


def test_chunk_text_splits_large_input() -> None:
    chunks = chunk_text("a" * 9000, chunk_size=4000, overlap=100)
    assert len(chunks) >= 3
    assert max(len(chunk) for chunk in chunks) <= 4000
