from typing import Optional

from sqlalchemy import BIGINT, Integer, String, Text, DateTime, Index
from sqlalchemy.orm import Mapped, mapped_column, relationship

from core.models.base import Base, TimestampMixin


class EduConstructFile(Base, TimestampMixin):
    __tablename__ = "edu_construct_files"

    id: Mapped[int] = mapped_column(BIGINT, primary_key=True, autoincrement=True)
    file_id: Mapped[str] = mapped_column(String(200), unique=True, nullable=False)
    file_name: Mapped[str] = mapped_column(String(500), nullable=False)
    file_type: Mapped[str] = mapped_column(String(100), nullable=False)
    parse_status: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    parse_progress: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    parse_stage: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    file_storage_path: Mapped[str] = mapped_column(String(1000), nullable=False)
    file_size: Mapped[int] = mapped_column(BIGINT, nullable=True)
    group_name: Mapped[str] = mapped_column(String(200), nullable=True)
    category: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    paper_file_id: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    content_hash: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    parsed_text_path: Mapped[str] = mapped_column(String(1000), nullable=True)
    frame_count: Mapped[int] = mapped_column(Integer, nullable=True)
    error_msg: Mapped[str] = mapped_column(Text, nullable=True)
    deleted_at: Mapped[DateTime] = mapped_column(DateTime, nullable=True)

    video_meta: Mapped["EduVideoMeta"] = relationship(
        "EduVideoMeta", back_populates="file", uselist=False
    )

    __table_args__ = (
        Index("idx_parse_status", "parse_status"),
        Index("idx_group_name", "group_name"),
        Index("idx_category", "category"),
        Index("idx_created_at", "created_at"),
    )
