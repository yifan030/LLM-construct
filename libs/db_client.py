"""Database client wrapping SQLAlchemy engine and table creation."""
from typing import Optional

from sqlalchemy import Engine, create_engine, inspect, text

from core.models.base import Base
from libs.settings import Settings, get_settings


class DatabaseClient:
    """Idempotent database initializer.

    Parameters
    ----------
    settings:
        Application settings. Defaults to the cached global settings.
    setup:
        Whether to create all tables on instantiation.
    engine:
        Optional SQLAlchemy engine to reuse. When omitted, a new engine is
        created from ``settings.database.url``.
    """

    def __init__(
        self,
        settings: Optional[Settings] = None,
        setup: bool = True,
        engine: Optional[Engine] = None,
    ):
        self.settings = settings or get_settings()
        self.engine = engine or create_engine(
            self.settings.database.url, pool_pre_ping=True
        )
        if setup:
            self.setup()

    def setup(self):
        """Create all tables if they do not already exist."""
        Base.metadata.create_all(bind=self.engine)
        self._migrate()

    def _migrate(self):
        """轻量幂等迁移：为已存在的 edu_construct_files 表补齐新增列。

        create_all 只建新表、不修改已有表，因此 category / paper_file_id
        两列需在此对存量库补齐（幂等，列存在则跳过）。
        """
        inspector = inspect(self.engine)
        if "edu_construct_files" not in inspector.get_table_names():
            return
        columns = {c["name"] for c in inspector.get_columns("edu_construct_files")}
        indexes = {i["name"] for i in inspector.get_indexes("edu_construct_files")}
        with self.engine.begin() as conn:
            if "category" not in columns:
                conn.execute(text(
                    "ALTER TABLE edu_construct_files ADD COLUMN category VARCHAR(20) NULL"
                ))
            if "paper_file_id" not in columns:
                conn.execute(text(
                    "ALTER TABLE edu_construct_files ADD COLUMN paper_file_id VARCHAR(200) NULL"
                ))
            if "idx_category" not in indexes:
                conn.execute(text(
                    "ALTER TABLE edu_construct_files ADD INDEX idx_category (category)"
                ))
