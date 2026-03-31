"""Unit tests for web searcher parsing and API fallbacks."""

from __future__ import annotations

from core.search.web import WebSearcher


class _PositionalDDGS:
    def text(self, query: str, **kwargs):
        return [
            {
                "title": f"title:{query}",
                "href": "https://example.com/post",
                "body": "snippet body",
            }
        ]


class _LegacyDDGS:
    def text(self, *, keywords: str, **kwargs):
        return [
            {
                "title": f"legacy:{keywords}",
                "link": "https://example.org/legacy",
                "snippet": "legacy snippet",
            }
        ]


def test_search_parses_results_with_positional_api() -> None:
    searcher = WebSearcher("empire-alpha")
    searcher._ddgs = _PositionalDDGS()

    response = searcher.search("agents", max_results=1)
    assert response.total_results == 1
    assert response.results[0].title == "title:agents"
    assert response.results[0].url == "https://example.com/post"
    assert response.results[0].source == "example.com"


def test_search_falls_back_to_legacy_keywords_api() -> None:
    searcher = WebSearcher("empire-alpha")
    searcher._ddgs = _LegacyDDGS()

    response = searcher.search("memory", max_results=1)
    assert response.total_results == 1
    assert response.results[0].title == "legacy:memory"
    assert response.results[0].url == "https://example.org/legacy"
