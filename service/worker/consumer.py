import json
import logging
import threading
import time
from typing import Optional

from libs.redis_client import RedisClient
from libs.settings import Settings
from service.worker.parse_worker import ParseTask, ParseWorker
from libs.db import SessionLocal

logger = logging.getLogger(__name__)


class Consumer:
    def __init__(
        self,
        settings: Settings,
        redis_client: RedisClient = None,
        worker: ParseWorker = None,
    ):
        self.settings = settings
        self.redis = redis_client or RedisClient(settings)
        self.worker = worker
        self._thread: Optional[threading.Thread] = None
        self._running = False

    def start(self):
        if self._thread and self._thread.is_alive():
            return
        self._running = True
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()
        logger.info("consumer started")

    def stop(self):
        self._running = False
        if self._thread:
            self._thread.join(timeout=5)

    def _loop(self):
        while self._running:
            try:
                self._process_once()
            except Exception as e:
                logger.exception("consumer error: %s", e)
                time.sleep(1)

    def _process_once(self):
        raw = self.redis.brpop(timeout=5)
        if raw is None:
            return
        task = ParseTask.model_validate_json(raw)
        lock_key = f"lock:parse:{task.file_id}"
        if not self.redis.acquire_lock(lock_key, ttl=600):
            logger.warning("task already processing: %s", task.file_id)
            return
        try:
            with SessionLocal() as session:
                self.worker.parse(task, session=session)
        finally:
            self.redis.release_lock(lock_key)
