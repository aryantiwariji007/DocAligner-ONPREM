import json
import hashlib
from typing import Any, Optional
import redis.asyncio as redis
from backend.app.core.config import settings

class CacheService:
    def __init__(self):
        self.redis = redis.from_url(settings.REDIS_URL, decode_responses=True)
        self.default_ttl = 60 * 60 * 24 * 7  # 1 week

    def _hash_key(self, prefix: str, data: str) -> str:
        h = hashlib.sha256(data.encode('utf-8')).hexdigest()
        return f"{prefix}:{h}"

    async def get_cached_result(self, key: str) -> Optional[Any]:
        try:
            val = await self.redis.get(key)
            if val:
                return json.loads(val)
        except Exception as e:
            msg = str(e).lower()
            if "event loop is closed" in msg or "loop is closed" in msg:
                 # Recreate client on next attempt
                 self.redis = redis.from_url(settings.REDIS_URL, decode_responses=True)
            print(f"Redis get error: {e}")
        return None

    async def set_cached_result(self, key: str, value: Any, ttl: int = None):
        try:
            await self.redis.set(key, json.dumps(value), ex=ttl or self.default_ttl)
        except Exception as e:
            msg = str(e).lower()
            if "event loop is closed" in msg or "loop is closed" in msg:
                 self.redis = redis.from_url(settings.REDIS_URL, decode_responses=True)
            print(f"Redis set error: {e}")

    async def get_doc_fingerprint_cache(self, file_content: bytes, standard_id: str) -> Optional[dict]:
        h = hashlib.sha256(file_content).hexdigest()
        key = f"doc_validation:{standard_id}:{h}"
        return await self.get_cached_result(key)

    async def set_doc_fingerprint_cache(self, file_content: bytes, standard_id: str, report: dict):
        h = hashlib.sha256(file_content).hexdigest()
        key = f"doc_validation:{standard_id}:{h}"
        await self.set_cached_result(key, report)

cache_service = CacheService()
