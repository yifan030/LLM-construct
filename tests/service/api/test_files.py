# tests/service/api/test_files.py
from io import BytesIO
from unittest.mock import MagicMock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from service.api.files import router, get_db_session


def make_app():
    app = FastAPI()
    app.include_router(router, prefix="/api/v1")
    return TestClient(app)


def test_upload_endpoint():
    client = make_app()
    with patch("service.api.files.Scheduler") as MockScheduler, patch("service.api.files.OssClient") as MockOss:
        mock_scheduler = MagicMock()
        MockScheduler.return_value = mock_scheduler
        mock_oss = MagicMock()
        MockOss.return_value = mock_oss
        mock_session = MagicMock()
        added = []
        mock_session.add.side_effect = added.append
        client.app.dependency_overrides[get_db_session] = lambda: mock_session

        resp = client.post(
            "/api/v1/files/upload",
            files={"file": ("lecture.mp4", BytesIO(b"video data"), "video/mp4")},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["file_id"]
        assert data["status"] == "pending"

        record = added[0]
        assert record.file_name == "lecture.mp4"
        assert record.file_type == "video"
        assert record.file_size == len(b"video data")
        assert record.file_storage_path.endswith("/lecture.mp4")
        mock_oss.upload.assert_called_once()
        mock_scheduler.enqueue.assert_called_once_with(
            file_id=record.file_id, file_type="video", oss_path=record.file_storage_path
        )


def test_upload_sanitizes_path_traversal():
    client = make_app()
    with patch("service.api.files.Scheduler") as MockScheduler, patch("service.api.files.OssClient") as MockOss:
        mock_scheduler = MagicMock()
        MockScheduler.return_value = mock_scheduler
        mock_oss = MagicMock()
        MockOss.return_value = mock_oss
        mock_session = MagicMock()
        added = []
        mock_session.add.side_effect = added.append
        client.app.dependency_overrides[get_db_session] = lambda: mock_session

        resp = client.post(
            "/api/v1/files/upload",
            files={"file": ("../../etc/passwd", BytesIO(b"bad"), "video/mp4")},
        )
        assert resp.status_code == 200
        record = added[0]
        assert record.file_name == "passwd"
        assert record.file_storage_path.endswith("/passwd")


def test_upload_rejects_bad_filename():
    client = make_app()
    resp = client.post(
        "/api/v1/files/upload",
        files={"file": ("../", BytesIO(b"bad"), "video/mp4")},
    )
    assert resp.status_code == 400


def test_register_endpoint():
    client = make_app()
    with patch("service.api.files.Scheduler") as MockScheduler:
        mock_scheduler = MagicMock()
        MockScheduler.return_value = mock_scheduler
        mock_session = MagicMock()
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


def test_register_rejects_invalid_file_type():
    client = make_app()
    resp = client.post("/api/v1/files/register", json={
        "file_name": "x.doc",
        "file_type": "doc",
        "oss_path": "education/docs/x.doc",
    })
    assert resp.status_code == 422


def test_get_status():
    client = make_app()
    session = MagicMock()
    file_record = MagicMock()
    file_record.file_id = "f1"
    file_record.parse_status = 1
    file_record.parse_stage = "ocr"
    file_record.parse_progress = 75
    file_record.video_meta = None
    file_record.parsed_text_path = None
    session.query.return_value.filter_by.return_value.first.return_value = file_record
    client.app.dependency_overrides[get_db_session] = lambda: session

    resp = client.get("/api/v1/files/f1")
    assert resp.status_code == 200
    data = resp.json()
    assert data["parse_status"] == 1
    assert data["parse_stage"] == "ocr"
    assert data["parse_progress"] == 75
    assert data["failed_frames"] is None


def test_parse_endpoint_removed():
    client = make_app()
    resp = client.post("/api/v1/files/f1/parse")
    assert resp.status_code == 404
