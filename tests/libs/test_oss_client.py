# tests/libs/test_oss_client.py
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

from libs.oss_client import OssClient
from libs.settings import Settings


def test_oss_client_auto_creates_bucket():
    with patch("libs.oss_client.Minio") as MockMinio:
        mock_client = MagicMock()
        mock_client.bucket_exists.return_value = False
        MockMinio.return_value = mock_client

        OssClient(Settings(), setup=True)

        mock_client.bucket_exists.assert_called_once_with("llm-construct")
        mock_client.make_bucket.assert_called_once_with("llm-construct")


def test_oss_roundtrip():
    client = OssClient(Settings())
    with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
        f.write("hello oss")
        local_path = f.name

    oss_path = "test/hello.txt"
    client.upload(local_path, oss_path)

    with tempfile.TemporaryDirectory() as tmp:
        downloaded = client.download(oss_path, tmp)
        assert Path(downloaded).read_text() == "hello oss"

    url = client.presigned_url(oss_path)
    assert url.startswith("http")
