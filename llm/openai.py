"""OpenAI LLM client implementation."""

from __future__ import annotations

import json
import logging
import time
from typing import Any, Generator

import openai

from llm.base import (
    LLMClient, LLMRequest, LLMResponse, LLMMessage,
    StreamChunk, ToolCall, ToolDefinition, estimate_tokens,
)

logger = logging.getLogger(__name__)


class OpenAIClient(LLMClient):
    """Client for the OpenAI API.

    Supports completions, streaming, function/tool calling, JSON mode,
    and automatic retries with exponential backoff.
    """

    provider_name = "openai"

    def __init__(self, api_key: str | None = None):
        super().__init__()
        if api_key is None:
            from config.settings import get_settings
            api_key = get_settings().openai_api_key
        self.client = openai.OpenAI(api_key=api_key)
        self._default_model = "gpt-4o"

    def complete(self, request: LLMRequest) -> LLMResponse:
        """Send a completion request to OpenAI.

        Args:
            request: The LLM request.

        Returns:
            LLM response with content, cost, and usage stats.
        """
        model = request.model or self._default_model
        messages = self._format_messages(request.messages, request.system_prompt)

        kwargs: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "max_tokens": request.max_tokens,
            "temperature": request.temperature,
            "top_p": request.top_p,
        }

        if request.has_tools:
            kwargs["tools"] = [self._format_tool(t) for t in request.tools]
            if request.tool_choice:
                if request.tool_choice in ("auto", "none", "required"):
                    kwargs["tool_choice"] = request.tool_choice
                else:
                    kwargs["tool_choice"] = {
                        "type": "function",
                        "function": {"name": request.tool_choice},
                    }

        if request.response_format == "json":
            kwargs["response_format"] = {"type": "json_object"}

        if request.stop_sequences:
            kwargs["stop"] = request.stop_sequences

        start_time = time.time()
        last_error = None

        # Rate limiter enforcement — wait if needed before making request
        estimated_tokens = sum(len(m.get("content", "")) // 4 for m in messages) + request.max_tokens
        while not self._rate_limiter.can_proceed(estimated_tokens):
            wait = self._rate_limiter.wait_time()
            if wait > 0:
                logger.debug("Rate limit backpressure: waiting %.1fs", wait)
                time.sleep(min(wait, 5.0))
            else:
                break

        for attempt in range(3):
            try:
                response = self.client.chat.completions.create(**kwargs)
                latency_ms = (time.time() - start_time) * 1000

                choice = response.choices[0]
                content = choice.message.content or ""
                tool_calls = []

                if choice.message.tool_calls:
                    for tc in choice.message.tool_calls:
                        try:
                            args = json.loads(tc.function.arguments)
                        except json.JSONDecodeError:
                            args = {"raw": tc.function.arguments}
                        tool_calls.append(ToolCall(
                            id=tc.id,
                            name=tc.function.name,
                            arguments=args,
                        ))

                finish_reason = choice.finish_reason or "stop"
                if finish_reason == "tool_calls":
                    finish_reason = "tool_calls"

                tokens_in = response.usage.prompt_tokens if response.usage else 0
                tokens_out = response.usage.completion_tokens if response.usage else 0
                cost = self._calculate_cost(model, tokens_in, tokens_out)

                llm_response = LLMResponse(
                    content=content,
                    model=model,
                    provider="openai",
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

            except openai.RateLimitError as e:
                last_error = e
                wait = min(2 ** attempt * 2, 30)
                logger.warning("Rate limited by OpenAI, waiting %ds (attempt %d)", wait, attempt + 1)
                time.sleep(wait)

            except openai.InternalServerError as e:
                last_error = e
                wait = min(2 ** attempt * 3, 60)
                logger.warning("OpenAI server error, waiting %ds (attempt %d)", wait, attempt + 1)
                time.sleep(wait)

            except openai.APIStatusError as e:
                self._errors += 1
                logger.error("OpenAI API error: %s", e)
                raise

            except Exception as e:
                self._errors += 1
                logger.error("Unexpected error calling OpenAI: %s", e)
                raise

        self._errors += 1
        raise last_error or RuntimeError("Failed after retries")

    def stream(self, request: LLMRequest) -> Generator[StreamChunk, None, None]:
        """Stream a completion response from OpenAI.

        Args:
            request: The LLM request.

        Yields:
            StreamChunk instances with content deltas.
        """
        model = request.model or self._default_model
        messages = self._format_messages(request.messages, request.system_prompt)

        kwargs: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "max_tokens": request.max_tokens,
            "temperature": request.temperature,
            "stream": True,
            "stream_options": {"include_usage": True},
        }

        if request.has_tools:
            kwargs["tools"] = [self._format_tool(t) for t in request.tools]

        try:
            stream = self.client.chat.completions.create(**kwargs)
            total_content = ""

            for chunk in stream:
                if not chunk.choices:
                    # Usage chunk at the end
                    if chunk.usage:
                        tokens_in = chunk.usage.prompt_tokens
                        tokens_out = chunk.usage.completion_tokens
                        cost = self._calculate_cost(model, tokens_in, tokens_out)
                        self._record_usage(LLMResponse(
                            content=total_content,
                            model=model,
                            provider="openai",
                            tokens_input=tokens_in,
                            tokens_output=tokens_out,
                            cost_usd=cost,
                        ))
                    continue

                delta = chunk.choices[0].delta
                finish = chunk.choices[0].finish_reason

                if delta and delta.content:
                    total_content += delta.content
                    yield StreamChunk(content=delta.content)

                if delta and delta.tool_calls:
                    for tc_delta in delta.tool_calls:
                        yield StreamChunk(tool_call_delta={
                            "index": tc_delta.index,
                            "id": tc_delta.id,
                            "name": tc_delta.function.name if tc_delta.function else None,
                            "arguments": tc_delta.function.arguments if tc_delta.function else None,
                        })

                if finish:
                    yield StreamChunk(is_final=True, finish_reason=finish)

        except Exception as e:
            self._errors += 1
            logger.error("OpenAI streaming error: %s", e)
            yield StreamChunk(is_final=True, finish_reason="error")

    def _format_messages(
        self,
        messages: list[LLMMessage],
        system_prompt: str = "",
    ) -> list[dict]:
        """Format messages for the OpenAI API."""
        formatted = []

        if system_prompt:
            formatted.append({"role": "system", "content": system_prompt})

        for msg in messages:
            if msg.role == "system":
                formatted.append({"role": "system", "content": msg.content})
            elif msg.role == "tool":
                formatted.append({
                    "role": "tool",
                    "tool_call_id": msg.tool_call_id,
                    "content": msg.content,
                })
            elif msg.role == "assistant" and msg.tool_calls:
                tool_calls_formatted = []
                for tc in msg.tool_calls:
                    tool_calls_formatted.append({
                        "id": tc["id"],
                        "type": "function",
                        "function": {
                            "name": tc["name"],
                            "arguments": json.dumps(tc["arguments"]),
                        },
                    })
                entry: dict[str, Any] = {
                    "role": "assistant",
                    "tool_calls": tool_calls_formatted,
                }
                if msg.content:
                    entry["content"] = msg.content
                formatted.append(entry)
            else:
                formatted.append({"role": msg.role, "content": msg.content})

        return formatted

    def _format_tool(self, tool: ToolDefinition) -> dict:
        """Format a tool definition for the OpenAI API."""
        return tool.to_openai_schema()

    def count_tokens(self, text: str, model: str | None = None) -> int:
        """Estimate token count using character-based heuristic."""
        return estimate_tokens(text)

    def create_embedding(
        self,
        text: str,
        model: str = "text-embedding-3-small",
    ) -> list[float]:
        """Create an embedding vector for text.

        Args:
            text: Text to embed.
            model: Embedding model.

        Returns:
            Embedding vector.
        """
        try:
            response = self.client.embeddings.create(
                input=text,
                model=model,
            )
            return response.data[0].embedding
        except Exception as e:
            logger.error("Embedding error: %s", e)
            raise

    def create_embeddings_batch(
        self,
        texts: list[str],
        model: str = "text-embedding-3-small",
    ) -> list[list[float]]:
        """Create embeddings for multiple texts.

        Args:
            texts: List of texts to embed.
            model: Embedding model.

        Returns:
            List of embedding vectors.
        """
        try:
            response = self.client.embeddings.create(
                input=texts,
                model=model,
            )
            return [item.embedding for item in sorted(response.data, key=lambda x: x.index)]
        except Exception as e:
            logger.error("Batch embedding error: %s", e)
            raise
