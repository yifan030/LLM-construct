from unittest.mock import MagicMock, patch

import pytest

from service.worker.scheduler import ParseInProgressError, Scheduler
from service.worker.parse_worker import ParseTask
from libs.settings import Settings


def test_scheduler_enqueue():
    redis_client = MagicMock()
    scheduler = Scheduler(settings=Settings(), redis_client=redis_client)
    scheduler.enqueue(file_id="f1", file_type="video", oss_path="education/video/x.mp4")
    redis_client.push_task.assert_called_once()
    task = ParseTask.model_validate(redis_client.push_task.call_args[0][0])
    assert task.file_id == "f1"


def test_scheduler_direct_parse():
    worker = MagicMock()
    redis_client = MagicMock()
    redis_client.acquire_lock.return_value = True
    scheduler = Scheduler(settings=Settings(), redis_client=redis_client, worker=worker)
    with patch("service.worker.scheduler.SessionLocal") as mock_session_cls:
        session = MagicMock()
        mock_session_cls.return_value.__enter__.return_value = session
        scheduler.direct_parse(file_id="f1", file_type="video", oss_path="education/video/x.mp4")
        worker.parse.assert_called_once()
        redis_client.acquire_lock.assert_called_once_with("lock:parse:f1", ttl=600)
        redis_client.release_lock.assert_called_once_with("lock:parse:f1")


def test_scheduler_direct_parse_raises_when_locked():
    worker = MagicMock()
    redis_client = MagicMock()
    redis_client.acquire_lock.return_value = False
    scheduler = Scheduler(settings=Settings(), redis_client=redis_client, worker=worker)
    with pytest.raises(ParseInProgressError):
        scheduler.direct_parse(file_id="f1", file_type="video", oss_path="education/video/x.mp4")
    worker.parse.assert_not_called()
    redis_client.release_lock.assert_not_called()
