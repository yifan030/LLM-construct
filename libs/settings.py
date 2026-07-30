# libs/settings.py
from functools import lru_cache
from pathlib import Path
from typing import Literal, Optional

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict
import yaml


class ServerSettings(BaseSettings):
    host: str = "0.0.0.0"
    port: int = 8000


class DatabaseSettings(BaseSettings):
    url: str = "mysql+pymysql://root:root@localhost:3306/llm_construct?charset=utf8mb4"


class RedisSettings(BaseSettings):
    host: str = "localhost"
    port: int = 6379
    db: int = 0
    queue_name: str = "edu_construct_parse_queue"


class OssSettings(BaseSettings):
    endpoint: str = "http://localhost:9000"
    access_key: str = "minioadmin"
    secret_key: str = "minioadmin"
    bucket_name: str = "llm-construct"


class PaddleCloudSettings(BaseSettings):
    base_url: str = ""
    api_key: str = ""
    job_url: str = ""
    token: str = ""
    model: str = "PaddleOCR-VL-1.6"


class PaddleVlLocalSettings(BaseSettings):
    server_url: str = ""
    device: str = "gpu:0"


class OcrSettings(BaseSettings):
    provider: Literal["paddle-cloud", "paddle-vl-local"] = "paddle-cloud"
    paddle_cloud: PaddleCloudSettings = Field(default_factory=PaddleCloudSettings)
    paddle_vl_local: PaddleVlLocalSettings = Field(default_factory=PaddleVlLocalSettings)


class FfmpegSettings(BaseSettings):
    path: str = "ffmpeg"
    frame_rate: int = 1
    output_format: str = "jpg"
    quality: int = 2


class VideoSettings(BaseSettings):
    dedup_mode: Literal["scene", "hash", "none"] = "scene"
    scene_threshold: float = 0.05


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file="conf/.env",
        env_file_encoding="utf-8",
        env_nested_delimiter="__",
        extra="ignore",
    )

    server: ServerSettings = Field(default_factory=ServerSettings)
    database: DatabaseSettings = Field(default_factory=DatabaseSettings)
    redis: RedisSettings = Field(default_factory=RedisSettings)
    oss: OssSettings = Field(default_factory=OssSettings)
    ocr: OcrSettings = Field(default_factory=OcrSettings)
    ffmpeg: FfmpegSettings = Field(default_factory=FfmpegSettings)
    video: VideoSettings = Field(default_factory=VideoSettings)

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        config_path = Path("conf/config.yaml")
        if config_path.exists():
            data = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
            for key, value in data.items():
                if hasattr(self, key):
                    setattr(self, key, self.__pydantic_fields__[key].annotation(**value))


@lru_cache
def get_settings() -> Settings:
    return Settings()
