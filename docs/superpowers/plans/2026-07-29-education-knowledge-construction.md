# 教育场景知识构建模块实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 实现数据接入与内容解析服务，支持视频（ts/mp4）和 PDF 上传/注册、OSS 存储、MySQL 元数据管理、Redis 异步解析队列、OCR 文本抽取，为后续题型知识图谱构建提供清洗后的 `.md` 内容。

**Architecture:** 基于 FastAPI 的 HTTP 服务层只负责接收文件/OSS 路径、写 MySQL、推队列、状态查询和同步解析入口；所有实际解析流程（下载 → 抽帧/OCR → 整合 → 上传 md）交给 `ParseWorker`，默认由 Redis Consumer 线程异步消费，也支持 HTTP 直接调用；OSS、Redis、MySQL、OCR、视频抽帧均通过接口抽象，便于切换实现与单测 mock。

**Tech Stack:** Python 3.10, FastAPI, SQLAlchemy 2.x, Pydantic Settings, Redis, MinIO (S3 API), ffmpeg, PaddleOCR Cloud API, pytest, TestClient.

## Global Constraints

- Python >= 3.10
- 所有实现写在 `reference/` 之外；`reference/` 目录下的代码仅作逻辑参考，不能直接引用
- OCR 当前使用云端 paddle API；本地 paddle-vl 通过配置切换，本次只实现接口和云端适配器
- Word 上传暂不实现，预留扩展点
- 直接上传接口默认原始路径：`education/uploads/{file_id}/{filename}`
- 解析后目录约定：`<原始目录>/<主名(无扩展名)>_parsed/`
- 解析状态：`0` 待解析、`1` 解析中、`2` 完成、`3` 失败
- 临时文件统一使用 `tempfile.TemporaryDirectory`，`finally` 中清理
- 所有外部依赖通过构造函数/依赖注入传入，禁止在业务代码中直接实例化全局客户端

---

## File Structure

```
llm-construct-question/
├── bin/
│   ├── start.sh                 # 启动 FastAPI + Consumer
│   └── stop.sh                  # 停止服务
├── conf/
│   ├── config.yaml              # 业务配置
│   └── .env                     # 环境变量/密钥
├── core/
│   └── models/
│       ├── __init__.py
│       ├── base.py              # SQLAlchemy Base + 通用字段
│       ├── edu_construct_files.py
│       └── edu_video_meta.py
├── libs/
│   ├── __init__.py
│   ├── settings.py              # Pydantic Settings 配置加载
│   ├── db.py                    # SQLAlchemy engine/session
│   ├── oss_client.py            # MinIO/S3 封装
│   └── redis_client.py          # Redis 队列 + 分布式锁
├── service/
│   ├── main.py                  # FastAPI lifespan + consumer 启动
│   ├── api/
│   │   ├── __init__.py
│   │   └── files.py             # 上传/注册/状态/解析/下载接口
│   ├── worker/
│   │   ├── __init__.py
│   │   ├── scheduler.py         # 入队 + 同步调用入口
│   │   ├── consumer.py          # 后台消费线程
│   │   └── parse_worker.py      # 解析编排
│   ├── handler/
│   │   ├── __init__.py
│   │   ├── base.py              # FileHandler 抽象
│   │   ├── video_handler.py     # ffmpeg 抽帧
│   │   └── pdf_handler.py       # PDF 转图
│   └── ocr/
│       ├── __init__.py
│       ├── base.py              # OcrAdapter 抽象
│       ├── factory.py           # 根据配置构造 OCR 适配器
│       ├── paddle_cloud.py      # 云端 paddle API
│       └── paddle_vl_local.py   # 本地 paddle-vl 占位
├── tests/
│   ├── conftest.py              # fixtures: settings/db/redis/oss
│   ├── libs/
│   ├── core/
│   ├── service/
│   └── integration/
├── Dockerfile
├── requirements.txt
└── docker-compose.yml           # 已存在，按需补充 app 服务
```

---

### Task 1: 项目初始化与配置加载

**Files:**
- Create: `requirements.txt`
- Create: `conf/config.yaml`
- Create: `libs/settings.py`
- Modify: `conf/.env`（追加非敏感默认配置说明，不提交真实密钥）
- Test: `tests/libs/test_settings.py`

**Interfaces:**
- Consumes: 无
- Produces: `libs.settings.Settings` 单例，通过 `get_settings()` 获取；支持从 `conf/config.yaml` 与 `.env` 加载

- [ ] **Step 1: Write the failing test**

```python
# tests/libs/test_settings.py
from libs.settings import get_settings, Settings

def test_settings_loads_config():
    s = get_settings()
    assert s.server.port == 8000
    assert s.redis.queue_name == "edu_construct_parse_queue"
    assert s.ocr.provider == "paddle-cloud"

def test_settings_env_override():
    s = Settings(_env_file="conf/.env")
    assert s.database.url is not None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/libs/test_settings.py -v`

Expected: FAIL with `ModuleNotFoundError: libs.settings`

- [ ] **Step 3: Write minimal implementation**

```python
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
```

```yaml
# conf/config.yaml
server:
  host: 0.0.0.0
  port: 8000

database:
  url: mysql+pymysql://root:root@localhost:3306/llm_construct?charset=utf8mb4

redis:
  host: localhost
  port: 6379
  db: 0
  queue_name: edu_construct_parse_queue

oss:
  endpoint: http://localhost:9000
  access_key: minioadmin
  secret_key: minioadmin
  bucket_name: llm-construct

ocr:
  provider: paddle-cloud
  paddle_cloud:
    base_url: ""
    api_key: ""
    job_url: "https://paddleocr.aistudio-app.com/api/v2/ocr/jobs"
    token: ""
    model: "PaddleOCR-VL-1.6"
  paddle_vl_local:
    server_url: ""
    device: "gpu:0"

ffmpeg:
  path: ffmpeg
  frame_rate: 1
  output_format: jpg
  quality: 2

video:
  dedup_mode: scene
  scene_threshold: 0.05
```

```txt
# requirements.txt（追加/新建，按已有依赖合并）
fastapi>=0.110.0
uvicorn[standard]>=0.27.0
pydantic>=2.6.0
pydantic-settings>=2.1.0
sqlalchemy>=2.0.0
pymysql>=1.1.0
cryptography>=42.0.0
redis>=5.0.0
minio>=7.2.0
requests>=2.31.0
pymupdf>=1.23.0
pytest>=8.0.0
httpx>=0.27.0
python-multipart>=0.0.9
python-dotenv>=1.0.0
pyyaml>=6.0.1
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/libs/test_settings.py -v`

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add requirements.txt conf/config.yaml conf/.env libs/settings.py tests/libs/test_settings.py
git commit -m "feat(config): add pydantic settings loader and project dependencies"
```

---

### Task 2: 数据库连接与模型

**Files:**
- Create: `core/models/base.py`
- Create: `core/models/edu_construct_files.py`
- Create: `core/models/edu_video_meta.py`
- Modify: `core/models/__init__.py`
- Create: `libs/db.py`
- Test: `tests/core/models/test_edu_models.py`

**Interfaces:**
- Consumes: `Settings.database.url`
- Produces: `libs.db.get_db_session()` 生成 `Session`；`core.models.EduConstructFile`、`EduVideoMeta`；`create_tables()` 建表函数

- [ ] **Step 1: Write the failing test**

```python
# tests/core/models/test_edu_models.py
import uuid

from libs.db import engine, create_tables
from core.models import EduConstructFile, EduVideoMeta
from sqlalchemy.orm import Session


def test_create_tables():
    create_tables()


def test_crud_file_and_meta():
    create_tables()
    file_id = str(uuid.uuid4())
    with Session(engine) as session:
        f = EduConstructFile(
            file_id=file_id,
            file_name="demo.mp4",
            file_type="video",
            file_storage_path=f"education/uploads/{file_id}/demo.mp4",
            file_size=1024,
        )
        session.add(f)
        session.commit()

        m = EduVideoMeta(
            file_id=file_id,
            duration=120.5,
            resolution="1920x1080",
            fps=1,
            scene_threshold=0.05,
            dedup_mode="scene",
        )
        session.add(m)
        session.commit()

        found = session.query(EduConstructFile).filter_by(file_id=file_id).first()
        assert found.parse_status == 0
        assert found.video_meta.duration == 120.5
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/core/models/test_edu_models.py -v`

Expected: FAIL with `ModuleNotFoundError: libs.db` 或模型未定义

- [ ] **Step 3: Write minimal implementation**

```python
# libs/db.py
from functools import lru_cache

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from libs.settings import get_settings


@lru_cache
def get_engine():
    settings = get_settings()
    return create_engine(settings.database.url, pool_pre_ping=True)


engine = get_engine()
SessionLocal = sessionmaker(bind=engine)


def get_db_session():
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


def create_tables():
    from core.models.base import Base
    Base.metadata.create_all(bind=engine)
```

```python
# core/models/base.py
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy import DateTime, func


class Base(DeclarativeBase):
    pass


class TimestampMixin:
    created_at: Mapped[DateTime] = mapped_column(DateTime, default=func.now())
    updated_at: Mapped[DateTime] = mapped_column(
        DateTime, default=func.now(), onupdate=func.now()
    )
```

```python
# core/models/edu_construct_files.py
from sqlalchemy import BIGINT, Integer, String, Text, DateTime, Index
from sqlalchemy.orm import Mapped, mapped_column, relationship

from core.models.base import Base, TimestampMixin


class EduConstructFile(Base, TimestampMixin):
    __tablename__ = "edu_construct_files"

    id: Mapped[int] = mapped_column(BIGINT, primary_key=True, autoincrement=True)
    file_id: Mapped[str] = mapped_column(String(200), unique=True, nullable=False)
    file_name: Mapped[str] = mapped_column(String(500), nullable=False)
    file_type: Mapped[str] = mapped_column(String(100), nullable=False)
    parse_status: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    file_storage_path: Mapped[str] = mapped_column(String(1000), nullable=False)
    file_size: Mapped[int] = mapped_column(BIGINT, nullable=True)
    group_name: Mapped[str] = mapped_column(String(200), nullable=True)
    parsed_text_path: Mapped[str] = mapped_column(String(1000), nullable=True)
    frame_count: Mapped[int] = mapped_column(Integer, nullable=True)
    error_msg: Mapped[str] = mapped_column(Text, nullable=True)
    deleted_at: Mapped[DateTime] = mapped_column(DateTime, nullable=True)

    video_meta: Mapped["EduVideoMeta"] = relationship(
        "EduVideoMeta", back_populates="file", uselist=False
    )

    __table_args__ = (
        Index("idx_parse_status", "parse_status"),
        Index("idx_group_name", "group_name"),
        Index("idx_created_at", "created_at"),
    )
```

```python
# core/models/edu_video_meta.py
from sqlalchemy import BIGINT, Float, Integer, String, Text, DateTime, ForeignKey, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from core.models.base import Base, TimestampMixin


class EduVideoMeta(Base, TimestampMixin):
    __tablename__ = "edu_video_meta"

    id: Mapped[int] = mapped_column(BIGINT, primary_key=True, autoincrement=True)
    file_id: Mapped[str] = mapped_column(
        String(200), ForeignKey("edu_construct_files.file_id"), nullable=False
    )
    duration: Mapped[float] = mapped_column(Float, nullable=True)
    resolution: Mapped[str] = mapped_column(String(50), nullable=True)
    fps: Mapped[int] = mapped_column(Integer, nullable=True)
    scene_threshold: Mapped[float] = mapped_column(Float, nullable=True)
    dedup_mode: Mapped[str] = mapped_column(String(50), nullable=True)
    frame_metadata_path: Mapped[str] = mapped_column(Text, nullable=True)

    file: Mapped["EduConstructFile"] = relationship(
        "EduConstructFile", back_populates="video_meta"
    )

    __table_args__ = (UniqueConstraint("file_id", name="uk_file_id"),)
```

```python
# core/models/__init__.py
from core.models.edu_construct_files import EduConstructFile
from core.models.edu_video_meta import EduVideoMeta

__all__ = ["EduConstructFile", "EduVideoMeta"]
```

- [ ] **Step 4: Run test to verify it passes**

前置：启动 MySQL

```bash
docker compose up -d mysql
pytest tests/core/models/test_edu_models.py -v
```

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add libs/db.py core/models/ tests/core/models/
git commit -m "feat(models): add EduConstructFile and EduVideoMeta models with db session"
```

---

### Task 3: OSS 客户端

**Files:**
- Create: `libs/oss_client.py`
- Test: `tests/libs/test_oss_client.py`

**Interfaces:**
- Consumes: `Settings.oss`
- Produces: `libs.oss_client.OssClient` with `upload(local_path, oss_path)`, `download(oss_path, local_dir)`, `presigned_url(oss_path, expires=3600)`

- [ ] **Step 1: Write the failing test**

```python
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/libs/test_oss_client.py -v`

Expected: FAIL with `ModuleNotFoundError: libs.oss_client`

- [ ] **Step 3: Write minimal implementation**

```python
# libs/oss_client.py
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
        return self.client.presigned_get_object(self.bucket, oss_path, expires=expires)

    def object_exists(self, oss_path: str) -> bool:
        try:
            self.client.stat_object(self.bucket, oss_path)
            return True
        except S3Error as e:
            if e.code == "NoSuchKey":
                return False
            raise
```

- [ ] **Step 4: Run test to verify it passes**

前置：启动 MinIO

```bash
docker compose up -d minio-app
pytest tests/libs/test_oss_client.py -v
```

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add libs/oss_client.py tests/libs/test_oss_client.py
git commit -m "feat(oss): add MinIO client wrapper with upload/download/presigned url"
```

---

### Task 4: Redis 客户端

**Files:**
- Create: `libs/redis_client.py`
- Test: `tests/libs/test_redis_client.py`

**Interfaces:**
- Consumes: `Settings.redis`
- Produces: `libs.redis_client.RedisClient` with `push_task(payload)`, `brpop(timeout=5)`, `acquire_lock(lock_key, ttl=60)`, `release_lock(lock_key)`

- [ ] **Step 1: Write the failing test**

```python
# tests/libs/test_redis_client.py
import json

from libs.redis_client import RedisClient
from libs.settings import Settings


def test_push_and_brpop():
    client = RedisClient(Settings())
    client.clear_queue()
    client.push_task({"file_id": "f1", "file_type": "video"})
    item = client.brpop(timeout=2)
    assert item is not None
    assert json.loads(item)["file_id"] == "f1"


def test_lock():
    client = RedisClient(Settings())
    assert client.acquire_lock("lock:test", ttl=10) is True
    assert client.acquire_lock("lock:test", ttl=10) is False
    client.release_lock("lock:test")
    assert client.acquire_lock("lock:test", ttl=10) is True
    client.release_lock("lock:test")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/libs/test_redis_client.py -v`

Expected: FAIL with `ModuleNotFoundError: libs.redis_client`

- [ ] **Step 3: Write minimal implementation**

```python
# libs/redis_client.py
import json
import uuid
from typing import Any, Dict, Optional

import redis

from libs.settings import Settings


class RedisClient:
    def __init__(self, settings: Optional[Settings] = None):
        cfg = (settings or Settings()).redis
        self.client = redis.Redis(host=cfg.host, port=cfg.port, db=cfg.db, decode_responses=True)
        self.queue_name = cfg.queue_name

    def push_task(self, payload: Dict[str, Any]):
        self.client.lpush(self.queue_name, json.dumps(payload, ensure_ascii=False))

    def brpop(self, timeout: int = 5) -> Optional[str]:
        result = self.client.brpop(self.queue_name, timeout=timeout)
        if result is None:
            return None
        return result[1]

    def acquire_lock(self, lock_key: str, ttl: int = 60) -> bool:
        token = str(uuid.uuid4())
        acquired = self.client.set(lock_key, token, nx=True, ex=ttl)
        if acquired:
            self._local_token = token
        return bool(acquired)

    def release_lock(self, lock_key: str):
        token = getattr(self, "_local_token", None)
        if token and self.client.get(lock_key) == token:
            self.client.delete(lock_key)

    def clear_queue(self):
        self.client.delete(self.queue_name)
```

- [ ] **Step 4: Run test to verify it passes**

前置：启动 Redis

```bash
docker compose up -d redis
pytest tests/libs/test_redis_client.py -v
```

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add libs/redis_client.py tests/libs/test_redis_client.py
git commit -m "feat(redis): add task queue and distributed lock client"
```

---

### Task 5: OCR 适配器

**Files:**
- Create: `service/ocr/base.py`
- Create: `service/ocr/factory.py`
- Create: `service/ocr/paddle_cloud.py`
- Create: `service/ocr/paddle_vl_local.py`
- Create: `service/ocr/__init__.py`
- Test: `tests/service/ocr/test_ocr.py`

**Interfaces:**
- Consumes: `Settings.ocr`
- Produces: `service.ocr.OcrAdapter` abstract class; `service.ocr.factory.create_ocr_adapter(settings)`; `PaddleCloudAdapter.parse_image(path) -> str`, `parse_pdf(path) -> str`

- [ ] **Step 1: Write the failing test**

```python
# tests/service/ocr/test_ocr.py
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/service/ocr/test_ocr.py -v`

Expected: FAIL with `ModuleNotFoundError: service.ocr`

- [ ] **Step 3: Write minimal implementation**

```python
# service/ocr/base.py
from abc import ABC, abstractmethod


class OcrAdapter(ABC):
    @abstractmethod
    def parse_image(self, image_path: str) -> str:
        """对单张图片进行 OCR，返回 markdown/文本。"""
        ...

    @abstractmethod
    def parse_pdf(self, pdf_path: str) -> str:
        """对 PDF 进行 OCR，返回 markdown/文本。"""
        ...
```

```python
# service/ocr/factory.py
from libs.settings import Settings
from service.ocr.base import OcrAdapter
from service.ocr.paddle_cloud import PaddleCloudAdapter
from service.ocr.paddle_vl_local import PaddleVlLocalAdapter


def create_ocr_adapter(settings: Settings) -> OcrAdapter:
    if settings.ocr.provider == "paddle-cloud":
        return PaddleCloudAdapter(settings.ocr.paddle_cloud)
    if settings.ocr.provider == "paddle-vl-local":
        return PaddleVlLocalAdapter(settings.ocr.paddle_vl_local)
    raise ValueError(f"unsupported ocr provider: {settings.ocr.provider}")
```

```python
# service/ocr/paddle_cloud.py
import base64
from pathlib import Path
from typing import Any, Dict

import requests

from service.ocr.base import OcrAdapter


class PaddleCloudAdapter(OcrAdapter):
    def __init__(self, cfg):
        self.base_url = cfg.base_url or cfg.job_url
        self.api_key = cfg.api_key or cfg.token
        self.model = cfg.model

    def _call_api(self, payload: Dict[str, Any]) -> str:
        headers = {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}
        resp = requests.post(self.base_url, json=payload, headers=headers, timeout=120)
        resp.raise_for_status()
        data = resp.json()
        # 根据实际 API 响应结构调整
        return data.get("result", "")

    def parse_image(self, image_path: str) -> str:
        b64 = base64.b64encode(Path(image_path).read_bytes()).decode()
        payload = {"model": self.model, "image": b64}
        return self._call_api(payload)

    def parse_pdf(self, pdf_path: str) -> str:
        b64 = base64.b64encode(Path(pdf_path).read_bytes()).decode()
        payload = {"model": self.model, "pdf": b64}
        return self._call_api(payload)
```

```python
# service/ocr/paddle_vl_local.py
from service.ocr.base import OcrAdapter


class PaddleVlLocalAdapter(OcrAdapter):
    """本地 paddle-vl 占位实现，后续替换为真实调用。"""

    def __init__(self, cfg):
        self.server_url = cfg.server_url
        self.device = cfg.device

    def parse_image(self, image_path: str) -> str:
        raise NotImplementedError("paddle-vl-local not ready yet")

    def parse_pdf(self, pdf_path: str) -> str:
        raise NotImplementedError("paddle-vl-local not ready yet")
```

```python
# service/ocr/__init__.py
from service.ocr.base import OcrAdapter
from service.ocr.factory import create_ocr_adapter

__all__ = ["OcrAdapter", "create_ocr_adapter"]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/service/ocr/test_ocr.py -v`

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add service/ocr/ tests/service/ocr/
git commit -m "feat(ocr): add pluggable OCR adapter with paddle-cloud implementation"
```

---

### Task 6: 文件处理器

**Files:**
- Create: `service/handler/base.py`
- Create: `service/handler/video_handler.py`
- Create: `service/handler/pdf_handler.py`
- Create: `service/handler/__init__.py`
- Test: `tests/service/handler/test_handlers.py`

**Interfaces:**
- Consumes: file path, `Settings.ffmpeg`, `Settings.video`
- Produces: `service.handler.FileHandler.extract_images(file_path, file_id) -> List[str]`；`VideoHandler` 返回帧图片路径列表；`PdfHandler` 返回每页图片路径列表

- [ ] **Step 1: Write the failing test**

```python
# tests/service/handler/test_handlers.py
import os
from pathlib import Path
from unittest.mock import patch

from service.handler.video_handler import VideoHandler
from service.handler.pdf_handler import PdfHandler
from libs.settings import Settings


def test_video_handler_extracts_frames(tmp_path: Path):
    handler = VideoHandler(Settings())
    video_path = tmp_path / "sample.mp4"
    # 用 ffmpeg 生成 1 秒测试视频
    os.system(
        f"ffmpeg -y -f lavfi -i testsrc=duration=1:size=320x240:rate=1 "
        f"-pix_fmt yuv420p {video_path} >/dev/null 2>&1"
    )
    frames = handler.extract_images(str(video_path), file_id="v1")
    assert len(frames) >= 1
    assert all(Path(f).exists() for f in frames)


def test_pdf_handler_extracts_pages(tmp_path: Path):
    handler = PdfHandler()
    # 创建一个极简 1 页 PDF
    pdf_path = tmp_path / "doc.pdf"
    try:
        import fitz
        doc = fitz.open()
        page = doc.new_page()
        page.insert_text((50, 50), "hello")
        doc.save(str(pdf_path))
        doc.close()
    except Exception:
        pytest.skip("fitz not available")

    pages = handler.extract_images(str(pdf_path), file_id="p1")
    assert len(pages) == 1
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/service/handler/test_handlers.py -v`

Expected: FAIL with `ModuleNotFoundError: service.handler`

- [ ] **Step 3: Write minimal implementation**

```python
# service/handler/base.py
from abc import ABC, abstractmethod
from typing import List


class FileHandler(ABC):
    @abstractmethod
    def extract_images(self, file_path: str, file_id: str) -> List[str]:
        """返回本地图片路径列表。"""
        ...
```

```python
# service/handler/video_handler.py
import json
import subprocess
import tempfile
from pathlib import Path
from typing import List

from service.handler.base import FileHandler


class VideoHandler(FileHandler):
    def __init__(self, settings=None):
        from libs.settings import get_settings
        self.cfg = (settings or get_settings()).ffmpeg
        self.video_cfg = (settings or get_settings()).video

    def extract_images(self, file_path: str, file_id: str) -> List[str]:
        tmpdir = tempfile.mkdtemp(prefix=f"video_{file_id}_")
        out_pattern = Path(tmpdir) / "frame_%04d.jpg"
        cmd = [
            self.cfg.path,
            "-i", file_path,
            "-vf", f"fps={self.cfg.frame_rate}",
            "-q:v", str(self.cfg.quality),
            str(out_pattern),
        ]
        subprocess.run(cmd, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)

        frames = sorted(str(p) for p in Path(tmpdir).glob("frame_*.jpg"))
        metadata = {
            "file_id": file_id,
            "source_video": file_path,
            "frames": [
                {"file": Path(f).name, "timestamp": i / max(self.cfg.frame_rate, 1)}
                for i, f in enumerate(frames)
            ],
        }
        Path(tmpdir).joinpath("metadata.json").write_text(json.dumps(metadata, ensure_ascii=False))
        return frames
```

```python
# service/handler/pdf_handler.py
import tempfile
from pathlib import Path
from typing import List

import fitz

from service.handler.base import FileHandler


class PdfHandler(FileHandler):
    def extract_images(self, file_path: str, file_id: str) -> List[str]:
        tmpdir = tempfile.mkdtemp(prefix=f"pdf_{file_id}_")
        doc = fitz.open(file_path)
        images = []
        for i, page in enumerate(doc):
            pix = page.get_pixmap(dpi=150)
            out = Path(tmpdir) / f"page_{i:04d}.jpg"
            pix.save(str(out))
            images.append(str(out))
        doc.close()
        return images
```

```python
# service/handler/__init__.py
from service.handler.base import FileHandler
from service.handler.video_handler import VideoHandler
from service.handler.pdf_handler import PdfHandler

__all__ = ["FileHandler", "VideoHandler", "PdfHandler"]
```

- [ ] **Step 4: Run test to verify it passes**

前置：确保系统已安装 ffmpeg

Run: `pytest tests/service/handler/test_handlers.py -v`

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add service/handler/ tests/service/handler/
git commit -m "feat(handler): add video frame extraction and pdf-to-image handlers"
```

---

### Task 7: 解析 Worker

**Files:**
- Create: `service/worker/parse_worker.py`
- Test: `tests/service/worker/test_parse_worker.py`

**Interfaces:**
- Consumes: `OssClient`, `OcrAdapter`, `VideoHandler`, `PdfHandler`, `Settings`
- Produces: `ParseWorker.parse(task: ParseTask)` 协调整个流程；`ParseTask` Pydantic model

- [ ] **Step 1: Write the failing test**

```python
# tests/service/worker/test_parse_worker.py
import uuid
from unittest.mock import MagicMock

from service.worker.parse_worker import ParseWorker, ParseTask
from libs.settings import Settings


def test_parse_video_uploads_md_and_updates_db():
    oss = MagicMock()
    ocr = MagicMock()
    ocr.parse_image.return_value = "frame text"
    video_handler = MagicMock()
    video_handler.extract_images.return_value = ["/tmp/frame.jpg"]
    pdf_handler = MagicMock()

    db_session = MagicMock()
    db_file = MagicMock()
    db_session.query.return_value.filter_by.return_value.first.return_value = db_file

    worker = ParseWorker(
        settings=Settings(),
        oss_client=oss,
        ocr_adapter=ocr,
        video_handler=video_handler,
        pdf_handler=pdf_handler,
    )

    task = ParseTask(file_id="f1", file_type="video", oss_path="education/video/2024/x.mp4")
    worker.parse(task, session=db_session)

    assert db_file.parse_status == 2
    assert db_file.parsed_text_path.endswith("x_parsed/x.md")
    oss.upload.assert_called()
    ocr.parse_image.assert_called_once_with("/tmp/frame.jpg")


def test_parse_pdf():
    oss = MagicMock()
    ocr = MagicMock()
    ocr.parse_pdf.return_value = "pdf markdown"
    video_handler = MagicMock()
    pdf_handler = MagicMock()
    pdf_handler.extract_images.return_value = ["/tmp/page.jpg"]

    db_session = MagicMock()
    db_file = MagicMock()
    db_session.query.return_value.filter_by.return_value.first.return_value = db_file

    worker = ParseWorker(
        settings=Settings(),
        oss_client=oss,
        ocr_adapter=ocr,
        video_handler=video_handler,
        pdf_handler=pdf_handler,
    )

    task = ParseTask(file_id="f2", file_type="pdf", oss_path="education/pdf/2024/y.pdf")
    worker.parse(task, session=db_session)

    assert db_file.parse_status == 2
    assert db_file.parsed_text_path.endswith("y_parsed/y.md")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/service/worker/test_parse_worker.py -v`

Expected: FAIL with `ModuleNotFoundError: service.worker.parse_worker`

- [ ] **Step 3: Write minimal implementation**

```python
# service/worker/parse_worker.py
import json
import os
import tempfile
from pathlib import Path
from typing import Optional

from pydantic import BaseModel

from core.models import EduConstructFile, EduVideoMeta
from libs.oss_client import OssClient
from libs.settings import Settings
from service.handler.base import FileHandler
from service.ocr.base import OcrAdapter


class ParseTask(BaseModel):
    file_id: str
    file_type: str  # video | pdf
    oss_path: str
    force: bool = False


class ParseWorker:
    def __init__(
        self,
        settings: Settings,
        oss_client: OssClient,
        ocr_adapter: OcrAdapter,
        video_handler: FileHandler,
        pdf_handler: FileHandler,
    ):
        self.settings = settings
        self.oss = oss_client
        self.ocr = ocr_adapter
        self.video_handler = video_handler
        self.pdf_handler = pdf_handler

    def parse(self, task: ParseTask, session) -> None:
        file_record = session.query(EduConstructFile).filter_by(file_id=task.file_id).first()
        if not file_record:
            raise ValueError(f"file not found: {task.file_id}")

        file_record.parse_status = 1
        session.commit()

        try:
            with tempfile.TemporaryDirectory(prefix=f"parse_{task.file_id}_") as tmpdir:
                local_file = self.oss.download(task.oss_path, tmpdir)
                parsed_dir = self._parsed_dir(task.oss_path)

                if task.file_type == "video":
                    md_path, frame_count = self._parse_video(local_file, task.file_id, parsed_dir, tmpdir)
                elif task.file_type == "pdf":
                    md_path, frame_count = self._parse_pdf(local_file, task.file_id, parsed_dir, tmpdir)
                else:
                    raise ValueError(f"unsupported file_type: {task.file_type}")

                self.oss.upload(md_path, f"{parsed_dir}/{Path(md_path).name}")
                file_record.parse_status = 2
                file_record.parsed_text_path = f"{parsed_dir}/{Path(md_path).name}"
                file_record.frame_count = frame_count
                session.commit()
        except Exception as e:
            file_record.parse_status = 3
            file_record.error_msg = str(e)
            session.commit()
            raise

    def _parsed_dir(self, oss_path: str) -> str:
        p = Path(oss_path)
        return str(p.parent / f"{p.stem}_parsed")

    def _parse_video(self, local_file: str, file_id: str, parsed_dir: str, tmpdir: str):
        frames = self.video_handler.extract_images(local_file, file_id)
        frame_texts = []
        for i, frame_path in enumerate(frames):
            oss_frame_path = f"{parsed_dir}/frames/{Path(frame_path).name}"
            self.oss.upload(frame_path, oss_frame_path)
            text = self.ocr.parse_image(frame_path)
            frame_texts.append(f"## Frame {i+1}\n\n{text}\n")

        md_content = "\n".join(frame_texts)
        md_path = Path(tmpdir) / f"{Path(local_file).stem}.md"
        md_path.write_text(md_content, encoding="utf-8")
        return str(md_path), len(frames)

    def _parse_pdf(self, local_file: str, file_id: str, parsed_dir: str, tmpdir: str):
        pages = self.pdf_handler.extract_images(local_file, file_id)
        page_texts = []
        for i, page_path in enumerate(pages):
            text = self.ocr.parse_image(page_path)
            page_texts.append(f"## Page {i+1}\n\n{text}\n")

        md_content = "\n".join(page_texts)
        md_path = Path(tmpdir) / f"{Path(local_file).stem}.md"
        md_path.write_text(md_content, encoding="utf-8")
        return str(md_path), len(pages)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/service/worker/test_parse_worker.py -v`

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add service/worker/parse_worker.py tests/service/worker/test_parse_worker.py
git commit -m "feat(worker): add ParseWorker orchestrating download-parse-upload-update"
```

---

### Task 8: 调度器与消费者

**Files:**
- Create: `service/worker/scheduler.py`
- Create: `service/worker/consumer.py`
- Modify: `service/worker/__init__.py`
- Test: `tests/service/worker/test_scheduler.py`, `tests/service/worker/test_consumer.py`

**Interfaces:**
- Consumes: `RedisClient`, `ParseWorker`, SQLAlchemy `Session`
- Produces: `Scheduler.enqueue(file_id, file_type, oss_path, force=False)`；`Consumer.start()` / `stop()`；`direct_parse(file_id)` 同步入口

- [ ] **Step 1: Write the failing test**

```python
# tests/service/worker/test_scheduler.py
from unittest.mock import MagicMock, patch

from service.worker.scheduler import Scheduler
from service.worker.parse_worker import ParseTask
from libs.settings import Settings


def test_scheduler_enqueue():
    redis_client = MagicMock()
    scheduler = Scheduler(settings=Settings(), redis_client=redis_client)
    scheduler.enqueue(file_id="f1", file_type="video", oss_path="education/video/x.mp4")
    redis_client.push_task.assert_called_once()
    task = ParseTask.model_validate_json(redis_client.push_task.call_args[0][0])
    assert task.file_id == "f1"


def test_scheduler_direct_parse():
    worker = MagicMock()
    scheduler = Scheduler(settings=Settings(), worker=worker)
    with patch("service.worker.scheduler.SessionLocal") as mock_session_cls:
        session = MagicMock()
        mock_session_cls.return_value.__enter__.return_value = session
        scheduler.direct_parse(file_id="f1", file_type="video", oss_path="education/video/x.mp4")
        worker.parse.assert_called_once()
```

```python
# tests/service/worker/test_consumer.py
import json
import threading
import time
from unittest.mock import MagicMock, patch

from service.worker.consumer import Consumer
from libs.settings import Settings


def test_consumer_processes_one_task():
    redis_client = MagicMock()
    redis_client.brpop.side_effect = [
        json.dumps({"file_id": "f1", "file_type": "video", "oss_path": "x.mp4"}),
        None,
    ]
    redis_client.acquire_lock.return_value = True
    worker = MagicMock()

    consumer = Consumer(settings=Settings(), redis_client=redis_client, worker=worker)
    consumer._running = True
    consumer._process_once()
    worker.parse.assert_called_once()
    redis_client.release_lock.assert_called_once()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/service/worker/test_scheduler.py tests/service/worker/test_consumer.py -v`

Expected: FAIL with `ModuleNotFoundError: service.worker.scheduler`

- [ ] **Step 3: Write minimal implementation**

```python
# service/worker/scheduler.py
import json

from libs.db import SessionLocal
from libs.redis_client import RedisClient
from libs.settings import Settings
from service.worker.parse_worker import ParseTask, ParseWorker


class Scheduler:
    def __init__(
        self,
        settings: Settings,
        redis_client: RedisClient = None,
        worker: ParseWorker = None,
    ):
        self.settings = settings
        self.redis = redis_client or RedisClient(settings)
        self.worker = worker

    def enqueue(
        self,
        file_id: str,
        file_type: str,
        oss_path: str,
        force: bool = False,
    ):
        task = ParseTask(file_id=file_id, file_type=file_type, oss_path=oss_path, force=force)
        self.redis.push_task(task.model_dump())

    def direct_parse(self, file_id: str, file_type: str, oss_path: str, force: bool = False):
        if self.worker is None:
            raise RuntimeError("worker not configured for direct parse")
        task = ParseTask(file_id=file_id, file_type=file_type, oss_path=oss_path, force=force)
        with SessionLocal() as session:
            self.worker.parse(task, session=session)
```

```python
# service/worker/consumer.py
import json
import logging
import threading
import time
from typing import Optional

from libs.redis_client import RedisClient
from libs.settings import Settings
from service.worker.parse_worker import ParseTask, ParseWorker
from libs.db import SessionLocal

logger = logging.getLogger(__name__)


class Consumer:
    def __init__(
        self,
        settings: Settings,
        redis_client: RedisClient = None,
        worker: ParseWorker = None,
    ):
        self.settings = settings
        self.redis = redis_client or RedisClient(settings)
        self.worker = worker
        self._thread: Optional[threading.Thread] = None
        self._running = False

    def start(self):
        if self._thread and self._thread.is_alive():
            return
        self._running = True
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()
        logger.info("consumer started")

    def stop(self):
        self._running = False
        if self._thread:
            self._thread.join(timeout=5)

    def _loop(self):
        while self._running:
            try:
                self._process_once()
            except Exception as e:
                logger.exception("consumer error: %s", e)
                time.sleep(1)

    def _process_once(self):
        raw = self.redis.brpop(timeout=5)
        if raw is None:
            return
        task = ParseTask.model_validate_json(raw)
        lock_key = f"lock:parse:{task.file_id}"
        if not self.redis.acquire_lock(lock_key, ttl=600):
            logger.warning("task already processing: %s", task.file_id)
            return
        try:
            with SessionLocal() as session:
                self.worker.parse(task, session=session)
        finally:
            self.redis.release_lock(lock_key)
```

```python
# service/worker/__init__.py
from service.worker.parse_worker import ParseWorker, ParseTask
from service.worker.scheduler import Scheduler
from service.worker.consumer import Consumer

__all__ = ["ParseWorker", "ParseTask", "Scheduler", "Consumer"]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/service/worker/test_scheduler.py tests/service/worker/test_consumer.py -v`

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add service/worker/scheduler.py service/worker/consumer.py service/worker/__init__.py tests/service/worker/
git commit -m "feat(worker): add Redis scheduler and consumer for async parse tasks"
```

---

### Task 9: HTTP API

**Files:**
- Create: `service/api/files.py`
- Create: `service/api/__init__.py`
- Test: `tests/service/api/test_files.py`

**Interfaces:**
- Consumes: FastAPI `UploadFile`, `Scheduler`, `OssClient`, SQLAlchemy `Session`
- Produces: `POST /api/v1/files/upload`, `POST /api/v1/files/register`, `GET /api/v1/files/{file_id}`, `POST /api/v1/files/{file_id}/parse`, `GET /api/v1/files/{file_id}/download`

- [ ] **Step 1: Write the failing test**

```python
# tests/service/api/test_files.py
from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient

from service.api.files import router
from fastapi import FastAPI


def make_app():
    app = FastAPI()
    app.include_router(router, prefix="/api/v1")
    return TestClient(app)


def test_register_endpoint():
    client = make_app()
    with patch("service.api.files.Scheduler") as MockScheduler, \
         patch("service.api.files.get_db_session") as mock_db:
        mock_scheduler = MagicMock()
        MockScheduler.return_value = mock_scheduler
        mock_session = MagicMock()
        mock_db.return_value = iter([mock_session])

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


def test_get_status():
    client = make_app()
    with patch("service.api.files.get_db_session") as mock_db:
        session = MagicMock()
        mock_db.return_value = iter([session])
        file_record = MagicMock()
        file_record.file_id = "f1"
        file_record.parse_status = 0
        file_record.parsed_text_path = None
        session.query.return_value.filter_by.return_value.first.return_value = file_record

        resp = client.get("/api/v1/files/f1")
        assert resp.status_code == 200
        assert resp.json()["parse_status"] == 0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/service/api/test_files.py -v`

Expected: FAIL with `ModuleNotFoundError: service.api.files`

- [ ] **Step 3: Write minimal implementation**

```python
# service/api/files.py
import uuid
from typing import Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from pydantic import BaseModel
from sqlalchemy.orm import Session

from core.models import EduConstructFile
from libs.db import get_db_session
from libs.oss_client import OssClient
from libs.redis_client import RedisClient
from libs.settings import get_settings
from service.worker.scheduler import Scheduler

router = APIRouter(tags=["files"])


class RegisterRequest(BaseModel):
    file_name: str
    file_type: str
    oss_path: str
    file_size: Optional[int] = None
    group_name: Optional[str] = None


class FileResponse(BaseModel):
    file_id: str
    status: str


def get_oss_client():
    return OssClient(get_settings())


def get_scheduler():
    return Scheduler(get_settings())


@router.post("/files/upload", response_model=FileResponse)
def upload_file(
    file: UploadFile = File(...),
    group_name: Optional[str] = Form(None),
    oss_client: OssClient = Depends(get_oss_client),
    scheduler: Scheduler = Depends(get_scheduler),
    session: Session = Depends(get_db_session),
):
    settings = get_settings()
    file_id = str(uuid.uuid4())
    ext = file.filename.split(".")[-1] if "." in file.filename else ""
    oss_path = f"education/uploads/{file_id}/{file.filename}"

    content = file.file.read()
    local_tmp = f"/tmp/{file_id}_{file.filename}"
    with open(local_tmp, "wb") as f:
        f.write(content)

    oss_client.upload(local_tmp, oss_path)

    record = EduConstructFile(
        file_id=file_id,
        file_name=file.filename,
        file_type=ext.lower() if ext in {"mp4", "ts", "pdf"} else "unknown",
        file_storage_path=oss_path,
        file_size=len(content),
        group_name=group_name,
    )
    session.add(record)
    session.commit()

    scheduler.enqueue(file_id=record.file_id, file_type=record.file_type, oss_path=oss_path)
    return FileResponse(file_id=file_id, status="pending")


@router.post("/files/register", response_model=FileResponse)
def register_file(
    req: RegisterRequest,
    scheduler: Scheduler = Depends(get_scheduler),
    session: Session = Depends(get_db_session),
):
    file_id = str(uuid.uuid4())
    record = EduConstructFile(
        file_id=file_id,
        file_name=req.file_name,
        file_type=req.file_type,
        file_storage_path=req.oss_path,
        file_size=req.file_size,
        group_name=req.group_name,
    )
    session.add(record)
    session.commit()

    scheduler.enqueue(file_id=file_id, file_type=req.file_type, oss_path=req.oss_path)
    return FileResponse(file_id=file_id, status="pending")


@router.get("/files/{file_id}")
def get_file(file_id: str, session: Session = Depends(get_db_session)):
    record = session.query(EduConstructFile).filter_by(file_id=file_id).first()
    if not record:
        raise HTTPException(status_code=404, detail="file not found")
    return {
        "file_id": record.file_id,
        "file_name": record.file_name,
        "file_type": record.file_type,
        "parse_status": record.parse_status,
        "file_storage_path": record.file_storage_path,
        "parsed_text_path": record.parsed_text_path,
        "frame_count": record.frame_count,
        "error_msg": record.error_msg,
        "created_at": record.created_at.isoformat() if record.created_at else None,
    }


@router.post("/files/{file_id}/parse")
def parse_file(
    file_id: str,
    sync: bool = Query(False),
    scheduler: Scheduler = Depends(get_scheduler),
    session: Session = Depends(get_db_session),
):
    record = session.query(EduConstructFile).filter_by(file_id=file_id).first()
    if not record:
        raise HTTPException(status_code=404, detail="file not found")

    if sync:
        scheduler.direct_parse(
            file_id=file_id, file_type=record.file_type, oss_path=record.file_storage_path
        )
        return {"file_id": file_id, "status": "completed"}

    scheduler.enqueue(
        file_id=file_id, file_type=record.file_type, oss_path=record.file_storage_path, force=True
    )
    return {"file_id": file_id, "status": "pending"}


@router.get("/files/{file_id}/download")
def download_file(
    file_id: str,
    type: str = Query("parsed", enum=["original", "parsed"]),
    oss_client: OssClient = Depends(get_oss_client),
    session: Session = Depends(get_db_session),
):
    record = session.query(EduConstructFile).filter_by(file_id=file_id).first()
    if not record:
        raise HTTPException(status_code=404, detail="file not found")

    path = record.parsed_text_path if type == "parsed" else record.file_storage_path
    if not path:
        raise HTTPException(status_code=404, detail="file not available")

    url = oss_client.presigned_url(path)
    return {"file_id": file_id, "url": url}
```

```python
# service/api/__init__.py
from service.api.files import router

__all__ = ["router"]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/service/api/test_files.py -v`

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add service/api/files.py service/api/__init__.py tests/service/api/
git commit -m "feat(api): add file upload/register/status/parse/download endpoints"
```

---

### Task 10: 服务主入口

**Files:**
- Create: `service/main.py`
- Test: `tests/service/test_main.py`

**Interfaces:**
- Consumes: `files.router`, `Consumer`, `Scheduler`, `ParseWorker`
- Produces: `uvicorn service.main:app` 可启动；lifespan 中初始化全局依赖并启动 consumer

- [ ] **Step 1: Write the failing test**

```python
# tests/service/test_main.py
from fastapi.testclient import TestClient
from service.main import app


def test_healthcheck():
    client = TestClient(app)
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/service/test_main.py -v`

Expected: FAIL with `ModuleNotFoundError: service.main`

- [ ] **Step 3: Write minimal implementation**

```python
# service/main.py
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI

from libs.db import create_tables
from libs.oss_client import OssClient
from libs.redis_client import RedisClient
from libs.settings import get_settings
from service.api.files import router
from service.handler import VideoHandler, PdfHandler
from service.ocr import create_ocr_adapter
from service.worker import Consumer, ParseWorker, Scheduler

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def build_worker():
    settings = get_settings()
    return ParseWorker(
        settings=settings,
        oss_client=OssClient(settings),
        ocr_adapter=create_ocr_adapter(settings),
        video_handler=VideoHandler(settings),
        pdf_handler=PdfHandler(),
    )


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    create_tables()
    worker = build_worker()
    consumer = Consumer(settings=settings, worker=worker)
    consumer.start()
    app.state.consumer = consumer
    app.state.worker = worker
    logger.info("application startup complete")
    yield
    consumer.stop()
    logger.info("application shutdown complete")


app = FastAPI(title="llm-construct-question", lifespan=lifespan)
app.include_router(router, prefix="/api/v1")


@app.get("/health")
def health():
    return {"status": "ok"}


if __name__ == "__main__":
    import uvicorn
    settings = get_settings()
    uvicorn.run("service.main:app", host=settings.server.host, port=settings.server.port, reload=True)
```

- [ ] **Step 4: Run test to verify it passes**

前置：MySQL/Redis/MinIO 已启动

Run: `pytest tests/service/test_main.py -v`

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add service/main.py tests/service/test_main.py
git commit -m "feat(main): wire FastAPI app with lifespan, health endpoint and consumer"
```

---

### Task 11: Docker 与启动脚本

**Files:**
- Create: `Dockerfile`
- Modify: `bin/start.sh`
- Modify: `bin/stop.sh`
- Test: `tests/integration/test_docker.py`（可选：验证镜像构建）

**Interfaces:**
- Produces: `./bin/start.sh` 启动 docker compose 依赖 + FastAPI；`./bin/stop.sh` 停止

- [ ] **Step 1: Write the failing test**

```python
# tests/integration/test_docker.py
import subprocess


def test_dockerfile_builds():
    result = subprocess.run(
        ["docker", "build", "-t", "llm-construct:test", "."],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/integration/test_docker.py -v`

Expected: FAIL with `Dockerfile` 不存在

- [ ] **Step 3: Write minimal implementation**

```dockerfile
# Dockerfile
FROM python:3.10-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    gcc \
    libglib2.0-0 \
    libsm6 \
    libxext6 \
    libxrender-dev \
    libgomp1 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 8000

CMD ["python", "-m", "service.main"]
```

```bash
# bin/start.sh
#!/usr/bin/env bash
set -e

cd "$(dirname "$0")/.."

echo "Starting infrastructure..."
docker compose up -d mysql redis minio-app

echo "Waiting for MySQL..."
until docker exec llm-mysql mysql -uroot -proot -e "SELECT 1" >/dev/null 2>&1; do
  sleep 1
done

echo "Starting application..."
python -m service.main
```

```bash
# bin/stop.sh
#!/usr/bin/env bash
set -e

cd "$(dirname "$0")/.."

echo "Stopping application..."
pkill -f "service.main" || true

echo "Stopping infrastructure..."
docker compose down
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/integration/test_docker.py -v`

Expected: PASS（耗时较长，首次构建会下载镜像）

- [ ] **Step 5: Commit**

```bash
git add Dockerfile bin/start.sh bin/stop.sh tests/integration/test_docker.py
git commit -m "feat(deploy): add Dockerfile and start/stop scripts"
```

---

### Task 12: 集成测试

**Files:**
- Create: `tests/integration/test_full_flow.py`
- Create: `tests/conftest.py`

**Interfaces:**
- Consumes: 真实 MySQL、Redis、MinIO、mock OCR
- Produces: 端到端验证 `upload -> queue -> parse -> status` 完整链路

- [ ] **Step 1: Write the failing test**

```python
# tests/conftest.py
import pytest

from libs.db import create_tables
from libs.oss_client import OssClient
from libs.redis_client import RedisClient
from libs.settings import Settings


@pytest.fixture(scope="session", autouse=True)
def init_database():
    create_tables()


@pytest.fixture
def settings():
    return Settings()


@pytest.fixture
def oss_client(settings):
    return OssClient(settings)


@pytest.fixture
def redis_client(settings):
    return RedisClient(settings)
```

```python
# tests/integration/test_full_flow.py
import time
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from service.main import app


def test_upload_pdf_and_parse(tmp_path: Path):
    client = TestClient(app)

    pdf = tmp_path / "math.pdf"
    try:
        import fitz
        doc = fitz.open()
        page = doc.new_page()
        page.insert_text((50, 50), "一元二次方程")
        doc.save(str(pdf))
        doc.close()
    except Exception:
        pytest.skip("fitz not available")

    with patch("service.main.create_ocr_adapter") as mock_factory:
        adapter = mock_factory.return_value
        adapter.parse_image.return_value = "一元二次方程"

        with open(pdf, "rb") as f:
            resp = client.post("/api/v1/files/upload", files={"file": ("math.pdf", f, "application/pdf")})
        assert resp.status_code == 200
        file_id = resp.json()["file_id"]

        # 等待 consumer 处理
        for _ in range(30):
            status_resp = client.get(f"/api/v1/files/{file_id}")
            if status_resp.json()["parse_status"] == 2:
                break
            time.sleep(1)

        assert status_resp.json()["parse_status"] == 2
        assert status_resp.json()["parsed_text_path"].endswith("math_parsed/math.md")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/integration/test_full_flow.py -v`

Expected: FAIL（因 `tests/conftest.py` 未创建或路径不存在）

- [ ] **Step 3: Write minimal implementation**

`tests/conftest.py` 已在 Step 1 中给出；补充 `tests/integration/__init__.py`：

```bash
mkdir -p tests/integration
touch tests/integration/__init__.py
```

- [ ] **Step 4: Run test to verify it passes**

前置：docker compose up -d mysql redis minio-app

Run: `pytest tests/integration/test_full_flow.py -v -s`

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add tests/conftest.py tests/integration/
git commit -m "test(integration): add end-to-end upload-parse-status flow test"
```

---

## Self-Review

**1. Spec coverage:**
- 文件上传接口 ✓ Task 9
- 文件注册接口 ✓ Task 9
- 状态查询 ✓ Task 9
- 同步/异步解析触发 ✓ Task 8 + Task 9
- OSS 原始文件与解析结果存储 ✓ Task 3 + Task 7
- MySQL 元数据与解析状态 ✓ Task 2 + Task 7
- Redis 队列消费 ✓ Task 4 + Task 8
- 视频 ffmpeg 抽帧 ✓ Task 6
- PDF OCR ✓ Task 5 + Task 6
- OCR 可插拔 ✓ Task 5
- 同步解析入口 ✓ Task 8
- OSS 路径约定 ✓ Task 7
- 错误处理与重试 ✓ Task 7（异常转失败状态）
- 幂等锁 ✓ Task 4 + Task 8
- 临时文件清理 ✓ Task 7（TemporaryDirectory）
- 测试策略 ✓ 各 Task 均含单测，Task 12 集成测试
- Docker 部署 ✓ Task 11
- 参考代码约束 ✓ Global Constraints

**2. Placeholder scan:**
- 无 TBD/TODO
- 无 "add appropriate error handling" 等模糊描述
- 所有步骤均给出具体代码或命令
- 无 "Similar to Task N" 引用

**3. Type consistency:**
- `ParseTask` 在 Task 7/8/9/10 中字段一致
- `OssClient.upload(local_path, oss_path)` 签名一致
- `RedisClient.push_task/brpop/acquire_lock/release_lock` 签名一致
- `FileHandler.extract_images(file_path, file_id)` 签名一致
- `OcrAdapter.parse_image/parse_pdf` 签名一致

**未发现 gaps，计划可执行。**
