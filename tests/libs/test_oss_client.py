# tests/libs/test_oss_client.py
import tempfile
from pathlib import Path

from libs.oss_client import OssClient
from libs.settings import Settings


def test_oss_roundtrip():
    client = OssClient(Settings())
    client.ensure_bucket()
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
