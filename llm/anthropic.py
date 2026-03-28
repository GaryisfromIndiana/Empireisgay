"""Anthropic/Claude LLM client implementation."""

from __future__ import annotations

import logging
import time
from typing import Any, Generator

import anthropic

from llm.base import (
    LLMClient, LLMRequest, LLMResponse, LLMMessage,
    StreamChunk, ToolCall, ToolDefinition, estimate_tokens,
)

logger = logging.getLogger(__name__)


class AnthropicClient(LLMClient):
    """Client for the Anthropic Claude API.

    Supports completions, streaming, tool use, and automatic retries
    with exponential backoff on transient errors.
    """

    provider_name = "anthropic"

    def __init__(self, api_key: str | None = None):
        super().__init__()
        if api_key is None:
            from config.settings import get_settings
            api_key = get_settings().anthropic_api_key
        self.client = anthropic.Anthropic(api_key=api_key)
        self._default_model = "claude-sonnet-4-20250514"
        # Tighter rate limits to avoid 429s (shared across threads in this worker)
        from llm.base import RateLimiter
        self._rate_limiter = RateLimiter(requests_per_minute=30, tokens_per_minute=80_000)

    def complete(self, request: LLMRequest) -> LLMResponse:
        """Send a completion request to Claude.

        Args:
            request: The LLM request.

        Returns:
            LLM response with content, cost, and usage stats.
        """
        model = request.model or self._default_model
        messages = self._format_messages(request.messages)

        kwargs: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "max_tokens": request.max_tokens,
            "temperature": request.temperature,
        }

        if request.system_prompt:
            kwargs["system"] = request.system_prompt

        if request.has_tools:
            kwargs["tools"] = [self._format_tool(t) for t in request.tools]
            if request.tool_choice:
                if request.tool_choice == "auto":
                    kwargs["tool_choice"] = {"type": "auto"}
                elif request.tool_choice == "required":
                    kwargs["tool_choice"] = {"type": "any"}
                elif request.tool_choice == "none":
                    pass  # Don't send tool_choice
                else:
                    kwargs["tool_choice"] = {"type": "tool", "name": request.tool_choice}

        if request.stop_sequences:
            kwargs["stop_sequences"] = request.stop_sequences

        start_time = time.time()
        last_error = None

        # Rate limiter enforcement — wait if needed before making request
        estimated_tokens = sum(len(m.content) // 4 for m in request.messages) + request.max_tokens
        _rl_wait_total = 0.0
        _rl_wait_loops = 0
        while not self._rate_limiter.can_proceed(estimated_tokens):
            wait = self._rate_limiter.wait_time()
            if wait > 0:
                logger.debug("Rate limit backpressure: waiting %.1fs", wait)
                _sleep_for = min(wait, 5.0)
                _rl_wait_total += _sleep_for
                _rl_wait_loops += 1
                time.sleep(_sleep_for)
            else:
                break
        for attempt in range(5):
            try:
                response = self.client.messages.create(**kwargs)
                latency_ms = (time.time() - start_time) * 1000

                content = ""
                tool_calls = []

                for block in response.content:
                    if block.type == "text":
                        content += block.text
                    elif block.type == "tool_use":
                        tool_calls.append(ToolCall(
                            id=block.id,
                            name=block.name,
                            arguments=block.input if isinstance(block.input, dict) else {},
                        ))

                finish_reason = "stop"
                if response.stop_reason == "tool_use":
                    finish_reason = "tool_calls"
                elif response.stop_reason == "max_tokens":
                    finish_reason = "length"

                if response.usage:
                    tokens_in = response.usage.input_tokens
                    tokens_out = response.usage.output_tokens
                else:
                    tokens_in = 0
                    tokens_out = 0
                cost = self._calculate_cost(model, tokens_in, tokens_out)

                llm_response = LLMResponse(
                    content=content,
                    model=model,
                    provider="anthropic",
                    tokens_input=tokens_in,
                    tokens_output=tokens_out,
                    cost_usd=cost,
                    tool_calls=tool_calls,
                    finish_reason=finish_reason,
                    latency_ms=latency_ms,
                    raw_response=response,
                )
                self._record_usage(llm_response)
                return llm_response

            except anthropic.RateLimitError as e:
                last_error = e
                import random
                # Exponential backoff with jitter to avoid thundering herd
                base_wait = min(2 ** attempt * 5, 60)
                jitter = random.uniform(0, base_wait * 0.5)
                wait = base_wait + jitter
                logger.warning("Rate limited by Anthropic, waiting %.1fs (attempt %d)", wait, attempt + 1)
                time.sleep(wait)

            except anthropic.InternalServerError as e:
                last_error = e
                wait = min(2 ** attempt * 3, 60)
                logger.warning("Anthropic server error, waiting %ds (attempt %d)", wait, attempt + 1)
                time.sleep(wait)

            except anthropic.APIStatusError as e:
                self._errors += 1
                logger.error("Anthropic API error: %s", e)
                raise

            except Exception as e:
                self._errors += 1
                logger.error("Unexpected error calling Anthropic: %s", e)
                raise

        self._errors += 1
        raise last_error or RuntimeError("Failed after retries")

    def stream(self, request: LLMRequest) -> Generator[StreamChunk, None, None]:
        """Stream a completion response from Claude.

        Args:
            request: The LLM request.

        Yields:
            StreamChunk instances with content deltas.
        """
        model = request.model or self._default_model
        messages = self._format_messages(request.messages)

        kwargs: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "max_tokens": request.max_tokens,
            "temperature": request.temperature,
        }

        if request.system_prompt:
            kwargs["system"] = request.system_prompt

        if request.has_tools:
            kwargs["tools"] = [self._format_tool(t) for t in request.tools]

        try:
            with self.client.messages.stream(**kwargs) as stream:
                for event in stream:
                    if hasattr(event, "type"):
                        if event.type == "content_block_delta":
                            if hasattr(event.delta, "text"):
                                yield StreamChunk(content=event.delta.text)
                            elif hasattr(event.delta, "partial_json"):
                                yield StreamChunk(
                                    tool_call_delta={"partial_json": event.delta.partial_json}
                                )
                        elif event.type == "message_stop":
                            yield StreamChunk(is_final=True, finish_reason="stop")

                # Record usage from the final message
                final = stream.get_final_message()
                if final:
                    tokens_in = final.usage.input_tokens
                    tokens_out = final.usage.output_tokens
                    cost = self._calculate_cost(model, tokens_in, tokens_out)
                    self._record_usage(LLMResponse(
                        content="",
                        model=model,
                        provider="anthropic",
                        tokens_input=tokens_in,
                        tokens_output=tokens_out,
                        cost_usd=cost,
                    ))

        except Exception as e:
            self._errors += 1
            logger.error("Streaming error: %s", e)
            yield StreamChunk(is_final=True, finish_reason="error")

    def _format_messages(self, messages: list[LLMMessage]) -> list[dict]:
        """Format messages for the Anthropic API.

        Anthropic uses a different format: system prompt is separate,
        and tool results have a specific structure.
        """
        formatted = []

        for msg in messages:
            if msg.role == "system":
                continue  # System prompt handled separately

            if msg.role == "tool":
                formatted.append({
                    "role": "user",
                    "content": [{
                        "type": "tool_result",
                        "tool_use_id": msg.tool_call_id,
                        "content": msg.content,
                    }],
                })
            elif msg.role == "assistant" and msg.tool_calls:
                content_blocks: list[dict] = []
                if msg.content:
                    content_blocks.append({"type": "text", "text": msg.content})
                for tc in msg.tool_calls:
                    content_blocks.append({
                        "type": "tool_use",
                        "id": tc["id"],
                        "name": tc["name"],
                        "input": tc["arguments"],
                    })
                formatted.append({"role": "assistant", "content": content_blocks})
            else:
                formatted.append({"role": msg.role, "content": msg.content})

        return formatted

    def _format_tool(self, tool: ToolDefinition) -> dict:
        """Format a tool definition for the Anthropic API."""
        return tool.to_anthropic_schema()

    def count_tokens(self, text: str, model: str | None = None) -> int:
        """Estimate token count for text.

        Uses the Anthropic token counting API if available,
        falls back to heuristic estimation.
        """
        # Anthropic SDK 0.40+ removed client.count_tokens(); use heuristic
        return estimate_tokens(text)

    def count_message_tokens(
        self,
        messages: list[LLMMessage],
        system_prompt: str = "",
        model: str | None = None,
    ) -> int:
        """Estimate total tokens for a message sequence."""
        total = estimate_tokens(system_prompt) if system_prompt else 0
        for msg in messages:
            total += estimate_tokens(msg.content) + 4
        return total
