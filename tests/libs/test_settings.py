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
