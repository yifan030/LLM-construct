from libs.db import SessionLocal
from libs.redis_client import RedisClient
from libs.settings import Settings
from service.worker.parse_worker import ParseTask, ParseWorker


class ParseInProgressError(RuntimeError):
    """Raised when a parse is already running for the same file."""


class Scheduler:
    def __init__(
        self,
        settings: Settings,
        redis_client: RedisClient = None,
        worker: ParseWorker = None,
    ):
        self.settings = settings
        self.redis = redis_client or RedisClient(settings)
        self.worker = worker

    def enqueue(
        self,
        file_id: str,
        file_type: str,
        oss_path: str,
        force: bool = False,
    ):
        task = ParseTask(file_id=file_id, file_type=file_type, oss_path=oss_path, force=force)
        self.redis.push_task(task.model_dump())

    def direct_parse(self, file_id: str, file_type: str, oss_path: str, force: bool = False):
        if self.worker is None:
            raise RuntimeError("worker not configured for direct parse")
        task = ParseTask(file_id=file_id, file_type=file_type, oss_path=oss_path, force=force)
        lock_key = f"lock:parse:{file_id}"
        if not self.redis.acquire_lock(lock_key, ttl=600):
            raise ParseInProgressError(file_id)
        try:
            with SessionLocal() as session:
                self.worker.parse(task, session=session)
        finally:
            self.redis.release_lock(lock_key)
