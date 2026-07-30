from unittest.mock import MagicMock, patch

from service.worker.scheduler import Scheduler
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
    scheduler = Scheduler(settings=Settings(), worker=worker)
    with patch("service.worker.scheduler.SessionLocal") as mock_session_cls:
        session = MagicMock()
        mock_session_cls.return_value.__enter__.return_value = session
        scheduler.direct_parse(file_id="f1", file_type="video", oss_path="education/video/x.mp4")
        worker.parse.assert_called_once()
