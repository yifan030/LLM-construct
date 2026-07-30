# 客户端实例化时自动初始化环境

## 目标

切换运行环境（如从服务器 MySQL/MinIO/Redis 切换到本地 Docker）后，不再需要手动创建数据库表、MinIO bucket 或验证 Redis 连接。所有中间件资源的初始化应在客户端实例化时自动、幂等地完成。

## 范围

本次设计覆盖三类中间件客户端：

1. **数据库（MySQL）**：自动创建 SQLAlchemy 定义的表结构。
2. **对象存储（MinIO）**：自动创建配置中指定的 bucket。
3. **Redis**：实例化时 ping 验证连接可达。

## 当前问题

- `create_tables()` 在 `service.main:lifespan` 中显式调用，DB 没有统一的“客户端”抽象。
- `OssClient.ensure_bucket()` 只在 `upload()` / `download()` 时惰性触发，若先调用 `object_exists()` 或 `presigned_url()` 可能遇到 bucket 不存在。
- `RedisClient` 仅保存连接参数，不验证服务是否可达。
- 切换到新环境后，需要手动确保 bucket、表等资源存在。

## 设计方案

### 1. 新增 `DatabaseClient`

位置：`libs/db_client.py`

```python
class DatabaseClient:
    def __init__(self, settings: Optional[Settings] = None, setup: bool = True):
        self.settings = settings or get_settings()
        self.engine = create_engine(self.settings.database.url, pool_pre_ping=True)
        if setup:
            self.setup()

    def setup(self):
        Base.metadata.create_all(bind=self.engine)
```

- `__init__` 创建 engine，并在 `setup=True` 时自动建表。
- `setup()` 保持与当前 `create_tables()` 相同的幂等行为。
- 测试可通过 `DatabaseClient(settings, setup=False)` 避免触发网络请求。

### 2. `OssClient` 自初始化

位置：`libs/oss_client.py`

```python
class OssClient:
    def __init__(self, settings: Optional[Settings] = None, setup: bool = True):
        ...
        if setup:
            self.ensure_bucket()
```

- 默认在实例化时创建 bucket。
- 新增 `setup: bool = True` 开关，便于测试传入 `setup=False` 避免网络请求。
- `ensure_bucket()` 保持幂等：`if not exists -> make_bucket`。

### 3. `RedisClient` 自初始化

位置：`libs/redis_client.py`

```python
class RedisClient:
    def __init__(self, settings: Optional[Settings] = None, setup: bool = True):
        ...
        if setup:
            self.client.ping()
```

- 默认在实例化时 ping 验证连接。
- 新增 `setup: bool = True` 开关，便于测试。

### 4. `service.main` 改造

`lifespan` 不再显式调用 `create_tables()`，改为实例化 `DatabaseClient`，其 `__init__` 会自动建表：

```python
@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    db_client = await asyncio.to_thread(DatabaseClient, settings)
    worker = await asyncio.to_thread(build_worker)
    redis_client = await asyncio.to_thread(RedisClient, settings)
    consumer = Consumer(settings=settings, redis_client=redis_client, worker=worker)
    await asyncio.to_thread(consumer.start)
    app.state.consumer = consumer
    app.state.worker = worker
    logger.info("application startup complete")
    yield
    await asyncio.to_thread(consumer.stop)
    logger.info("application shutdown complete")
```

`build_worker()` 中 `OssClient(settings)` 实例化时会自动创建 bucket。

### 5. 测试适配

- 现有测试 `tests/libs/test_oss_client.py` 中的 `client.ensure_bucket()` 可保留（幂等）或删除。
- 单元测试在 mock 客户端时应使用 `OssClient(settings, setup=False)` 或 patch `ensure_bucket`。
- `tests/conftest.py` 中的 `create_tables()` fixture 可替换为 `DatabaseClient(settings).setup()`，保持行为一致。

### 6. 错误处理

- 若 MySQL/MinIO/Redis 未启动，客户端在实例化或 `setup()` 时立即抛出异常，启动失败并给出明确错误。
- 所有初始化操作均为幂等：重复执行不会破坏已有数据。

## 验收标准

- [ ] 删除空数据库后启动服务，表结构自动创建。
- [ ] 删除 MinIO bucket 后启动服务，bucket 自动创建。
- [ ] Redis 未启动时，服务启动立即报错。
- [ ] 现有测试全部通过。
- [ ] 切换 `conf/.env` 到新的本地 Docker 配置后，无需手动创建任何资源即可启动。

## 影响文件

- `libs/db_client.py`（新增）
- `libs/db.py`（可能保留 `create_tables` 兼容，或迁移到 `DatabaseClient`）
- `libs/oss_client.py`
- `libs/redis_client.py`
- `service/main.py`
- `tests/conftest.py`
- `tests/libs/test_oss_client.py`
- `tests/service/test_main.py`
