# libs/settings.py
from functools import lru_cache
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic_settings.sources import YamlConfigSettingsSource


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
    job_url: str = "https://paddleocr.aistudio-app.com/api/v2/ocr/jobs"
    token: str = ""
    model: str = "PaddleOCR-VL-1.6"
    # PaddleOCR cloud API optional payload switches (see docs/superpowers/specs/...)
    use_doc_orientation_classify: bool = False
    use_doc_unwarping: bool = False
    use_chart_recognition: bool = False


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
        yaml_file="conf/config.yaml",
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

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls,
        init_settings,
        env_settings,
        dotenv_settings,
        file_secret_settings,
    ):
        # 优先级：init / env / .env / secrets 覆盖 YAML 默认值
        return (
            init_settings,
            env_settings,
            dotenv_settings,
            file_secret_settings,
            YamlConfigSettingsSource(settings_cls),
        )


@lru_cache
def get_settings() -> Settings:
    return Settings()
