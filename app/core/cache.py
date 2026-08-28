"""
Redis cache layer.

Provides a CacheBackend abstraction so callers are insulated from Redis details
and can transparently fall back to a no-op NullCache when Redis is unavailable.

Usage:
    from app.core.cache import create_cache, CacheBackend

    # In lifespan:
    cache = await create_cache(settings.redis_url)
    music_service.set_cache(cache)
    yield
    await cache.close()
"""

import json
import logging
from abc import ABC, abstractmethod
from typing import Any, Optional

import redis.asyncio as aioredis

logger = logging.getLogger(__name__)

# Key namespace — prefix for every cache entry
_NS = "dj"


def make_key(*parts: Any) -> str:
    """Build a namespaced Redis key: dj:<part1>:<part2>:..."""
    return f"{_NS}:" + ":".join(str(p) for p in parts)


# ---------------------------------------------------------------------------
# Abstract interface
# ---------------------------------------------------------------------------


class CacheBackend(ABC):
    """
    Minimal cache contract.  Swap RedisCache for another backend (Memcached,
    in-memory) without touching any caller.
    """

    @abstractmethod
    async def get(self, key: str) -> Optional[Any]:
        """Return the deserialised value, or None on miss / error."""

    @abstractmethod
    async def set(self, key: str, value: Any, ttl: int) -> None:
        """Serialise and store value with the given TTL in seconds."""

    @abstractmethod
    async def delete(self, key: str) -> None:
        """Remove a key (best-effort, never raises)."""

    @abstractmethod
    async def close(self) -> None:
        """Release underlying resources."""


# ---------------------------------------------------------------------------
# Redis implementation
# ---------------------------------------------------------------------------


class RedisCache(CacheBackend):
    """Production Redis-backed cache using redis.asyncio."""

    def __init__(self, url: str) -> None:
        self._url = url
        self._client: Optional[aioredis.Redis] = None

    async def connect(self) -> None:
        self._client = aioredis.from_url(
            self._url,
            encoding="utf-8",
            decode_responses=True,
            socket_connect_timeout=3,
            socket_timeout=2,
            retry_on_timeout=False,
        )
        await self._client.ping()
        logger.info("Redis connected: %s", self._url)

    async def get(self, key: str) -> Optional[Any]:
        try:
            raw = await self._client.get(key)  # type: ignore[union-attr]
            if raw is None:
                return None
            return json.loads(raw)
        except Exception as exc:
            logger.warning("Redis GET failed [%s]: %s", key, exc)
            return None

    async def set(self, key: str, value: Any, ttl: int) -> None:
        try:
            await self._client.setex(key, ttl, json.dumps(value))  # type: ignore[union-attr]
        except Exception as exc:
            logger.warning("Redis SET failed [%s]: %s", key, exc)

    async def delete(self, key: str) -> None:
        try:
            await self._client.delete(key)  # type: ignore[union-attr]
        except Exception as exc:
            logger.warning("Redis DEL failed [%s]: %s", key, exc)

    async def close(self) -> None:
        if self._client:
            await self._client.aclose()
            logger.info("Redis connection closed")


# ---------------------------------------------------------------------------
# No-op fallback — always a cache miss, never raises
# ---------------------------------------------------------------------------


class NullCache(CacheBackend):
    """
    Null Object — used when Redis is unavailable.
    All calls are silent no-ops so callers need zero guard clauses.
    """

    async def get(self, key: str) -> Optional[Any]:
        return None

    async def set(self, key: str, value: Any, ttl: int) -> None:
        pass

    async def delete(self, key: str) -> None:
        pass

    async def close(self) -> None:
        pass


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------


async def create_cache(url: str) -> CacheBackend:
    """
    Try to connect to Redis at *url*.
    Returns RedisCache on success, NullCache on any connection failure.
    Callers never need to check which one they received.
    """
    try:
        cache = RedisCache(url)
        await cache.connect()
        return cache
    except Exception as exc:
        logger.error(
            "Redis unavailable (%s) — falling back to NullCache (no caching)", exc
        )
        return NullCache()
