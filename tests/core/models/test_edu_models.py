import uuid

from libs.db import engine, create_tables
from core.models import EduConstructFile, EduVideoMeta
from sqlalchemy.orm import Session


def test_create_tables():
    create_tables()


def test_crud_file_and_meta():
    create_tables()
    file_id = str(uuid.uuid4())
    with Session(engine) as session:
        f = EduConstructFile(
            file_id=file_id,
            file_name="demo.mp4",
            file_type="video",
            file_storage_path=f"education/uploads/{file_id}/demo.mp4",
            file_size=1024,
        )
        session.add(f)
        session.commit()

        m = EduVideoMeta(
            file_id=file_id,
            duration=120.5,
            resolution="1920x1080",
            fps=1,
            scene_threshold=0.05,
            dedup_mode="scene",
        )
        session.add(m)
        session.commit()

        found = session.query(EduConstructFile).filter_by(file_id=file_id).first()
        assert found.parse_status == 0
        assert found.video_meta.duration == 120.5
