# llm-construct-question Docker 生产部署实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在现有服务器上并行部署新版本 `llm-construct-question:v2`，复用现有 MySQL/Redis/MinIO，使用生产级 Docker 配置。

**Architecture:** 新增 `docker-compose.prod.yml` 单独管理应用容器；改造 `Dockerfile` 使用非 root 用户、`gunicorn` 生产服务器和健康检查；通过 `host.docker.internal` 访问宿主机已存在的中间件端口；敏感配置通过 `conf/.env.prod` 注入。

**Tech Stack:** Docker, Docker Compose, FastAPI/Uvicorn, Gunicorn, MySQL, Redis, MinIO

## Global Constraints

- 容器内应用端口固定为 `8081`。
- 宿主机暴露端口为 `8090`（`8090:8081`）。
- 复用现有中间件：MySQL `127.0.0.1:8306`、Redis `127.0.0.1:8369`、MinIO `127.0.0.1:8999`。
- 应用容器通过 `host.docker.internal` 访问宿主机中间件；Linux 下需 `extra_hosts: ["host.docker.internal:host-gateway"]`。
- MinIO bucket 沿用旧版本 `llm-construct`，由 `OssClient.ensure_bucket()` 自动保证存在。
- Redis 使用 `DB 10` 和新队列名 `edu_construct_parse_queue_v2`，避免与旧版本任务队列冲突。
- 真实密钥不提交 Git；`conf/.env.prod` 加入 `.gitignore`。

---

## File Structure

| 文件 | 操作 | 说明 |
|---|---|---|
| `Dockerfile` | 修改 | 生产化：非 root 用户、`gunicorn`、健康检查、暴露 8081、不复制敏感目录 |
| `docker-compose.prod.yml` | 创建 | 仅包含应用服务，复用现有中间件 |
| `conf/.env.prod` | 创建 | 生产环境敏感配置模板 |
| `.gitignore` | 修改 | 忽略 `conf/.env.prod` |

---

### Task 1: 创建 `conf/.env.prod` 生产环境配置模板

**Files:**
- Create: `conf/.env.prod`

**Interfaces:**
- Consumes: `libs/settings.py` 使用 `env_nested_delimiter="__"` 读取环境变量。
- Produces: 运行时的环境变量，覆盖 `conf/config.yaml` 的默认值。

- [ ] **Step 1: 写入 `.env.prod` 模板**

```dotenv
# 生产环境配置
# 请把 <真实密码>、<真实 AK>、<真实 SK>、<真实 token> 替换为实际值
# 此文件包含敏感信息，请勿提交 Git

SERVER__HOST=0.0.0.0
SERVER__PORT=8081

DATABASE__URL=mysql+pymysql://root:<真实密码>@host.docker.internal:8306/llm_construct?charset=utf8mb4

REDIS__HOST=host.docker.internal
REDIS__PORT=8369
REDIS__DB=10
REDIS__QUEUE_NAME=edu_construct_parse_queue_v2

OSS__ENDPOINT=http://host.docker.internal:8999
OSS__ACCESS_KEY=<真实 AK>
OSS__SECRET_KEY=<真实 SK>
OSS__BUCKET_NAME=llm-construct

OCR__PROVIDER=paddle-cloud
OCR__PADDLE_CLOUD__JOB_URL=https://paddleocr.aistudio-app.com/api/v2/ocr/jobs
OCR__PADDLE_CLOUD__TOKEN=<真实 token>
OCR__PADDLE_CLOUD__MODEL=PaddleOCR-VL-1.6
OCR__PADDLE_CLOUD__USE_DOC_ORIENTATION_CLASSIFY=False
OCR__PADDLE_CLOUD__USE_DOC_UNWARPING=False
OCR__PADDLE_CLOUD__USE_CHART_RECOGNITION=False

FFMPEG__PATH=ffmpeg
FFMPEG__FRAME_RATE=1
FFMPEG__OUTPUT_FORMAT=jpg
FFMPEG__QUALITY=2

VIDEO__DEDUP_MODE=scene
VIDEO__SCENE_THRESHOLD=0.05
```

- [ ] **Step 2: 确认文件已创建**

Run: `ls -la conf/.env.prod`
Expected: 文件存在，大小大于 0。

- [ ] **Step 3: Commit**

```bash
git add conf/.env.prod
git commit -m "chore(conf): add production env template"
```

---

### Task 2: 创建 `docker-compose.prod.yml`

**Files:**
- Create: `docker-compose.prod.yml`

**Interfaces:**
- Consumes: `conf/.env.prod` 提供环境变量；宿主机的 `8306`、`8369`、`8999` 端口必须可达。
- Produces: 名为 `llm-construct-question-v2` 的容器，监听宿主机 `8090` 端口。

- [ ] **Step 1: 写入 `docker-compose.prod.yml`**

```yaml
services:
  app:
    container_name: llm-construct-question-v2
    image: llm-construct-question:v2
    build:
      context: .
      dockerfile: Dockerfile
    ports:
      - "8090:8081"
    env_file:
      - conf/.env.prod
    extra_hosts:
      - "host.docker.internal:host-gateway"
    restart: unless-stopped
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:8081/health"]
      interval: 30s
      timeout: 5s
      retries: 3
      start_period: 10s
```

- [ ] **Step 2: 验证 YAML 语法**

Run: `docker compose -f docker-compose.prod.yml config`
Expected: 输出解析后的配置，无报错。

- [ ] **Step 3: Commit**

```bash
git add docker-compose.prod.yml
git commit -m "chore(deploy): add production docker compose for app only"
```

---

### Task 3: 改造 `Dockerfile`

**Files:**
- Modify: `Dockerfile`

**Interfaces:**
- Consumes: `requirements.txt`、项目源码。
- Produces: 生产镜像 `llm-construct-question:v2`，暴露 `8081`，以非 root 用户运行，使用 `gunicorn` + `uvicorn` worker。

- [ ] **Step 1: 重写 `Dockerfile`**

```dockerfile
FROM python:3.10.12-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    gcc \
    libglib2.0-0 \
    libsm6 \
    libxext6 \
    libxrender-dev \
    libgomp1 \
    curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

RUN groupadd -r app && useradd -r -g app app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt \
    && pip install --no-cache-dir gunicorn

COPY --chown=app:app . .

USER app

EXPOSE 8081

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
  CMD curl -f http://localhost:8081/health || exit 1

CMD ["gunicorn", "-w", "2", "-k", "uvicorn.workers.UvicornWorker", "-b", "0.0.0.0:8081", "service.main:app"]
```

- [ ] **Step 2: 验证 Dockerfile 语法**

Run: `docker build -t llm-construct-question:v2-test .`
Expected: 镜像构建成功，无报错。

- [ ] **Step 3: Commit**

```bash
git add Dockerfile
git commit -m "feat(deploy): productionize Dockerfile with gunicorn, non-root user, healthcheck"
```

---

### Task 4: 更新 `.gitignore`

**Files:**
- Modify: `.gitignore`

**Interfaces:**
- Produces: Git 忽略 `conf/.env.prod`，避免提交敏感信息。

- [ ] **Step 1: 检查并追加忽略规则**

如果 `.gitignore` 中已存在 `conf/.env` 或类似规则，追加 `conf/.env.prod`：

```gitignore
# Environment variables with secrets
conf/.env
conf/.env.prod
```

- [ ] **Step 2: 验证 Git 忽略生效**

Run: `git check-ignore -v conf/.env.prod`
Expected: 显示匹配的忽略规则。

- [ ] **Step 3: Commit**

```bash
git add .gitignore
git commit -m "chore(git): ignore production env file"
```

---

### Task 5: 本地构建并验证镜像

**Files:**
- 无需修改文件。

**Interfaces:**
- Consumes: `Dockerfile`、`docker-compose.prod.yml`、`conf/.env.prod`。

- [ ] **Step 1: 确认本地中间件已启动（仅本地验证需要）**

如果本地没有现成中间件，临时使用原 `docker-compose.yml`：

```bash
docker compose up -d mysql redis minio-app
```

- [ ] **Step 2: 准备本地 `.env.prod` 副本**

复制并修改本地值（仅用于本地验证）：

```bash
cp conf/.env.prod conf/.env.local
cp conf/.env.local conf/.env.prod
```

编辑 `conf/.env.prod`，把中间件地址改回本地 Docker 地址：

```dotenv
DATABASE__URL=mysql+pymysql://root:root@host.docker.internal:3306/llm_construct?charset=utf8mb4
REDIS__HOST=host.docker.internal
REDIS__PORT=6379
REDIS__DB=10
OSS__ENDPOINT=http://host.docker.internal:9000
OSS__ACCESS_KEY=minioadmin
OSS__SECRET_KEY=minioadmin
OSS__BUCKET_NAME=llm-construct
```

- [ ] **Step 3: 构建并启动**

```bash
docker compose -f docker-compose.prod.yml up -d --build
```

- [ ] **Step 4: 健康检查**

```bash
curl http://localhost:8090/health
```

Expected: `{"status":"ok"}`

- [ ] **Step 5: 停止并清理本地验证容器**

```bash
docker compose -f docker-compose.prod.yml down
```

- [ ] **Step 6: 恢复生产 `.env.prod`**

```bash
mv conf/.env.local conf/.env.prod
```

---

### Task 6: 服务器部署

**Files:**
- 无需修改文件。

**Interfaces:**
- Consumes: 已构建镜像 `llm-construct-question:v2`、已填写真实的 `conf/.env.prod`。

- [ ] **Step 1: 在 MySQL 中创建数据库**

```bash
mysql -h127.0.0.1 -P8306 -uroot -p<真实密码> -e "CREATE DATABASE IF NOT EXISTS llm_construct CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;"
```

- [ ] **Step 2: 确认 `conf/.env.prod` 已填写真实值**

重点检查：
- `DATABASE__URL` 中的密码
- `OSS__ACCESS_KEY`、`OSS__SECRET_KEY`
- `OCR__PADDLE_CLOUD__TOKEN`

- [ ] **Step 3: 在服务器上构建镜像**

```bash
docker build -t llm-construct-question:v2 .
```

- [ ] **Step 4: 启动应用**

```bash
docker compose -f docker-compose.prod.yml up -d
```

- [ ] **Step 5: 验证服务**

```bash
curl http://127.0.0.1:8090/health
```

Expected: `{"status":"ok"}`

- [ ] **Step 6: 查看日志**

```bash
docker logs -f llm-construct-question-v2
```

确认无连接错误（MySQL、Redis、MinIO）。

---

## Self-Review

### Spec Coverage

| 设计点 | 对应任务 |
|---|---|
| 新增 `docker-compose.prod.yml` 仅含应用服务 | Task 2 |
| 复用现有 MySQL/Redis/MinIO | Task 1（环境变量）、Task 2（`extra_hosts`） |
| 容器端口 8081，宿主机端口 8090 | Task 2 |
| 通过 `host.docker.internal` 访问宿主机 | Task 1、Task 2 |
| Dockerfile 生产化 | Task 3 |
| `conf/.env.prod` 管理敏感配置 | Task 1、Task 4 |
| MinIO bucket 共用 `llm-construct` | Task 1 |
| Redis 队列隔离 | Task 1 |
| 本地构建验证 | Task 5 |
| 服务器部署步骤 | Task 6 |

### Placeholder Scan

- 无 `TBD`、`TODO`。
- 环境变量中的 `<真实密码>`、`<真实 AK>`、`<真实 SK>`、`<真实 token>` 是用户必须填写的真实凭证占位符，已加注释说明。
- 每个任务都包含具体命令和预期输出。

### Type Consistency

- 环境变量命名使用 `__` 分隔符，与 `libs/settings.py` 的 `env_nested_delimiter="__"` 一致。
- `OSS__BUCKET_NAME=llm-construct` 与 `libs/settings.py` 中 `OssSettings.bucket_name` 一致。
- `REDIS__QUEUE_NAME=edu_construct_parse_queue_v2` 是新的队列名，避免冲突。

---

## Execution Handoff

Plan complete and saved to `docs/superpowers/plans/2026-07-30-llm-construct-docker-deployment-plan.md`. Two execution options:

**1. Subagent-Driven (recommended)** - I dispatch a fresh subagent per task, review between tasks, fast iteration

**2. Inline Execution** - Execute tasks in this session using executing-plans, batch execution with checkpoints

Which approach?
