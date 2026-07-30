import json
import threading
import time
from unittest.mock import MagicMock, patch

from service.worker.consumer import Consumer
from libs.settings import Settings


def test_consumer_processes_one_task():
    redis_client = MagicMock()
    redis_client.brpop.side_effect = [
        json.dumps({"file_id": "f1", "file_type": "video", "oss_path": "x.mp4"}),
        None,
    ]
    redis_client.acquire_lock.return_value = True
    worker = MagicMock()

    consumer = Consumer(settings=Settings(), redis_client=redis_client, worker=worker)
    consumer._running = True
    consumer._process_once()
    worker.parse.assert_called_once()
    redis_client.release_lock.assert_called_once()
