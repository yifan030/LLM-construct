# llm-construct-question

教育场景知识构建模块 —— 用于接收、存储并解析高中数学讲解视频（mp4/ts）与 PDF 文档，将内容转换为 Markdown 文本，供后续题型分类与知识图谱构建使用。

---

## 功能概述

- **文件上传**：单接口支持视频（mp4/ts）与 PDF 上传，原始文件写入 MinIO，元数据写入 MySQL。
- **外部文件登记**：调用方自行上传 OSS 后，可通过 `register` 接口登记并触发解析。
- **异步解析**：基于 Redis 队列消费，默认后台解析，不阻塞 HTTP 请求。
- **同步解析入口**：通过 `?sync=true` 在 HTTP 层直接调用解析 Worker。
- **OCR 可插拔**：当前默认 PaddleCloud OCR-VL，后续可通过配置切换为本地 Paddle-VL。
- **视频解析**：使用 ffmpeg 抽帧，帧图与 metadata 一并上传 OSS。
- **PDF 解析**：使用 PyMuPDF 拆页后调用 OCR 生成 Markdown。

---

## 技术栈

| 用途 | 组件 |
|---|---|
| Web 框架 | FastAPI + Uvicorn |
| 配置管理 | Pydantic Settings + YAML/环境变量 |
| 数据库 | MySQL 8 + SQLAlchemy 2.0 |
| 对象存储 | MinIO（S3 兼容） |
| 任务队列 | Redis + 自定义 Consumer |
| OCR | PaddleCloud API / 本地 Paddle-VL（预留） |
| 视频处理 | ffmpeg |
| 测试 | pytest |

---

## 快速开始

### 1. 环境准备

- Python 3.10+
- Docker + Docker Compose
- ffmpeg（本地开发/运行时需要，容器镜像已内置）

### 2. 安装依赖

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### 3. 启动基础设施

```bash
docker compose up -d
```

将启动：
- MySQL：`localhost:3306`，数据库 `llm_construct`
- Redis：`localhost:6379`
- MinIO：`localhost:9000`（API），`localhost:9001`（Console）

默认账号密码见 `docker-compose.yml`。

### 4. 配置

配置优先级：**环境变量 > `conf/config.yaml` > 默认值**。

开发环境可直接使用 `conf/config.yaml`，生产环境建议通过 `conf/.env` 或导出环境变量覆盖敏感信息。

```bash
# 示例：复制示例文件后按需修改
cp conf/.env .env
# 编辑 .env 后加载
export $(grep -v '^#' .env | xargs)
```

> ⚠️ 不要将真实密钥提交到版本库。`.env` 已加入 `.gitignore`。

### 5. 启动应用

一键启动（会自动等待 MySQL/Redis/MinIO 就绪）：

```bash
bin/start.sh
```

或手动启动：

```bash
python -m service.main
```

服务默认监听 `http://localhost:8000`。

停止应用与基础设施：

```bash
bin/stop.sh
```

---

## API 接口

基础路径：`/api/v1`

| 方法 | 路径 | 说明 |
|---|---|---|
| `POST` | `/files/upload` | 上传文件（multipart/form-data） |
| `POST` | `/files/register` | 登记已上传 OSS 的文件 |
| `GET` | `/files/{file_id}` | 查询文件元数据与解析状态 |
| `POST` | `/files/{file_id}/parse?sync=false` | 重新解析（默认异步） |
| `POST` | `/files/{file_id}/parse?sync=true` | 同步解析 |
| `GET` | `/files/{file_id}/download?type=parsed` | 获取解析后 Markdown 下载链接 |
| `GET` | `/files/{file_id}/download?type=original` | 获取原始文件下载链接 |
| `GET` | `/health` | 健康检查 |

### 示例：上传文件

```bash
curl -X POST "http://localhost:8000/api/v1/files/upload" \
  -F "file=@example.mp4" \
  -F "group_name=高一数学"
```

返回：

```json
{
  "file_id": "uuid",
  "status": "pending"
}
```

### 示例：查询状态

```bash
curl "http://localhost:8000/api/v1/files/{file_id}"
```

---

## 项目结构

```text
.
├── bin/                    # 启动/停止脚本
│   ├── start.sh
│   └── stop.sh
├── conf/                   # 配置文件
│   ├── config.yaml
│   └── .env                # 环境变量示例（敏感信息勿提交）
├── core/models/            # SQLAlchemy 数据模型
├── libs/                   # 基础客户端
│   ├── db.py               # MySQL 连接与会话
│   ├── oss_client.py       # MinIO 客户端
│   ├── redis_client.py     # Redis 队列与锁
│   └── settings.py         # 配置加载
├── service/
│   ├── api/files.py        # FastAPI 路由
│   ├── main.py             # 应用入口
│   ├── handler/            # 文件预处理（视频/PDF）
│   ├── ocr/                # OCR 适配器
│   └── worker/             # 解析 Worker + 队列 Consumer + 调度器
├── tests/                  # 测试用例
├── Dockerfile
├── docker-compose.yml
└── requirements.txt
```

---

## 解析流程

```text
上传/登记文件
    ↓
写入 MinIO 原始文件路径
    ↓
MySQL 写入 edu_construct_files 元数据（status=pending）
    ↓
任务入队 Redis（edu_construct_parse_queue）
    ↓
Consumer 弹出任务
    ↓
ParseWorker 执行：
    1. 从 MinIO 下载文件到临时目录
    2. 视频 → ffmpeg 抽帧；PDF → 拆页
    3. OCR 识别图片/页面 → Markdown
    4. 上传 Markdown、帧图、metadata 到 MinIO
    5. 更新 MySQL：status=completed / failed
```

---

## 测试

```bash
pytest tests/ -q
```

> 注意：仓库根目录下的 `reference/` 目录包含历史参考代码，直接运行 `pytest` 可能导致用例收集冲突，建议始终指定 `pytest tests/`。

---

## Docker 部署

构建镜像：

```bash
docker build -t llm-construct-question .
```

结合 `docker-compose.yml` 启动完整环境（镜像构建后可通过 compose 扩展服务）。

---

## 配置说明

关键配置项（`conf/config.yaml` 或环境变量）：

| 配置项 | 环境变量示例 | 说明 |
|---|---|---|
| 服务地址 | `SERVER__HOST`, `SERVER__PORT` | FastAPI 监听地址与端口 |
| 数据库 | `DATABASE__URL` | MySQL 连接串 |
| Redis | `REDIS__HOST`, `REDIS__PORT`, `REDIS__QUEUE_NAME` | 队列配置 |
| OSS | `OSS__ENDPOINT`, `OSS__ACCESS_KEY`, `OSS__SECRET_KEY`, `OSS__BUCKET_NAME` | MinIO 配置 |
| OCR | `OCR__PROVIDER`, `OCR__PADDLE_CLOUD__TOKEN`, `OCR__PADDLE_CLOUD__MODEL` | `paddle-cloud` 或 `paddle-vl-local` |
| ffmpeg | `FFMPEG__PATH`, `FFMPEG__FRAME_RATE`, `FFMPEG__QUALITY` | 视频抽帧参数 |
| 视频去重 | `VIDEO__DEDUP_MODE`, `VIDEO__SCENE_THRESHOLD` | 预留视频帧去重配置 |

---

## 注意事项

- 当前 OCR 默认使用 **PaddleCloud 在线接口**，生产环境请配置真实 `OCR__PADDLE_CLOUD__TOKEN`；`job_url`、`model` 及可选功能开关（`use_doc_orientation_classify`、`use_doc_unwarping`、`use_chart_recognition`）可在 `conf/config.yaml` 中调整。
- 大文件上传会流式写入临时目录，避免一次性加载到内存。
- 解析任务默认异步执行；HTTP 同步解析仅用于调试或小文件场景。
- 所有真实密钥请通过环境变量注入，不要写入 `config.yaml` 或提交到 Git。
