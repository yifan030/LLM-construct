from unittest.mock import MagicMock, patch

import pytest

from libs.settings import Settings
from service.ocr.paddle_vl_local import PaddleVlLocalAdapter


def _make_result(text: str):
    res = MagicMock()
    res.markdown = {"text": text}
    return res


def _make_config():
    cfg = Settings().ocr.paddle_vl_local
    cfg.server_url = "http://localhost:8128/v1"
    return cfg


@patch("service.ocr.paddle_vl_local.PaddleOCRVL")
def test_parse_image_returns_concatenated_markdown(mock_cls):
    pipeline = MagicMock()
    pipeline.predict.return_value = [_make_result("line 1"), _make_result("line 2")]
    mock_cls.return_value = pipeline

    adapter = PaddleVlLocalAdapter(_make_config())
    result = adapter.parse_image("/tmp/frame.jpg")

    assert result == "line 1\n\nline 2"
    pipeline.predict.assert_called_once_with("/tmp/frame.jpg")


@patch("service.ocr.paddle_vl_local.PaddleOCRVL")
def test_parse_pdf_uses_concatenate_markdown_pages(mock_cls):
    pipeline = MagicMock()
    pipeline.predict.return_value = [_make_result("page 1"), _make_result("page 2")]
    pipeline.concatenate_markdown_pages.return_value = "merged markdown"
    mock_cls.return_value = pipeline

    adapter = PaddleVlLocalAdapter(_make_config())
    result = adapter.parse_pdf("/tmp/doc.pdf")

    assert result == "merged markdown"
    pipeline.predict.assert_called_once_with("/tmp/doc.pdf")
    pipeline.concatenate_markdown_pages.assert_called_once()


@patch("service.ocr.paddle_vl_local.PaddleOCRVL")
def test_parse_image_empty_result_returns_empty_string(mock_cls):
    pipeline = MagicMock()
    pipeline.predict.return_value = []
    mock_cls.return_value = pipeline

    adapter = PaddleVlLocalAdapter(_make_config())
    assert adapter.parse_image("/tmp/frame.jpg") == ""


@patch("service.ocr.paddle_vl_local.PaddleOCRVL")
def test_parse_image_wraps_sdk_error(mock_cls):
    pipeline = MagicMock()
    pipeline.predict.side_effect = RuntimeError("server down")
    mock_cls.return_value = pipeline

    adapter = PaddleVlLocalAdapter(_make_config())
    with pytest.raises(RuntimeError, match="PaddleVlLocal OCR failed"):
        adapter.parse_image("/tmp/frame.jpg")


@patch("service.ocr.paddle_vl_local.PaddleOCRVL")
def test_parse_pdf_falls_back_when_concatenate_unavailable(mock_cls):
    pipeline = MagicMock()
    pipeline.predict.return_value = [_make_result("page 1"), _make_result("page 2")]
    del pipeline.concatenate_markdown_pages
    mock_cls.return_value = pipeline

    adapter = PaddleVlLocalAdapter(_make_config())
    result = adapter.parse_pdf("/tmp/doc.pdf")

    assert result == "page 1\n\npage 2"
