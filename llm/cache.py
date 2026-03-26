"""LLM Response Caching -- Redis-backed cache for LLM responses."""

from __future__ import annotations

import hashlib
import json
import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

logger = logging.getLogger(__name__)


@dataclass
class CacheEntry:
    """A cached LLM response."""
    cache_key: str
    model: str
    prompt_hash: str
    content: str
    tokens_input: int = 0
    tokens_output: int = 0
    cost_usd: float = 0.0
    created_at: str = ""
    hit_count: int = 0
    ttl_seconds: int = 86400

    def is_expired(self) -> bool:
        if not self.created_at:
            return True
        try:
            created = datetime.fromisoformat(self.created_at.replace("Z", "+00:00"))
            age = (datetime.now(timezone.utc) - created).total_seconds()
            return age > self.ttl_seconds
        except (ValueError, TypeError):
            return True

    def to_dict(self) -> dict:
        return {
            "cache_key": self.cache_key,
            "model": self.model,
            "prompt_hash": self.prompt_hash,
            "content": self.content,
            "tokens_input": self.tokens_input,
            "tokens_output": self.tokens_output,
            "cost_usd": self.cost_usd,
            "created_at": self.created_at,
            "hit_count": self.hit_count,
            "ttl_seconds": self.ttl_seconds,
        }

    @classmethod
    def from_dict(cls, data: dict) -> CacheEntry:
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})


class LLMCache:
    """Redis-backed LLM response cache.

    Caches LLM responses keyed by model + prompt hash to avoid
    redundant API calls. Gracefully degrades if Redis is unavailable.
    """

    def __init__(self, redis_url: str = "redis://localhost:6379/0", enabled: bool = True):
        self.enabled = enabled
        self._redis = None
        self._redis_url = redis_url
        self._hits = 0
        self._misses = 0
        self._saves = 0
        if enabled:
            self._connect()

    def _connect(self) -> None:
        try:
            import redis
            self._redis = redis.from_url(self._redis_url, decode_responses=True, socket_timeout=2.0)
            self._redis.ping()
            logger.info("LLM cache connected to Redis")
        except ImportError:
            logger.warning("Redis not installed -- LLM cache disabled. Install with: pip install redis")
            self.enabled = False
        except Exception as e:
            logger.warning("Redis connection failed -- LLM cache disabled: %s", e)
            self.enabled = False

    def _cache_key(self, model: str, prompt: str, system_prompt: str = "") -> str:
        content = f"{model}:{system_prompt}:{prompt}"
        prompt_hash = hashlib.sha256(content.encode()).hexdigest()[:16]
        return f"llm:cache:{model}:{prompt_hash}"

    def get(self, model: str, prompt: str, system_prompt: str = "") -> Optional[CacheEntry]:
        if not self.enabled or not self._redis:
            self._misses += 1
            return None

        cache_key = self._cache_key(model, prompt, system_prompt)
        try:
            data = self._redis.get(cache_key)
            if data:
                entry = CacheEntry.from_dict(json.loads(data))
                if not entry.is_expired():
                    entry.hit_count += 1
                    self._redis.set(cache_key, json.dumps(entry.to_dict()), ex=entry.ttl_seconds)
                    self._hits += 1
                    return entry
                else:
                    self._redis.delete(cache_key)
            self._misses += 1
        except Exception as e:
            logger.warning("Cache get failed: %s", e)
            self._misses += 1
        return None

    def set(
        self,
        model: str,
        prompt: str,
        content: str,
        system_prompt: str = "",
        tokens_input: int = 0,
        tokens_output: int = 0,
        cost_usd: float = 0.0,
        ttl_seconds: int = 86400,
    ) -> bool:
        if not self.enabled or not self._redis:
            return False

        cache_key = self._cache_key(model, prompt, system_prompt)
        entry = CacheEntry(
            cache_key=cache_key,
            model=model,
            prompt_hash=cache_key.split(":")[-1],
            content=content,
            tokens_input=tokens_input,
            tokens_output=tokens_output,
            cost_usd=cost_usd,
            created_at=datetime.now(timezone.utc).isoformat(),
            ttl_seconds=ttl_seconds,
        )
        try:
            self._redis.set(cache_key, json.dumps(entry.to_dict()), ex=ttl_seconds)
            self._saves += 1
            return True
        except Exception as e:
            logger.warning("Cache set failed: %s", e)
            return False

    def invalidate(self, model: str, prompt: str, system_prompt: str = "") -> bool:
        """Remove a specific entry from the cache."""
        if not self.enabled or not self._redis:
            return False
        cache_key = self._cache_key(model, prompt, system_prompt)
        try:
            return bool(self._redis.delete(cache_key))
        except Exception:
            return False

    def clear(self) -> int:
        """Clear all LLM cache entries. Returns number of keys deleted."""
        if not self.enabled or not self._redis:
            return 0
        try:
            keys = self._redis.keys("llm:cache:*")
            if keys:
                return self._redis.delete(*keys)
            return 0
        except Exception as e:
            logger.warning("Cache clear failed: %s", e)
            return 0

    def get_stats(self) -> dict:
        total = self._hits + self._misses
        return {
            "enabled": self.enabled,
            "hits": self._hits,
            "misses": self._misses,
            "saves": self._saves,
            "hit_rate": self._hits / total if total > 0 else 0.0,
            "estimated_savings_usd": self._hits * 0.005,
        }


# Module-level singleton
_cache: Optional[LLMCache] = None


def get_cache(redis_url: str = "redis://localhost:6379/0", enabled: bool = True) -> LLMCache:
    global _cache
    if _cache is None:
        _cache = LLMCache(redis_url=redis_url, enabled=enabled)
    return _cache


def cache_llm_response(
    model: str,
    prompt: str,
    content: str,
    system_prompt: str = "",
    tokens_input: int = 0,
    tokens_output: int = 0,
    cost_usd: float = 0.0,
    ttl_seconds: int = 86400,
) -> bool:
    return get_cache().set(
        model=model,
        prompt=prompt,
        content=content,
        system_prompt=system_prompt,
        tokens_input=tokens_input,
        tokens_output=tokens_output,
        cost_usd=cost_usd,
        ttl_seconds=ttl_seconds,
    )


def get_cached_response(model: str, prompt: str, system_prompt: str = "") -> Optional[CacheEntry]:
    return get_cache().get(model, prompt, system_prompt)
