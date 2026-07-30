import json
import uuid
from typing import Any, Dict, Optional

import redis

from libs.settings import Settings


class RedisClient:
    def __init__(self, settings: Optional[Settings] = None, setup: bool = True):
        cfg = (settings or Settings()).redis
        self.client = redis.Redis(host=cfg.host, port=cfg.port, db=cfg.db, decode_responses=True)
        self.queue_name = cfg.queue_name
        if setup:
            self.client.ping()

    def push_task(self, payload: Dict[str, Any]):
        self.client.lpush(self.queue_name, json.dumps(payload, ensure_ascii=False))

    def brpop(self, timeout: int = 5) -> Optional[str]:
        result = self.client.brpop(self.queue_name, timeout=timeout)
        if result is None:
            return None
        return result[1]

    def acquire_lock(self, lock_key: str, ttl: int = 60) -> bool:
        token = str(uuid.uuid4())
        acquired = self.client.set(lock_key, token, nx=True, ex=ttl)
        if acquired:
            self._local_token = token
        return bool(acquired)

    def release_lock(self, lock_key: str):
        token = getattr(self, "_local_token", None)
        if token and self.client.get(lock_key) == token:
            self.client.delete(lock_key)

    def clear_queue(self):
        self.client.delete(self.queue_name)
