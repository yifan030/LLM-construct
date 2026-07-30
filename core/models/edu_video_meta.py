from typing import Optional

from sqlalchemy import BIGINT, Float, Integer, String, Text, DateTime, ForeignKey, UniqueConstraint, JSON
from sqlalchemy.orm import Mapped, mapped_column, relationship

from core.models.base import Base, TimestampMixin


class EduVideoMeta(Base, TimestampMixin):
    __tablename__ = "edu_video_meta"

    id: Mapped[int] = mapped_column(BIGINT, primary_key=True, autoincrement=True)
    file_id: Mapped[str] = mapped_column(
        String(200), ForeignKey("edu_construct_files.file_id"), nullable=False
    )
    duration: Mapped[float] = mapped_column(Float, nullable=True)
    resolution: Mapped[str] = mapped_column(String(50), nullable=True)
    fps: Mapped[int] = mapped_column(Integer, nullable=True)
    scene_threshold: Mapped[float] = mapped_column(Float, nullable=True)
    dedup_mode: Mapped[str] = mapped_column(String(50), nullable=True)
    failed_frames: Mapped[Optional[list]] = mapped_column(JSON, nullable=True)
    frame_metadata_path: Mapped[str] = mapped_column(Text, nullable=True)

    file: Mapped["EduConstructFile"] = relationship(
        "EduConstructFile", back_populates="video_meta"
    )

    __table_args__ = (UniqueConstraint("file_id", name="uk_file_id"),)
