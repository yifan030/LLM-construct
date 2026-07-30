"""Database client wrapping SQLAlchemy engine and table creation."""
from typing import Optional

from sqlalchemy import Engine, create_engine

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
