# 教育场景知识构建模块设计文档

**日期**: 2026-07-29  
**项目**: llm-construct-question  
**范围**: 数据接入、OSS 存储、MySQL 元数据管理、PDF/视频 OCR 解析、Redis 队列消费

---

## 1. 背景与目标

基于客户提供的高一～高三数学讲解视频（ts/mp4）和 PDF 文档，构建题型知识图谱。本阶段只负责**数据接入与内容解析**，不包含下游的题型分类、知识图谱构建、推荐算法、考试评估。

目标：

1. 提供文件上传接口，支持视频（ts/mp4）、PDF；Word 暂不实现，预留扩展点。
2. 原始文件上传 OSS，MySQL 记录文件元数据与解析状态。
3. 异步解析文件内容：
   - 视频：ffmpeg 抽帧 → 帧图片上传 OSS → OCR(VL) → 整合为 `.md`。
   - PDF：OCR(VL) → 整合为 `.md`。
4. 解析结果（`.md`、视频帧图片、metadata.json）上传 OSS，并更新 MySQL 状态。
5. 支持 Redis 队列消费执行解析任务，同时提供同步解析入口用于调试/小文件。
6. OCR 服务可插拔：当前使用云端 paddle API，后续通过配置切换为本地 paddle-vl。

---

## 2. 架构总览

```
┌─────────────────────────────────────────────────────────────────┐
│                    llm-construct-question                       │
│  ┌──────────────┐    ┌──────────────┐    ┌──────────────────┐  │
│  │  FastAPI     │    │  Redis Queue │    │  Parse Worker    │  │
│  │  HTTP API    │◄──►│  Consumer    │◄──►│  (async thread)  │  │
│  └──────┬───────┘    └──────────────┘    └──────────────────┘  │
│         │                                                       │
│         │  upload / register / status / sync-parse              │
│         ▼                                                       │
│  ┌──────────────┐    ┌──────────────┐    ┌──────────────────┐  │
│  │   MinIO OSS  │    │    MySQL     │    │      Redis       │  │
│  │  (file/md)   │    │ edu_construct_files │  │  (task queue)    │  │
│  └──────────────┘    └──────────────┘    └──────────────────┘  │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
                  ┌───────────────────────┐
                  │   Pluggable OCR       │
                  │  - paddle-cloud-api   │  (当前)
                  │  - paddle-vl-local    │  (后续)
                  └───────────────────────┘
```

核心原则：

- HTTP 层只做：接收文件/OSS 路径、写 MySQL、推队列、状态查询、同步解析入口。
- 所有实际解析（下载 → 抽帧/OCR → 整合 → 上传 md）交给 `ParseWorker`，默认从 Redis 队列消费，也支持 HTTP 直接调用。
- OCR、视频抽帧、OSS 都抽象成接口，方便后续切换实现。

---

## 3. 模块划分与接口

| 模块 | 文件/包 | 职责 |
|---|---|---|
| HTTP API 层 | `service/api/files.py` | 上传、注册、状态查询、同步/异步解析触发 |
| 任务调度器 | `service/worker/scheduler.py` | 把任务推入 Redis 队列；HTTP 同步时直接调用 worker |
| 解析 Worker | `service/worker/parse_worker.py` | 消费队列，协调下载→解析→上传→更新状态 |
| Redis 消费者 | `service/worker/consumer.py` | 后台线程，循环 `brpop` 队列并调用 worker |
| 文件处理器 | `service/handler/` | `video_handler.py`（ffmpeg 抽帧）、`pdf_handler.py`（pdf 预处理） |
| OCR 适配器 | `service/ocr/` | `base.py`（接口）+ `paddle_cloud.py` + `paddle_vl_local.py` |
| OSS 客户端 | `libs/oss_client.py` | 上传、下载、生成预签名 URL |
| MySQL 模型 | `core/models/` | `edu_construct_files.py` + `edu_video_meta.py` |
| Redis 客户端 | `libs/redis_client.py` | 队列操作、分布式锁 |
| 配置 | `conf/config.yaml` / `.env` | 数据库、Redis、OSS、OCR、ffmpeg 等配置 |

### 3.1 关键接口约定

```python
# service/ocr/base.py
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
# service/handler/base.py
class FileHandler(ABC):
    @abstractmethod
    def extract_images(self, file_path: str, file_id: str) -> List[str]:
        """返回本地图片路径列表。"""
        ...
```

---

## 4. HTTP 接口与数据流

### 4.1 接口列表

| 方法 | 路径 | 说明 |
|---|---|---|
| `POST` | `/api/v1/files/upload` | 直接上传文件流，服务写入 OSS + MySQL，默认异步入队 |
| `POST` | `/api/v1/files/register` | 调用方已上传 OSS，只登记元数据并触发解析 |
| `GET` | `/api/v1/files/{file_id}` | 查询文件元数据和解析状态 |
| `POST` | `/api/v1/files/{file_id}/parse` | 手动触发重新解析（`sync=true` 走同步） |
| `GET` | `/api/v1/files/{file_id}/download` | 返回原始文件或解析后 md 的下载链接 |

### 4.2 上传流程（默认异步）

```text
调用方 POST /files/upload (multipart/form-data)
    ↓
FastAPI 接收文件流
    ↓
生成 file_id (uuid)
    ↓
上传原始文件到 OSS 默认路径: education/uploads/{file_id}/{filename}
    ↓
写入 MySQL: parse_status=0
    ↓
推入 Redis 队列: {"file_id": "...", "file_type": "video", "oss_path": "..."}
    ↓
返回 {file_id, status: "pending"}
```

> 直接上传接口使用默认 OSS 路径 `education/uploads/{file_id}/{filename}`；若调用方需要自定义目录结构，应使用 `/files/register` 接口（此时 OSS 路径由调用方指定）。

### 4.2.1 Redis 队列消息格式

```json
{
  "file_id": "uuid",
  "file_type": "video",
  "oss_path": "education/video/2024/xxx.mp4",
  "force": false
}
```

- `file_id`: 服务生成的唯一标识。
- `file_type`: `video` | `pdf`。
- `oss_path`: 原始文件在 OSS 上的完整路径。
- `force`: 是否强制覆盖已有的解析结果。

### 4.3 Redis 消费流程

```text
Consumer Thread 循环 brpop
    ↓
取到任务
    ↓
获取 Redis 锁 lock:parse:{file_id}（防止重复消费）
    ↓
更新 MySQL parse_status=1
    ↓
从 OSS 下载原始文件到本地 /tmp/{file_id}/
    ↓
按 file_type 分发：
  video → ffmpeg 抽帧 → 上传帧到 OSS → OCR 每帧 → 整合 md
  pdf   → OCR 每页/整本 → 整合 md
    ↓
上传 md 到 OSS: <原始目录>/<原始文件名(无扩展名)>_parsed/<原始文件名(无扩展名)>.md
    ↓
更新 MySQL parse_status=2, parsed_text_path=...
    ↓
释放锁、清理本地临时文件
```

### 4.4 视频解析详细流程

```text
视频下载到本地
    ↓
ffmpeg 抽帧 → 本地帧图片
    ↓
同时做三件事：
  ① 把帧图片上传到 OSS: <原始目录>/<原始文件名(无扩展名)>_parsed/frames/frame_0001.jpg
  ② 对本地帧图片调用 OCR(VL) 得到每帧文本
  ③ 抽取视频元信息（duration/resolution/fps/scene_threshold）
    ↓
按时间戳整合所有帧文本 → 生成完整视频内容.md
    ↓
上传 md 到 OSS: <原始目录>/<原始文件名(无扩展名)>_parsed/<原始文件名(无扩展名)>.md
上传 metadata.json 到 OSS: <原始目录>/<原始文件名(无扩展名)>_parsed/metadata.json
    ↓
更新 edu_construct_files.parse_status=2, parsed_text_path, frame_count
更新 edu_video_meta 时长/分辨率/fps 等
```

### 4.5 同步解析流程

`/files/{file_id}/parse?sync=true` 时，worker 直接在当前 HTTP 后台任务中执行解析，适合小文件或调试。大文件视频仍建议走异步。

### 4.6 注册接口流程（调用方已传 OSS）

`POST /files/register` 接收 `file_name`、`file_type`、`oss_path`、`file_size`、`group_name?`，只做校验和 MySQL 写入，然后推队列。

---

## 5. 数据模型

### 5.1 edu_construct_files

```sql
CREATE TABLE edu_construct_files (
    id                  BIGINT AUTO_INCREMENT PRIMARY KEY,
    file_id             VARCHAR(200) UNIQUE,
    file_name           VARCHAR(500) NOT NULL,
    file_type           VARCHAR(100) NOT NULL,          -- pdf / video / word(后续)
    parse_status        TINYINT NOT NULL DEFAULT 0,     -- 0待解析 1解析中 2完成 3失败
    file_storage_path   VARCHAR(1000) NOT NULL,         -- OSS 原始文件路径
    file_size           BIGINT,
    group_name          VARCHAR(200),
    parsed_text_path    VARCHAR(1000),                  -- 解析后 .md 路径
    frame_count         INT,                            -- 视频=帧数，PDF=页数
    error_msg           TEXT,                           -- 失败原因/堆栈
    created_at          DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at          DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    deleted_at          DATETIME,
    INDEX idx_parse_status (parse_status),
    INDEX idx_group_name (group_name),
    INDEX idx_created_at (created_at)
);
```

### 5.2 edu_video_meta

```sql
CREATE TABLE edu_video_meta (
    id                  BIGINT AUTO_INCREMENT PRIMARY KEY,
    file_id             VARCHAR(200) NOT NULL,          -- 对应 edu_construct_files.file_id
    duration            FLOAT,                          -- 视频时长（秒）
    resolution          VARCHAR(50),                    -- 分辨率，如 1920x1080
    fps                 INT,                            -- 抽帧帧率
    scene_threshold     FLOAT,                          -- 场景检测阈值
    dedup_mode          VARCHAR(50),                    -- scene / hash / none
    frame_metadata_path VARCHAR(1000),                  -- OSS 上 metadata.json 路径
    created_at          DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at          DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    UNIQUE KEY uk_file_id (file_id),
    FOREIGN KEY (file_id) REFERENCES edu_construct_files(file_id)
);
```

---

## 6. OSS 路径约定

假设原始文件路径为 `education/video/2024/xxx.mp4`，文件主名为 `xxx`。

| 类型 | OSS 路径 |
|---|---|
| 原始文件 | `education/video/2024/xxx.mp4` |
| 解析后目录 | `education/video/2024/xxx_parsed/` |
| 解析后 md | `education/video/2024/xxx_parsed/xxx.md` |
| 视频帧图片 | `education/video/2024/xxx_parsed/frames/frame_0001.jpg` |
| 视频 metadata | `education/video/2024/xxx_parsed/metadata.json` |

PDF 同理：若原始文件为 `education/pdf/2024/yyy.pdf`，则解析后目录为 `education/pdf/2024/yyy_parsed/`，md 文件为 `education/pdf/2024/yyy_parsed/yyy.md`。

直接上传接口的默认原始路径为 `education/uploads/{file_id}/{filename}`，其解析后目录为 `education/uploads/{file_id}/{filename(无扩展名)}_parsed/`。

---

## 7. 错误处理与重试

### 7.1 状态机

```
待解析(0) ──► 解析中(1) ──► 完成(2)
                │
                └──► 失败(3)
```

- 失败后可以调用 `/files/{file_id}/parse` 重新解析。
- 重试时 OSS 上已有的 md/frames 默认覆盖。

### 7.2 异常分类

| 异常类型 | 示例 | 处理 |
|---|---|---|
| 可重试 | OCR 服务超时、网络抖动 | 更新 error_msg，状态=3，由调用方重试 |
| 不可重试 | 文件不存在、格式不支持 | 更新 error_msg，状态=3 |
| 部分失败 | 某些帧 OCR 失败 | 记录失败帧，继续整合其余文本，最终状态=2，error_msg 记录警告 |

### 7.3 幂等与去重

- Redis 队列任务使用 `file_id` 作为唯一键，消费前用 Redis 分布式锁 `lock:parse:{file_id}` 防止重复消费。
- 上传接口若检测到相同 `file_id` 已存在，返回已有记录，不重复写入。

### 7.4 临时文件清理

- Worker 使用 `tempfile.TemporaryDirectory` 或固定 `/tmp/{file_id}` 目录。
- 无论成功失败，`finally` 块中清理本地临时文件；OSS 上的原始文件和解析结果保留。

---

## 8. OCR 适配器设计

```python
# service/ocr/paddle_cloud.py
class PaddleCloudAdapter(OcrAdapter):
    def __init__(self, base_url: str, api_key: str):
        self.base_url = base_url
        self.api_key = api_key

    def parse_image(self, image_path: str) -> str:
        # 读取本地图片字节，调用云端 paddle API
        ...

    def parse_pdf(self, pdf_path: str) -> str:
        # 按页拆图或整本上传，调用云端 paddle API
        ...
```

```python
# service/ocr/paddle_vl_local.py
class PaddleVlLocalAdapter(OcrAdapter):
    def __init__(self, server_url: str, device: str):
        # 后续本地 paddle-vl 部署后切换
        ...
```

配置决定使用哪个适配器：

```yaml
ocr:
  provider: paddle-cloud    # paddle-cloud | paddle-vl-local
```

---

## 9. 视频抽帧设计

复用 `videoAnalysis` 的核心思路，但重新实现：

- 使用 `subprocess` 调用 ffmpeg。
- 支持按 fps 抽帧 + 场景检测去重（`scene` 模式）。
- 输出格式：jpg。
- 抽帧结果保存 metadata.json，包含每帧文件名、时间戳、来源视频、video_id。
- 帧图片和 metadata.json 都上传 OSS。

配置项：

```yaml
ffmpeg:
  path: ffmpeg
  frame_rate: 1
  output_format: jpg
  quality: 2

video:
  dedup_mode: scene
  scene_threshold: 0.05
```

---

## 10. 目录结构

```
llm-construct-question/
├── bin/
│   ├── start.sh
│   └── stop.sh
├── conf/
│   ├── config.yaml
│   └── .env
├── core/
│   └── models/
│       ├── __init__.py
│       ├── edu_construct_files.py
│       └── edu_video_meta.py
├── libs/
│   ├── oss_client.py
│   ├── redis_client.py
│   └── db.py
├── service/
│   ├── main.py
│   ├── api/
│   │   └── files.py
│   ├── worker/
│   │   ├── consumer.py
│   │   ├── scheduler.py
│   │   └── parse_worker.py
│   ├── handler/
│   │   ├── base.py
│   │   ├── video_handler.py
│   │   └── pdf_handler.py
│   └── ocr/
│       ├── base.py
│       ├── paddle_cloud.py
│       └── paddle_vl_local.py
├── tests/
├── requirements.txt
├── Dockerfile
└── docker-compose.yml
```

---

## 11. 配置示例

```yaml
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

---

## 12. 测试策略

| 测试层级 | 内容 | 工具 |
|---|---|---|
| 单元测试 | OCR 适配器、ffmpeg 抽帧、OSS 路径生成、文本整合 | pytest |
| 接口测试 | 上传、注册、状态查询、同步/异步解析 | TestClient (FastAPI) |
| 集成测试 | 真实上传 → 队列消费 → OSS 落库 → MySQL 状态更新 | 本地 docker-compose |
| 异常测试 | OCR 失败、ffmpeg 失败、OSS 不可用、重复上传 | pytest + mock |

可测性设计：

- OCR、视频处理、OSS、Redis、MySQL 全部通过接口/依赖注入传入，便于 mock。
- 提供 `ocr_provider=mock` / `video_provider=mock` 配置，CI 不依赖真实模型。
- 关键函数返回值包含 `file_id`、`oss_paths`、`status`，方便断言。

---

## 13. 部署与启动

### 13.1 本地开发

```bash
python -m service.main
```

### 13.2 生产启动

```bash
./bin/start.sh
```

`service/main.py` 启动时：

1. 加载配置。
2. 初始化 MySQL、Redis、OSS、OCR 适配器。
3. 启动 FastAPI。
4. 在 `startup_event` 中启动 Redis consumer 线程。

### 13.3 Docker

- 基于 `python:3.10-slim`。
- 安装 ffmpeg。
- 挂载 `conf/` 和日志目录。
- 复用项目已有的 `docker-compose.yml` 中的 mysql / redis / minio。

---

## 14. 风险与后续扩展

| 风险 | 缓解措施 |
|---|---|
| 几百 GB 视频上传超时 | 优先使用 `/files/register`（调用方已传 OSS）；直接上传接口后续可扩展分片 |
| OCR 服务不稳定 | 适配器内部加超时、重试；失败状态可重试 |
| 单进程 consumer 处理能力不足 | ParseWorker 抽象独立，后续可拆分为独立 consumer 进程 |
| Word 支持 | 后续通过新增 `word_handler.py` + 转 PDF 实现 |
| 本地 paddle-vl 切换 | 新增 `paddle_vl_local.py` 适配器，改配置即可 |

---

## 15. 参考代码约束

- `reference/` 目录下的代码仅作逻辑参考，不能直接引用。
- 所有实现写在 `reference/` 之外。
- 当前本地开发无法使用服务器模型服务，先用云端 paddle API；部署到服务器后通过 `ocr.provider` 配置切换。
