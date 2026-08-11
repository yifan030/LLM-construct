# libs/oss_client.py
import json
from datetime import timedelta
from pathlib import Path
from typing import Optional
from urllib.parse import urlparse

from minio import Minio
from minio.error import S3Error

from libs.settings import Settings

_PUBLIC_READ_POLICY_TEMPLATE = """
{{
  "Version": "2012-10-17",
  "Statement": [
    {{
      "Effect": "Allow",
      "Principal": {{"AWS": ["*"]}},
      "Action": ["s3:GetObject"],
      "Resource": ["arn:aws:s3:::{bucket}/*"]
    }}
  ]
}}
"""


class OssClient:
    def __init__(self, settings: Optional[Settings] = None, setup: bool = True):
        cfg = (settings or Settings()).oss
        parsed = urlparse(cfg.endpoint)
        self.bucket = cfg.bucket_name
        self.client = Minio(
            f"{parsed.hostname}:{parsed.port}" if parsed.port else parsed.hostname,
            access_key=cfg.access_key,
            secret_key=cfg.secret_key,
            secure=parsed.scheme == "https",
        )
        # 外网 presigned URL 专用 client（签名中包含 Host 头，不能用字符串替换）
        self._external_endpoint = cfg.external_endpoint
        self._url_style = cfg.url_style
        if cfg.external_endpoint:
            parsed_ext = urlparse(cfg.external_endpoint)
            self._presign_client: Optional[Minio] = Minio(
                f"{parsed_ext.hostname}:{parsed_ext.port}"
                if parsed_ext.port
                else parsed_ext.hostname,
                access_key=cfg.access_key,
                secret_key=cfg.secret_key,
                secure=parsed_ext.scheme == "https",
                region="us-east-1",  # 避免 _get_region 发网络请求
            )
        else:
            self._presign_client = None

        if setup:
            self.ensure_bucket()
            if self._url_style == "public" and self._external_endpoint:
                self.ensure_public_bucket()

    def ensure_bucket(self):
        if not self.client.bucket_exists(self.bucket):
            self.client.make_bucket(self.bucket)

    def ensure_public_bucket(self):
        """设置 bucket 为公开读（用于永久直链）。"""
        policy = _PUBLIC_READ_POLICY_TEMPLATE.format(bucket=self.bucket)
        self.client.set_bucket_policy(self.bucket, policy)

    def upload(self, local_path: str, oss_path: str):
        self.ensure_bucket()
        self.client.fput_object(self.bucket, oss_path, local_path)

    def download(self, oss_path: str, local_dir: str) -> str:
        self.ensure_bucket()
        target = Path(local_dir) / Path(oss_path).name
        self.client.fget_object(self.bucket, oss_path, str(target))
        return str(target)

    def public_url(self, oss_path: str) -> str:
        """返回永久公开直链（需 bucket 设置为公开读）。"""
        base = self._external_endpoint or f"http://127.0.0.1:9000"
        return f"{base.rstrip('/')}/{self.bucket}/{oss_path}"

    def presigned_url(self, oss_path: str, expires: int = 3600) -> str:
        """生成对象访问 URL。

        url_style="public" 时返回永久直链（无过期时间），
        否则返回预签名 URL（默认有效期 1 小时，最长 7 天）。
        """
        if self._url_style == "public" and self._external_endpoint:
            return self.public_url(oss_path)
        client = self._presign_client or self.client
        return client.presigned_get_object(
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
