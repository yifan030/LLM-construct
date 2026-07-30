import json
from unittest.mock import MagicMock, patch

from libs.redis_client import RedisClient
from libs.settings import Settings


def test_redis_client_pings_on_init():
    with patch("libs.redis_client.redis.Redis") as MockRedis:
        mock_client = MagicMock()
        MockRedis.return_value = mock_client

        RedisClient(Settings(), setup=True)

        mock_client.ping.assert_called_once()


def test_redis_client_setup_false_does_not_ping():
    with patch("libs.redis_client.redis.Redis") as MockRedis:
        mock_client = MagicMock()
        MockRedis.return_value = mock_client

        RedisClient(Settings(), setup=False)

        mock_client.ping.assert_not_called()


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
