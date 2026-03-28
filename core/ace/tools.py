"""Tool use orchestration for the ACE pipeline.

Defines tools that the LLM can use during task execution,
including memory recall, knowledge lookup, and web search.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from typing import Any, Callable

from llm.base import ToolDefinition

logger = logging.getLogger(__name__)


@dataclass
class ToolResult:
    """Result from executing a tool."""
    tool_name: str
    success: bool = True
    output: str = ""
    data: dict = field(default_factory=dict)
    error: str = ""


@dataclass
class ToolRegistration:
    """A registered tool with its handler."""
    definition: ToolDefinition
    handler: Callable[[dict], ToolResult]
    requires_empire_id: bool = False
    requires_lieutenant_id: bool = False


class ToolRegistry:
    """Registry of tools available to the ACE pipeline.

    Tools can be registered and made available to LLMs during execution.
    Handles tool definition conversion and result formatting.
    """

    def __init__(self, empire_id: str = "", lieutenant_id: str = ""):
        self.empire_id = empire_id
        self.lieutenant_id = lieutenant_id
        self._tools: dict[str, ToolRegistration] = {}
        self._register_builtin_tools()

    def _register_builtin_tools(self) -> None:
        """Register built-in tools."""
        self.register(ToolRegistration(
            definition=ToolDefinition(
                name="recall_memory",
                description="Search and recall relevant memories from the lieutenant's memory system",
                parameters={
                    "type": "object",
                    "properties": {
                        "query": {"type": "string", "description": "Search query for memories"},
                        "memory_type": {
                            "type": "string",
                            "enum": ["semantic", "experiential", "design", "episodic"],
                            "description": "Type of memory to search",
                        },
                        "limit": {"type": "integer", "description": "Maximum results", "default": 5},
                    },
                    "required": ["query"],
                },
            ),
            handler=self._tool_recall_memory,
            requires_empire_id=True,
        ))

        self.register(ToolRegistration(
            definition=ToolDefinition(
                name="lookup_knowledge",
                description="Search the knowledge graph for entities and their relations",
                parameters={
                    "type": "object",
                    "properties": {
                        "query": {"type": "string", "description": "Entity or topic to search for"},
                        "entity_type": {"type": "string", "description": "Filter by entity type"},
                        "include_neighbors": {"type": "boolean", "description": "Include related entities", "default": True},
                    },
                    "required": ["query"],
                },
            ),
            handler=self._tool_lookup_knowledge,
            requires_empire_id=True,
        ))

        self.register(ToolRegistration(
            definition=ToolDefinition(
                name="store_finding",
                description="Store an important finding or fact in memory for future reference",
                parameters={
                    "type": "object",
                    "properties": {
                        "content": {"type": "string", "description": "The finding to store"},
                        "importance": {"type": "number", "description": "Importance score (0-1)", "default": 0.6},
                        "category": {"type": "string", "description": "Category for the finding"},
                    },
                    "required": ["content"],
                },
            ),
            handler=self._tool_store_finding,
            requires_empire_id=True,
        ))

        self.register(ToolRegistration(
            definition=ToolDefinition(
                name="check_previous_work",
                description="Check if similar work has been done before and get the results",
                parameters={
                    "type": "object",
                    "properties": {
                        "description": {"type": "string", "description": "Description of the work to check for"},
                    },
                    "required": ["description"],
                },
            ),
            handler=self._tool_check_previous_work,
            requires_empire_id=True,
        ))

        self.register(ToolRegistration(
            definition=ToolDefinition(
                name="estimate_cost",
                description="Estimate the cost of an LLM operation before executing it",
                parameters={
                    "type": "object",
                    "properties": {
                        "task_type": {"type": "string", "description": "Type of task"},
                        "complexity": {"type": "string", "enum": ["simple", "moderate", "complex", "expert"]},
                        "input_length": {"type": "integer", "description": "Estimated input length in characters"},
                    },
                    "required": ["task_type"],
                },
            ),
            handler=self._tool_estimate_cost,
        ))

        self.register(ToolRegistration(
            definition=ToolDefinition(
                name="get_best_practices",
                description="Get best practices and patterns for a domain or task type",
                parameters={
                    "type": "object",
                    "properties": {
                        "domain": {"type": "string", "description": "Domain to get best practices for"},
                        "task_type": {"type": "string", "description": "Type of task"},
                    },
                    "required": ["domain"],
                },
            ),
            handler=self._tool_get_best_practices,
            requires_empire_id=True,
        ))

        self.register(ToolRegistration(
            definition=ToolDefinition(
                name="web_search",
                description="Search the web for current information. Use this to find the latest news, research, and developments.",
                parameters={
                    "type": "object",
                    "properties": {
                        "query": {"type": "string", "description": "Search query"},
                        "max_results": {"type": "integer", "description": "Maximum results", "default": 5},
                    },
                    "required": ["query"],
                },
            ),
            handler=self._tool_web_search,
            requires_empire_id=True,
        ))

        self.register(ToolRegistration(
            definition=ToolDefinition(
                name="search_news",
                description="Search for recent news articles. Great for finding the latest AI developments and announcements.",
                parameters={
                    "type": "object",
                    "properties": {
                        "query": {"type": "string", "description": "News search query"},
                        "max_results": {"type": "integer", "description": "Maximum results", "default": 5},
                        "time_range": {"type": "string", "enum": ["d", "w", "m"], "description": "Time range: d=day, w=week, m=month", "default": "w"},
                    },
                    "required": ["query"],
                },
            ),
            handler=self._tool_search_news,
            requires_empire_id=True,
        ))

        self.register(ToolRegistration(
            definition=ToolDefinition(
                name="search_ai_papers",
                description="Search for AI research papers on arXiv and academic sites.",
                parameters={
                    "type": "object",
                    "properties": {
                        "topic": {"type": "string", "description": "Research topic to search for"},
                        "max_results": {"type": "integer", "description": "Maximum results", "default": 5},
                    },
                    "required": ["topic"],
                },
            ),
            handler=self._tool_search_ai_papers,
            requires_empire_id=True,
        ))

        self.register(ToolRegistration(
            definition=ToolDefinition(
                name="read_url",
                description="Fetch and read the full content of a web page. Use this when you need the full article, not just a search snippet.",
                parameters={
                    "type": "object",
                    "properties": {
                        "url": {"type": "string", "description": "URL to read"},
                    },
                    "required": ["url"],
                },
            ),
            handler=self._tool_read_url,
            requires_empire_id=True,
        ))

        self.register(ToolRegistration(
            definition=ToolDefinition(
                name="search_hackernews",
                description="Search Hacker News for tech discussions, Show HN launches, and community insights. Best for early trend detection and technical debates.",
                parameters={
                    "type": "object",
                    "properties": {
                        "query": {"type": "string", "description": "Search query"},
                        "max_results": {"type": "integer", "description": "Maximum results (max 10)", "default": 5},
                        "sort": {
                            "type": "string",
                            "enum": ["relevance", "date"],
                            "description": "Sort by relevance or most recent (default: relevance)",
                            "default": "relevance",
                        },
                        "time_filter": {
                            "type": "string",
                            "enum": ["day", "week", "month", "year", "all"],
                            "description": "Time filter (default: year)",
                            "default": "year",
                        },
                    },
                    "required": ["query"],
                },
            ),
            handler=self._tool_search_hackernews,
            requires_empire_id=True,
        ))

        self.register(ToolRegistration(
            definition=ToolDefinition(
                name="search_papers",
                description="Search Semantic Scholar for academic papers with citation counts, influence scores, and abstracts. Better than web search for finding specific research.",
                parameters={
                    "type": "object",
                    "properties": {
                        "query": {"type": "string", "description": "Search query"},
                        "max_results": {"type": "integer", "description": "Maximum results (max 10)", "default": 5},
                        "year_filter": {
                            "type": "string",
                            "description": "Year range, e.g. '2024-2025' or '2023-' (optional)",
                            "default": "",
                        },
                    },
                    "required": ["query"],
                },
            ),
            handler=self._tool_search_papers,
            requires_empire_id=True,
        ))

        self.register(ToolRegistration(
            definition=ToolDefinition(
                name="search_papers_with_code",
                description="Search Papers With Code for papers that have GitHub implementations and SOTA benchmark results. Bridges theory to working code.",
                parameters={
                    "type": "object",
                    "properties": {
                        "query": {"type": "string", "description": "Search query"},
                        "max_results": {"type": "integer", "description": "Maximum results (max 10)", "default": 5},
                        "search_type": {
                            "type": "string",
                            "enum": ["papers", "methods", "tasks"],
                            "description": "Search papers, ML methods, or benchmark tasks (default: papers)",
                            "default": "papers",
                        },
                    },
                    "required": ["query"],
                },
            ),
            handler=self._tool_search_papers_with_code,
            requires_empire_id=True,
        ))

        self.register(ToolRegistration(
            definition=ToolDefinition(
                name="search_reddit",
                description="Search Reddit for discussions, opinions, and community insights. Great for finding real-world experiences, comparisons, and debates about AI topics.",
                parameters={
                    "type": "object",
                    "properties": {
                        "query": {"type": "string", "description": "Search query"},
                        "subreddit": {
                            "type": "string",
                            "description": "Limit to a subreddit (e.g. 'MachineLearning', 'LocalLLaMA'). Leave empty for all.",
                            "default": "",
                        },
                        "max_results": {"type": "integer", "description": "Maximum results (max 10)", "default": 5},
                        "sort": {
                            "type": "string",
                            "enum": ["relevance", "hot", "top", "new", "comments"],
                            "description": "Sort order (default: relevance)",
                            "default": "relevance",
                        },
                        "time_filter": {
                            "type": "string",
                            "enum": ["day", "week", "month", "year", "all"],
                            "description": "Time filter (default: year)",
                            "default": "year",
                        },
                    },
                    "required": ["query"],
                },
            ),
            handler=self._tool_search_reddit,
            requires_empire_id=True,
        ))

        self.register(ToolRegistration(
            definition=ToolDefinition(
                name="search_github",
                description="Search GitHub for repositories, code, or topics. Great for finding open-source projects, implementations, and trending repos.",
                parameters={
                    "type": "object",
                    "properties": {
                        "query": {"type": "string", "description": "Search query"},
                        "search_type": {
                            "type": "string",
                            "enum": ["repositories", "code", "topics"],
                            "description": "Type of search (default: repositories)",
                            "default": "repositories",
                        },
                        "max_results": {"type": "integer", "description": "Maximum results (max 10)", "default": 5},
                        "sort": {
                            "type": "string",
                            "enum": ["stars", "forks", "updated", "best-match"],
                            "description": "Sort order (default: best-match)",
                            "default": "best-match",
                        },
                    },
                    "required": ["query"],
                },
            ),
            handler=self._tool_search_github,
            requires_empire_id=True,
        ))

        self.register(ToolRegistration(
            definition=ToolDefinition(
                name="search_huggingface",
                description="Search HuggingFace for models, datasets, and spaces. Great for finding pre-trained models, benchmarks, and ML datasets.",
                parameters={
                    "type": "object",
                    "properties": {
                        "query": {"type": "string", "description": "Search query"},
                        "search_type": {
                            "type": "string",
                            "enum": ["models", "datasets", "spaces"],
                            "description": "Type of search (default: models)",
                            "default": "models",
                        },
                        "max_results": {"type": "integer", "description": "Maximum results (max 10)", "default": 5},
                        "sort": {
                            "type": "string",
                            "enum": ["downloads", "likes", "trending", "recent"],
                            "description": "Sort order (default: downloads)",
                            "default": "downloads",
                        },
                    },
                    "required": ["query"],
                },
            ),
            handler=self._tool_search_huggingface,
            requires_empire_id=True,
        ))

    def register(self, tool: ToolRegistration) -> None:
        """Register a tool."""
        self._tools[tool.definition.name] = tool

    def get_definitions(self) -> list[ToolDefinition]:
        """Get all tool definitions for LLM configuration."""
        return [t.definition for t in self._tools.values()]

    def execute(self, tool_name: str, arguments: dict) -> ToolResult:
        """Execute a tool by name.

        Args:
            tool_name: Name of the tool.
            arguments: Tool arguments.

        Returns:
            ToolResult.
        """
        tool = self._tools.get(tool_name)
        if not tool:
            return ToolResult(tool_name=tool_name, success=False, error=f"Unknown tool: {tool_name}")

        try:
            return tool.handler(arguments)
        except Exception as e:
            logger.error("Tool %s execution error: %s", tool_name, e)
            return ToolResult(tool_name=tool_name, success=False, error=str(e))

    def execute_tool_call(self, name: str, arguments: dict) -> str:
        """Execute a tool call and return string result (for LLM integration)."""
        result = self.execute(name, arguments)
        if result.success:
            return result.output or json.dumps(result.data)
        return f"Error: {result.error}"

    # ── Built-in tool handlers ─────────────────────────────────────────

    def _tool_recall_memory(self, args: dict) -> ToolResult:
        """Handler for recall_memory tool."""
        from core.memory.manager import MemoryManager
        mm = MemoryManager(self.empire_id)

        query = args.get("query", "")
        memory_type = args.get("memory_type")
        limit = args.get("limit", 5)

        memories = mm.recall(
            query=query,
            memory_types=[memory_type] if memory_type else None,
            lieutenant_id=self.lieutenant_id,
            limit=limit,
        )

        if not memories:
            return ToolResult(tool_name="recall_memory", output="No relevant memories found.")

        output_parts = []
        for m in memories:
            output_parts.append(f"[{m.get('type', '')}] {m.get('content', '')[:300]}")

        return ToolResult(
            tool_name="recall_memory",
            output="\n\n".join(output_parts),
            data={"count": len(memories), "memories": memories},
        )

    def _tool_lookup_knowledge(self, args: dict) -> ToolResult:
        """Handler for lookup_knowledge tool."""
        from core.knowledge.graph import KnowledgeGraph
        graph = KnowledgeGraph(self.empire_id)

        query = args.get("query", "")
        entity_type = args.get("entity_type", "")
        include_neighbors = args.get("include_neighbors", True)

        entities = graph.find_entities(query=query, entity_type=entity_type, limit=5)

        if not entities:
            return ToolResult(tool_name="lookup_knowledge", output="No matching knowledge entities found.")

        output_parts = []
        for e in entities:
            name = getattr(e, 'name', 'Unknown')
            etype = getattr(e, 'entity_type', '')
            desc = getattr(e, 'description', '') or ''
            part = f"**{name}** ({etype}): {desc[:200]}"
            if include_neighbors:
                neighbors = graph.get_neighbors(e.name, max_depth=1)
                if neighbors:
                    neighbor_names = [n.name for n in neighbors[:5]]
                    part += f"\n  Related: {', '.join(neighbor_names)}"
            output_parts.append(part)

        return ToolResult(
            tool_name="lookup_knowledge",
            output="\n\n".join(output_parts),
            data={"count": len(entities)},
        )

    def _tool_store_finding(self, args: dict) -> ToolResult:
        """Handler for store_finding tool."""
        content = args.get("content", "")
        importance = args.get("importance", 0.6)
        category = args.get("category", "finding")

        # Use BiTemporalMemory so new findings supersede outdated ones
        # instead of piling up and decaying to zero.
        from core.memory.bitemporal import BiTemporalMemory
        bt = BiTemporalMemory(self.empire_id)

        fact = bt.store_smart(
            content=content,
            title=f"Finding: {content[:80]}",
            category=category,
            importance=importance,
            tags=["finding", "tool_generated"],
            lieutenant_id=self.lieutenant_id,
        )

        return ToolResult(
            tool_name="store_finding",
            output=f"Finding stored successfully (importance: {importance})",
            data={"id": fact.id, "title": fact.title, "type": "semantic"},
        )

    def _tool_check_previous_work(self, args: dict) -> ToolResult:
        """Handler for check_previous_work tool."""
        from core.memory.manager import MemoryManager
        mm = MemoryManager(self.empire_id)

        description = args.get("description", "")
        episodes = mm.recall(
            query=description,
            memory_types=["episodic", "experiential"],
            lieutenant_id=self.lieutenant_id,
            limit=3,
        )

        if not episodes:
            return ToolResult(tool_name="check_previous_work", output="No similar previous work found.")

        output_parts = []
        for ep in episodes:
            output_parts.append(f"[{ep.get('type', '')}] {ep.get('content', '')[:300]}")

        return ToolResult(
            tool_name="check_previous_work",
            output="\n\n".join(output_parts),
            data={"count": len(episodes)},
        )

    def _tool_estimate_cost(self, args: dict) -> ToolResult:
        """Handler for estimate_cost tool."""
        from core.routing.pricing import PricingEngine
        engine = PricingEngine()

        estimate = engine.estimate_task_cost(
            task_type=args.get("task_type", "general"),
            complexity=args.get("complexity", "moderate"),
            input_text_length=args.get("input_length", 2000),
        )

        return ToolResult(
            tool_name="estimate_cost",
            output=f"Estimated cost: ${estimate.estimated_cost_usd:.4f} ({estimate.estimated_tokens_input + estimate.estimated_tokens_output} tokens)",
            data={
                "cost": estimate.estimated_cost_usd,
                "tokens_input": estimate.estimated_tokens_input,
                "tokens_output": estimate.estimated_tokens_output,
                "model": estimate.model,
            },
        )

    def _tool_get_best_practices(self, args: dict) -> ToolResult:
        """Handler for get_best_practices tool."""
        from core.memory.manager import MemoryManager
        mm = MemoryManager(self.empire_id)

        domain = args.get("domain", "")
        memories = mm.recall(
            query=f"best practice pattern {domain}",
            memory_types=["design", "experiential"],
            lieutenant_id=self.lieutenant_id,
            limit=5,
        )

        if not memories:
            return ToolResult(tool_name="get_best_practices", output="No best practices found for this domain.")

        output_parts = [m.get("content", "")[:300] for m in memories]
        return ToolResult(
            tool_name="get_best_practices",
            output="\n\n".join(f"- {p}" for p in output_parts),
            data={"count": len(memories)},
        )

    def _tool_web_search(self, args: dict) -> ToolResult:
        """Handler for web_search tool."""
        from core.search.web import WebSearcher
        searcher = WebSearcher(self.empire_id)

        query = args.get("query", "")
        max_results = args.get("max_results", 5)

        result = searcher.search_and_store(query, max_results=max_results)

        if not result.get("found"):
            return ToolResult(tool_name="web_search", output=f"No results found for: {query}")

        return ToolResult(
            tool_name="web_search",
            output=result.get("summary", ""),
            data={
                "result_count": result.get("result_count", 0),
                "stored_entities": result.get("stored_entities", 0),
                "stored_memories": result.get("stored_memories", 0),
            },
        )

    def _tool_search_news(self, args: dict) -> ToolResult:
        """Handler for search_news tool."""
        from core.search.web import WebSearcher
        searcher = WebSearcher(self.empire_id)

        query = args.get("query", "")
        max_results = args.get("max_results", 5)
        time_range = args.get("time_range", "w")

        response = searcher.search_news(query, max_results=max_results, time_range=time_range)

        if not response.results:
            return ToolResult(tool_name="search_news", output=f"No news found for: {query}")

        output_parts = []
        for r in response.results:
            output_parts.append(f"**{r.title}**\n{r.snippet}\n_Source: {r.source} | {r.published}_")

        return ToolResult(
            tool_name="search_news",
            output="\n\n".join(output_parts),
            data={"result_count": len(response.results)},
        )

    def _tool_search_ai_papers(self, args: dict) -> ToolResult:
        """Handler for search_ai_papers tool."""
        from core.search.web import WebSearcher
        searcher = WebSearcher(self.empire_id)

        topic = args.get("topic", "")
        max_results = args.get("max_results", 5)

        response = searcher.search_ai_papers(topic, max_results=max_results)

        if not response.results:
            return ToolResult(tool_name="search_ai_papers", output=f"No papers found for: {topic}")

        output_parts = []
        for r in response.results:
            output_parts.append(f"**{r.title}**\n{r.snippet}\n_URL: {r.url}_")

        return ToolResult(
            tool_name="search_ai_papers",
            output="\n\n".join(output_parts),
            data={"result_count": len(response.results)},
        )

    def _tool_read_url(self, args: dict) -> ToolResult:
        """Handler for read_url tool — scrapes full page content."""
        from core.search.scraper import WebScraper
        scraper = WebScraper(self.empire_id)

        url = args.get("url", "")
        if not url:
            return ToolResult(tool_name="read_url", success=False, error="URL required")

        page = scraper.scrape_url(url)

        if not page.success:
            return ToolResult(tool_name="read_url", success=False, output=f"Failed to read {url}: {page.error}")

        content = scraper.format_for_prompt(page, max_chars=6000)

        return ToolResult(
            tool_name="read_url",
            output=content,
            data={
                "title": page.title,
                "domain": page.domain,
                "word_count": page.word_count,
                "url": url,
            },
        )

    def _tool_search_hackernews(self, args: dict) -> ToolResult:
        """Handler for search_hackernews tool."""
        from core.search.hackernews import HackerNewsSearcher
        searcher = HackerNewsSearcher(self.empire_id)

        query = args.get("query", "")
        max_results = min(args.get("max_results", 5), 10)
        sort = args.get("sort", "relevance")
        time_filter = args.get("time_filter", "year")

        result = searcher.search(query, max_results=max_results, sort=sort, time_filter=time_filter)

        if not result.get("found"):
            return ToolResult(tool_name="search_hackernews", output=f"No HN results for: {query}")

        return ToolResult(
            tool_name="search_hackernews",
            output=result.get("summary", ""),
            data={
                "result_count": result.get("result_count", 0),
                "stored_entities": result.get("stored_entities", 0),
            },
        )

    def _tool_search_papers(self, args: dict) -> ToolResult:
        """Handler for search_papers tool — Semantic Scholar."""
        from core.search.semantic_scholar import SemanticScholarSearcher
        searcher = SemanticScholarSearcher(self.empire_id)

        query = args.get("query", "")
        max_results = min(args.get("max_results", 5), 10)
        year_filter = args.get("year_filter", "")

        result = searcher.search(query, max_results=max_results, year_filter=year_filter)

        if not result.get("found"):
            return ToolResult(tool_name="search_papers", output=f"No papers found for: {query}")

        return ToolResult(
            tool_name="search_papers",
            output=result.get("summary", ""),
            data={
                "result_count": result.get("result_count", 0),
                "stored_entities": result.get("stored_entities", 0),
            },
        )

    def _tool_search_papers_with_code(self, args: dict) -> ToolResult:
        """Handler for search_papers_with_code tool."""
        from core.search.papers_with_code import PapersWithCodeSearcher
        searcher = PapersWithCodeSearcher(self.empire_id)

        query = args.get("query", "")
        max_results = min(args.get("max_results", 5), 10)
        search_type = args.get("search_type", "papers")

        result = searcher.search(query, max_results=max_results, search_type=search_type)

        if not result.get("found"):
            return ToolResult(tool_name="search_papers_with_code", output=f"No PWC results for: {query}")

        return ToolResult(
            tool_name="search_papers_with_code",
            output=result.get("summary", ""),
            data={
                "result_count": result.get("result_count", 0),
                "stored_entities": result.get("stored_entities", 0),
            },
        )

    def _tool_search_reddit(self, args: dict) -> ToolResult:
        """Handler for search_reddit tool — searches Reddit posts and discussions."""
        from core.search.reddit import RedditSearcher
        searcher = RedditSearcher(self.empire_id)

        query = args.get("query", "")
        subreddit = args.get("subreddit", "")
        max_results = min(args.get("max_results", 5), 10)
        sort = args.get("sort", "relevance")
        time_filter = args.get("time_filter", "year")

        result = searcher.search(
            query, subreddit=subreddit, max_results=max_results,
            sort=sort, time_filter=time_filter,
        )

        if not result.get("found"):
            return ToolResult(tool_name="search_reddit", output=f"No Reddit results for: {query}")

        return ToolResult(
            tool_name="search_reddit",
            output=result.get("summary", ""),
            data={
                "result_count": result.get("result_count", 0),
                "stored_entities": result.get("stored_entities", 0),
            },
        )

    def _tool_search_github(self, args: dict) -> ToolResult:
        """Handler for search_github tool — searches GitHub repos, code, topics."""
        from core.search.github import GitHubSearcher
        searcher = GitHubSearcher(self.empire_id)

        query = args.get("query", "")
        search_type = args.get("search_type", "repositories")
        max_results = min(args.get("max_results", 5), 10)
        sort = args.get("sort", "best-match")

        result = searcher.search(query, search_type=search_type, max_results=max_results, sort=sort)

        if not result.get("found"):
            return ToolResult(tool_name="search_github", output=f"No GitHub results for: {query}")

        return ToolResult(
            tool_name="search_github",
            output=result.get("summary", ""),
            data={
                "result_count": result.get("result_count", 0),
                "stored_entities": result.get("stored_entities", 0),
            },
        )

    def _tool_search_huggingface(self, args: dict) -> ToolResult:
        """Handler for search_huggingface tool — searches HF models, datasets, spaces."""
        from core.search.huggingface import HuggingFaceSearcher
        searcher = HuggingFaceSearcher(self.empire_id)

        query = args.get("query", "")
        search_type = args.get("search_type", "models")
        max_results = min(args.get("max_results", 5), 10)
        sort = args.get("sort", "downloads")

        result = searcher.search(query, search_type=search_type, max_results=max_results, sort=sort)

        if not result.get("found"):
            return ToolResult(tool_name="search_huggingface", output=f"No HuggingFace results for: {query}")

        return ToolResult(
            tool_name="search_huggingface",
            output=result.get("summary", ""),
            data={
                "result_count": result.get("result_count", 0),
                "stored_entities": result.get("stored_entities", 0),
            },
        )
