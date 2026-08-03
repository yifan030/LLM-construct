import os

import pytest

from libs.db import create_tables
from libs.oss_client import OssClient
from libs.redis_client import RedisClient
from libs.settings import Settings


@pytest.fixture(scope="session", autouse=True)
def init_database():
    if os.getenv("SKIP_DB_INIT"):
        return
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
