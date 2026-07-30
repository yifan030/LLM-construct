# llm-construct-question Docker 生产部署设计

> 状态：待实现  
> 目标：在现有服务器上并行部署新版本 `llm-construct-question`，复用现有 MySQL/Redis/MinIO 中间件。

---

## 1. 背景与目标

- 项目为 FastAPI 应用，依赖 MySQL、Redis、MinIO。
- 服务器上已有 `llm-construct-1`（镜像 `llm-construct:v4.4.1`）在运行。
- 本次部署**不替换**现有容器，而是并行运行新版本。
- 复用现有中间件实例：
  - MySQL：`mysql_hugegraph`（宿主机 `127.0.0.1:8306`）
  - Redis：`redis`（宿主机 `127.0.0.1:8369`）
  - MinIO：`minio-oss`（宿主机 `127.0.0.1:8999`）

---

## 2. 架构决策

### 2.1 应用容器

- 镜像名：`llm-construct-question:v2`
- 容器名：`llm-construct-question-v2`
- 容器内监听端口：`8081`
- 宿主机暴露端口：`8090`（映射 `8090:8081`）

> 选择 8090 是为了避免与现有 `llm-construct-1` 以及宿主机上 `8081`（milvus-attu）冲突。

### 2.2 网络访问方式

应用容器通过 `host.docker.internal` 访问宿主机上的中间件。

- Linux 服务器需要在 compose 文件中添加：
  ```yaml
  extra_hosts:
    - "host.docker.internal:host-gateway"
  ```
- 配置中的数据库、Redis、MinIO 地址均改为 `host.docker.internal` 加对应端口。

### 2.3 配置管理

- 新增 `conf/.env.prod`，存放生产环境敏感配置。
- 通过 `docker compose -f docker-compose.prod.yml up` 自动加载 `conf/.env.prod`。
- 真实密钥不提交 Git；`.env.prod` 加入 `.gitignore`。

### 2.4 OCR 模式

- 默认使用 `paddle-cloud` 在线 OCR，容器无需 GPU。
- 后续如需切换 `paddle-vl-local`，仅修改环境变量即可：
  - `OCR__PROVIDER=paddle-vl-local`
  - `OCR__PADDLE_VL_LOCAL__SERVER_URL=http://paddleocr-vlm-server:8080/v1`
  - 需将应用容器加入 `paddleocr-vlm-server` 所在 Docker 网络（本设计暂不实现，作为后续扩展项）。

---

## 3. 文件改动

### 3.1 新增 `docker-compose.prod.yml`

只包含应用服务，不再定义 MySQL/Redis/MinIO，避免误启动新的中间件实例。

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

### 3.2 新增 `conf/.env.prod`

```dotenv
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
OSS__BUCKET_NAME=llm-construct-v2

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

> `REDIS__DB=10` 与 `OSS__BUCKET_NAME=llm-construct-v2` 是为了避免与现有 `llm-construct-1` 的任务队列和存储桶冲突。

### 3.3 改造 `Dockerfile`

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

主要改动：
- 基础镜像加 `curl` 用于健康检查。
- 增加 `gunicorn` 作为生产 WSGI/ASGI 服务器。
- 增加非 root 用户 `app`。
- `EXPOSE 8081` 与配置一致。
- 增加 `HEALTHCHECK`。
- 移除 `python -m service.main` 的开发模式启动（含 `reload=True`）。

### 3.4 `.gitignore`

确认已包含：

```gitignore
conf/.env.prod
```

---

## 4. 部署步骤

1. 在 MySQL `mysql_hugegraph` 实例中创建数据库：
   ```sql
   CREATE DATABASE IF NOT EXISTS llm_construct CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
   ```
2. 复制示例配置并填写真实值：
   ```bash
   cp conf/.env conf/.env.prod
   # 编辑 conf/.env.prod，替换 <真实密码>、<真实 AK/SK/token>
   ```
3. 构建镜像：
   ```bash
   docker build -t llm-construct-question:v2 .
   ```
4. 启动应用：
   ```bash
   docker compose -f docker-compose.prod.yml up -d
   ```
5. 验证：
   ```bash
   curl http://<服务器IP>:8090/health
   ```

---

## 5. 安全与运维建议

- 真实密钥仅保存在 `conf/.env.prod`，不提交 Git。
- 容器以非 root 用户运行。
- 对外只暴露 `8090`；中间件端口已存在且不应再额外暴露。
- 如需公网访问，建议在现有 Nginx（如 `kg-nginx`）上反代到 `127.0.0.1:8090`，并配置 HTTPS。
- 日志持久化：可将容器 `/app/logs` 挂载到宿主机目录，避免重启丢失。

---

## 6. 后续扩展项

- **本地 GPU OCR**：切换 `OCR__PROVIDER` 后，将应用容器加入 `paddleocr-vlm-server` 所在网络。
- **日志收集**：接入现有日志方案（如 ELK 或宿主机日志目录）。
- **CI/CD**：构建镜像步骤可放到 GitHub Actions / GitLab CI。

---

## 7. 待确认清单

- [ ] MySQL root 密码已填入 `conf/.env.prod`。
- [ ] MinIO `llm-construct-v2` bucket 权限已配置。
- [ ] PaddleCloud token 已填入 `conf/.env.prod`。
- [ ] 防火墙/安全组已放行 `8090`（如需要外部访问）。
