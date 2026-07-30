from pathlib import Path
from unittest.mock import patch, MagicMock

from service.ocr.factory import create_ocr_adapter
from service.ocr.base import OcrAdapter
from libs.settings import Settings


def test_factory_returns_adapter():
    adapter = create_ocr_adapter(Settings())
    assert isinstance(adapter, OcrAdapter)


def test_paddle_cloud_parse_image(tmp_path: Path):
    adapter = create_ocr_adapter(Settings())
    img = tmp_path / "frame.jpg"
    img.write_bytes(b"fake image")

    with patch.object(adapter, "_call_api", return_value="markdown text") as mock_call:
        result = adapter.parse_image(str(img))
        assert result == "markdown text"
        mock_call.assert_called_once()


def test_paddle_cloud_parse_pdf(tmp_path: Path):
    adapter = create_ocr_adapter(Settings())
    pdf = tmp_path / "doc.pdf"
    pdf.write_bytes(b"fake pdf")

    with patch.object(adapter, "_call_api", return_value="pdf markdown") as mock_call:
        result = adapter.parse_pdf(str(pdf))
        assert result == "pdf markdown"
