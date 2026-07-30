# tests/libs/test_settings.py
from libs.settings import get_settings, Settings


def test_settings_loads_config():
    get_settings.cache_clear()
    s = get_settings()
    assert s.server.port == 8082
    assert s.redis.queue_name == "edu_construct_parse_queue"
    assert s.ocr.provider == "paddle-cloud"
    assert s.video.dedup_mode == "scene"
    assert s.video.scene_threshold == 0.05
    assert s.video.hash_size == 8
    assert s.video.hash_threshold == 8


def test_settings_env_override(monkeypatch):
    monkeypatch.setenv("DATABASE__URL", "mysql+pymysql://env/env")
    get_settings.cache_clear()
    s = get_settings()
    assert s.database.url == "mysql+pymysql://env/env"
