"""Abstract base LLM client with common interfaces and utilities."""

from __future__ import annotations

import logging
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Generator, Optional

logger = logging.getLogger(__name__)


@dataclass
class LLMMessage:
    """A single message in a conversation."""
    role: str  # system, user, assistant, tool
    content: str
    name: Optional[str] = None
    tool_call_id: Optional[str] = None
    tool_calls: Optional[list[dict]] = None
    metadata: Optional[dict] = None

    @staticmethod
    def system(content: str) -> LLMMessage:
        return LLMMessage(role="system", content=content)

    @staticmethod
    def user(content: str) -> LLMMessage:
        return LLMMessage(role="user", content=content)

    @staticmethod
    def assistant(content: str, tool_calls: list[dict] | None = None) -> LLMMessage:
        return LLMMessage(role="assistant", content=content, tool_calls=tool_calls)

    @staticmethod
    def tool_result(tool_call_id: str, content: str, name: str = "") -> LLMMessage:
        return LLMMessage(role="tool", content=content, tool_call_id=tool_call_id, name=name)

    def to_dict(self) -> dict:
        d: dict[str, Any] = {"role": self.role, "content": self.content}
        if self.name:
            d["name"] = self.name
        if self.tool_call_id:
            d["tool_call_id"] = self.tool_call_id
        if self.tool_calls:
            d["tool_calls"] = self.tool_calls
        return d


@dataclass
class ToolDefinition:
    """Definition of a tool/function that the LLM can call."""
    name: str
    description: str
    parameters: dict  # JSON Schema
    required: list[str] = field(default_factory=list)

    def to_openai_schema(self) -> dict:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            },
        }

    def to_anthropic_schema(self) -> dict:
        return {
            "name": self.name,
            "description": self.description,
            "input_schema": self.parameters,
        }


@dataclass
class ToolCall:
    """A tool call from the LLM."""
    id: str
    name: str
    arguments: dict
    raw: Optional[dict] = None


@dataclass
class LLMRequest:
    """A request to an LLM provider."""
    messages: list[LLMMessage]
    model: str = ""
    system_prompt: str = ""
    temperature: float = 0.7
    max_tokens: int = 4096
    top_p: float = 1.0
    stop_sequences: list[str] = field(default_factory=list)
    tools: list[ToolDefinition] = field(default_factory=list)
    tool_choice: Optional[str] = None  # auto, none, required, or specific tool name
    response_format: Optional[str] = None  # json, text
    metadata: dict = field(default_factory=dict)

    @property
    def has_tools(self) -> bool:
        return len(self.tools) > 0


@dataclass
class LLMResponse:
    """Response from an LLM provider."""
    content: str
    model: str
    provider: str
    tokens_input: int = 0
    tokens_output: int = 0
    cost_usd: float = 0.0
    tool_calls: list[ToolCall] = field(default_factory=list)
    tool_log: list[dict] = field(default_factory=list)  # [{tool, args, result, chars}] from complete_with_tools
    finish_reason: str = "stop"  # stop, tool_calls, length, error
    latency_ms: float = 0.0
    raw_response: Optional[Any] = None

    @property
    def has_tool_calls(self) -> bool:
        return len(self.tool_calls) > 0

    @property
    def total_tokens(self) -> int:
        return self.tokens_input + self.tokens_output

    def to_dict(self) -> dict:
        return {
            "content": self.content,
            "model": self.model,
            "provider": self.provider,
            "tokens_input": self.tokens_input,
            "tokens_output": self.tokens_output,
            "cost_usd": self.cost_usd,
            "tool_calls": [
                {"id": tc.id, "name": tc.name, "arguments": tc.arguments}
                for tc in self.tool_calls
            ],
            "finish_reason": self.finish_reason,
            "latency_ms": self.latency_ms,
        }


@dataclass
class StreamChunk:
    """A single chunk from a streaming response."""
    content: str = ""
    tool_call_delta: Optional[dict] = None
    finish_reason: Optional[str] = None
    is_final: bool = False


class RateLimiter:
    """Token bucket rate limiter for API calls."""

    def __init__(
        self,
        requests_per_minute: int = 60,
        tokens_per_minute: int = 100_000,
    ):
        self.rpm_limit = requests_per_minute
        self.tpm_limit = tokens_per_minute
        self._request_timestamps: list[float] = []
        self._token_counts: list[tuple[float, int]] = []

    def can_proceed(self, estimated_tokens: int = 0) -> bool:
        """Check if a request can proceed without hitting rate limits."""
        now = time.time()
        minute_ago = now - 60.0

        # Clean old entries
        self._request_timestamps = [t for t in self._request_timestamps if t > minute_ago]
        self._token_counts = [(t, c) for t, c in self._token_counts if t > minute_ago]

        # Check RPM
        if len(self._request_timestamps) >= self.rpm_limit:
            return False

        # Check TPM
        current_tokens = sum(c for _, c in self._token_counts)
        if current_tokens + estimated_tokens > self.tpm_limit:
            return False

        return True

    def record_request(self, tokens_used: int = 0) -> None:
        """Record a completed request."""
        now = time.time()
        self._request_timestamps.append(now)
        if tokens_used > 0:
            self._token_counts.append((now, tokens_used))

    def wait_time(self) -> float:
        """Get seconds to wait before next request."""
        if not self._request_timestamps:
            return 0.0
        oldest = min(self._request_timestamps)
        wait = 60.0 - (time.time() - oldest)
        return max(0.0, wait)


def estimate_tokens(text: str) -> int:
    """Estimate token count from text length.

    Rough heuristic: ~4 characters per token for English text.
    """
    return max(1, len(text) // 4)


def estimate_message_tokens(messages: list[LLMMessage]) -> int:
    """Estimate total tokens for a message list."""
    total = 0
    for msg in messages:
        total += estimate_tokens(msg.content)
        total += 4  # Message overhead
    return total


class LLMClient(ABC):
    """Abstract base class for LLM providers."""

    provider_name: str = "base"

    def __init__(self):
        self._rate_limiter = RateLimiter()
        self._total_requests = 0
        self._total_tokens = 0
        self._total_cost = 0.0
        self._errors = 0

    @abstractmethod
    def complete(self, request: LLMRequest) -> LLMResponse:
        """Send a completion request and return the response.

        Args:
            request: The LLM request.

        Returns:
            LLM response.
        """
        ...

    @abstractmethod
    def stream(self, request: LLMRequest) -> Generator[StreamChunk, None, None]:
        """Stream a completion response.

        Args:
            request: The LLM request.

        Yields:
            Stream chunks.
        """
        ...

    def complete_with_tools(
        self,
        request: LLMRequest,
        tool_executor: Any = None,
        max_rounds: int = 5,
    ) -> LLMResponse:
        """Complete with automatic tool execution loop.

        Args:
            request: The request with tools defined.
            tool_executor: Callable that executes tool calls.
            max_rounds: Maximum tool-use rounds.

        Returns:
            Final LLM response after all tool calls.
        """
        messages = list(request.messages)
        final_response = None
        tool_rounds = 0
        tool_log: list[dict] = []

        for round_num in range(max_rounds):
            req = LLMRequest(
                messages=messages,
                model=request.model,
                system_prompt=request.system_prompt,
                temperature=request.temperature,
                max_tokens=request.max_tokens,
                tools=request.tools,
                tool_choice=request.tool_choice,
                metadata=request.metadata,
            )
            response = self.complete(req)
            final_response = response

            logger.info(
                "Tool loop round %d/%d: has_tool_calls=%s, content_len=%d, finish=%s, tools=%s",
                round_num + 1, max_rounds,
                response.has_tool_calls,
                len(response.content),
                response.finish_reason,
                [tc.name for tc in response.tool_calls] if response.tool_calls else [],
            )

            if not response.has_tool_calls or tool_executor is None:
                break

            tool_rounds += 1

            # Add assistant message with tool calls
            messages.append(LLMMessage.assistant(
                response.content,
                tool_calls=[
                    {"id": tc.id, "name": tc.name, "arguments": tc.arguments}
                    for tc in response.tool_calls
                ],
            ))

            # Execute tools and add results
            for tc in response.tool_calls:
                try:
                    result = tool_executor(tc.name, tc.arguments)
                    result_str = str(result)
                    logger.info("Tool %s returned %d chars", tc.name, len(result_str))
                    messages.append(LLMMessage.tool_result(tc.id, result_str, tc.name))
                    tool_log.append({
                        "tool": tc.name,
                        "args": tc.arguments,
                        "result": result_str[:2000],
                        "chars": len(result_str),
                    })
                except Exception as e:
                    logger.error("Tool %s error: %s", tc.name, e)
                    messages.append(LLMMessage.tool_result(tc.id, f"Error: {e}", tc.name))
                    tool_log.append({
                        "tool": tc.name,
                        "args": tc.arguments,
                        "result": f"Error: {e}",
                        "chars": 0,
                    })

        # After multiple tool rounds, the LLM's "final" response may be a
        # brief or incomplete answer rather than a true synthesis.  Force a
        # dedicated synthesis call whenever more than one tool round ran —
        # not only when the loop hit max_rounds with pending tool calls.
        needs_synthesis = (
            final_response is not None
            and tool_rounds > 1
        )
        if needs_synthesis or (final_response and final_response.has_tool_calls):
            reason = (
                "pending tool calls"
                if final_response and final_response.has_tool_calls
                else f"{tool_rounds} tool rounds"
            )
            logger.info(
                "Tool loop ended (%s) — requesting final summary (messages=%d)",
                reason, len(messages),
            )
            try:
                # Append the last assistant text so the LLM sees its own
                # most-recent answer in context before synthesizing.
                if final_response and not final_response.has_tool_calls and final_response.content:
                    messages.append(LLMMessage.assistant(final_response.content))

                messages.append(LLMMessage.user(
                    "Now synthesize all the information gathered from the tool calls above "
                    "into a comprehensive, well-structured response. Do not attempt to call "
                    "any more tools — just write the final answer.\n\n"
                    "IMPORTANT: Include inline source citations for key claims, e.g. "
                    "(Source: HuggingFace) or (Source: GitHub). End with a ## Sources section "
                    "listing all sources used."
                ))
                final_req = LLMRequest(
                    messages=messages,
                    model=request.model,
                    system_prompt=request.system_prompt,
                    temperature=request.temperature,
                    max_tokens=request.max_tokens,
                )
                summary_response = self.complete(final_req)
                logger.info(
                    "Final summary: content_len=%d, finish=%s",
                    len(summary_response.content), summary_response.finish_reason,
                )
                if summary_response.content:
                    final_response = summary_response
            except Exception as e:
                logger.error("Final summary call failed: %s", e)

        if final_response:
            final_response.tool_log = tool_log
        return final_response or LLMResponse(content="", model=request.model, provider=self.provider_name)

    def _record_usage(self, response: LLMResponse) -> None:
        """Record usage statistics."""
        self._total_requests += 1
        self._total_tokens += response.total_tokens
        self._total_cost += response.cost_usd
        self._rate_limiter.record_request(response.total_tokens)

    def _calculate_cost(self, model: str, tokens_in: int, tokens_out: int) -> float:
        """Calculate cost for a request."""
        from config.settings import MODEL_CATALOG
        for key, config in MODEL_CATALOG.items():
            if config.model_id == model or key == model:
                return (
                    tokens_in * config.cost_per_1k_input / 1000
                    + tokens_out * config.cost_per_1k_output / 1000
                )
        return 0.0

    def get_stats(self) -> dict:
        """Get client usage statistics."""
        return {
            "provider": self.provider_name,
            "total_requests": self._total_requests,
            "total_tokens": self._total_tokens,
            "total_cost_usd": self._total_cost,
            "errors": self._errors,
        }
