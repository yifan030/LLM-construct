# tests/service/api/test_files.py
from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient

from service.api.files import router, get_db_session
from fastapi import FastAPI


def make_app():
    app = FastAPI()
    app.include_router(router, prefix="/api/v1")
    return TestClient(app)


def test_register_endpoint():
    client = make_app()
    with patch("service.api.files.Scheduler") as MockScheduler, \
         patch("service.api.files.get_db_session") as mock_db:
        mock_scheduler = MagicMock()
        MockScheduler.return_value = mock_scheduler
        mock_session = MagicMock()
        mock_db.return_value = iter([mock_session])
        client.app.dependency_overrides[get_db_session] = lambda: mock_session

        resp = client.post("/api/v1/files/register", json={
            "file_name": "x.mp4",
            "file_type": "video",
            "oss_path": "education/video/2024/x.mp4",
            "file_size": 1024,
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["file_id"]
        assert data["status"] == "pending"
        mock_scheduler.enqueue.assert_called_once()


def test_get_status():
    client = make_app()
    with patch("service.api.files.get_db_session") as mock_db:
        session = MagicMock()
        mock_db.return_value = iter([session])
        file_record = MagicMock()
        file_record.file_id = "f1"
        file_record.parse_status = 0
        file_record.parsed_text_path = None
        session.query.return_value.filter_by.return_value.first.return_value = file_record
        client.app.dependency_overrides[get_db_session] = lambda: session

        resp = client.get("/api/v1/files/f1")
        assert resp.status_code == 200
        assert resp.json()["parse_status"] == 0
