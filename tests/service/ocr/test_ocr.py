from pathlib import Path
from unittest.mock import MagicMock

from service.ocr.factory import create_ocr_adapter
from service.ocr.base import OcrAdapter
from service.ocr.paddle_cloud import PaddleCloudAdapter
from libs.settings import Settings


def test_factory_returns_adapter():
    adapter = create_ocr_adapter(Settings())
    assert isinstance(adapter, OcrAdapter)


def test_paddle_cloud_parse_image(tmp_path: Path):
    cfg = Settings().ocr.paddle_cloud
    fake_response = MagicMock()
    fake_response.raise_for_status.return_value = None
    fake_response.json.return_value = {"result": "markdown text"}
    fake_client = MagicMock()
    fake_client.post.return_value = fake_response

    adapter = PaddleCloudAdapter(cfg, client=fake_client)
    img = tmp_path / "frame.jpg"
    img.write_bytes(b"fake image")

    result = adapter.parse_image(str(img))
    assert result == "markdown text"
    fake_client.post.assert_called_once()


def test_paddle_cloud_parse_pdf(tmp_path: Path):
    cfg = Settings().ocr.paddle_cloud
    fake_response = MagicMock()
    fake_response.raise_for_status.return_value = None
    fake_response.json.return_value = {"result": "pdf markdown"}
    fake_client = MagicMock()
    fake_client.post.return_value = fake_response

    adapter = PaddleCloudAdapter(cfg, client=fake_client)
    pdf = tmp_path / "doc.pdf"
    pdf.write_bytes(b"fake pdf")

    result = adapter.parse_pdf(str(pdf))
    assert result == "pdf markdown"
    fake_client.post.assert_called_once()


def test_paddle_cloud_handles_null_result():
    cfg = Settings().ocr.paddle_cloud
    fake_response = MagicMock()
    fake_response.raise_for_status.return_value = None
    fake_response.json.return_value = {"result": None}
    fake_client = MagicMock()
    fake_client.post.return_value = fake_response

    adapter = PaddleCloudAdapter(cfg, client=fake_client)
    result = adapter._call_api({"model": cfg.model, "image": "abc"})
    assert result == ""
