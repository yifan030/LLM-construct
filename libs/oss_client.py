# libs/oss_client.py
from datetime import timedelta
from pathlib import Path
from typing import Optional
from urllib.parse import urlparse

from minio import Minio
from minio.error import S3Error

from libs.settings import Settings


class OssClient:
    def __init__(self, settings: Optional[Settings] = None):
        cfg = (settings or Settings()).oss
        parsed = urlparse(cfg.endpoint)
        self.bucket = cfg.bucket_name
        self.client = Minio(
            f"{parsed.hostname}:{parsed.port}" if parsed.port else parsed.hostname,
            access_key=cfg.access_key,
            secret_key=cfg.secret_key,
            secure=parsed.scheme == "https",
        )

    def ensure_bucket(self):
        if not self.client.bucket_exists(self.bucket):
            self.client.make_bucket(self.bucket)

    def upload(self, local_path: str, oss_path: str):
        self.ensure_bucket()
        self.client.fput_object(self.bucket, oss_path, local_path)

    def download(self, oss_path: str, local_dir: str) -> str:
        self.ensure_bucket()
        target = Path(local_dir) / Path(oss_path).name
        self.client.fget_object(self.bucket, oss_path, str(target))
        return str(target)

    def presigned_url(self, oss_path: str, expires: int = 3600) -> str:
        return self.client.presigned_get_object(
            self.bucket, oss_path, expires=timedelta(seconds=expires)
        )

    def object_exists(self, oss_path: str) -> bool:
        try:
            self.client.stat_object(self.bucket, oss_path)
            return True
        except S3Error as e:
            if e.code == "NoSuchKey":
                return False
            raise
