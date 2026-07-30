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
    from libs.db_client import DatabaseClient
    DatabaseClient(engine=get_engine(), setup=True)
