import json

from libs.redis_client import RedisClient
from libs.settings import Settings


def test_push_and_brpop():
    client = RedisClient(Settings())
    client.clear_queue()
    client.push_task({"file_id": "f1", "file_type": "video"})
    item = client.brpop(timeout=2)
    assert item is not None
    assert json.loads(item)["file_id"] == "f1"


def test_lock():
    client = RedisClient(Settings())
    assert client.acquire_lock("lock:test", ttl=10) is True
    assert client.acquire_lock("lock:test", ttl=10) is False
    client.release_lock("lock:test")
    assert client.acquire_lock("lock:test", ttl=10) is True
    client.release_lock("lock:test")
