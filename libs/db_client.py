from typing import Optional

from sqlalchemy import create_engine

from core.models.base import Base
from libs.settings import Settings, get_settings


class DatabaseClient:
    def __init__(self, settings: Optional[Settings] = None, setup: bool = True):
        self.settings = settings or get_settings()
        self.engine = create_engine(self.settings.database.url, pool_pre_ping=True)
        if setup:
            self.setup()

    def setup(self):
        Base.metadata.create_all(bind=self.engine)
