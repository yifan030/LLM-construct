# service/api/files.py
import uuid
from typing import Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from pydantic import BaseModel
from sqlalchemy.orm import Session

from core.models import EduConstructFile
from libs.db import get_db_session
from libs.oss_client import OssClient
from libs.settings import get_settings
from service.worker.scheduler import Scheduler

router = APIRouter(tags=["files"])


class RegisterRequest(BaseModel):
    file_name: str
    file_type: str
    oss_path: str
    file_size: Optional[int] = None
    group_name: Optional[str] = None


class FileResponse(BaseModel):
    file_id: str
    status: str


def get_oss_client():
    return OssClient(get_settings())


def get_scheduler():
    return Scheduler(get_settings())


@router.post("/files/upload", response_model=FileResponse)
def upload_file(
    file: UploadFile = File(...),
    group_name: Optional[str] = Form(None),
    oss_client: OssClient = Depends(get_oss_client),
    scheduler: Scheduler = Depends(get_scheduler),
    session: Session = Depends(get_db_session),
):
    settings = get_settings()
    file_id = str(uuid.uuid4())
    ext = file.filename.split(".")[-1] if "." in file.filename else ""
    oss_path = f"education/uploads/{file_id}/{file.filename}"

    content = file.file.read()
    local_tmp = f"/tmp/{file_id}_{file.filename}"
    with open(local_tmp, "wb") as f:
        f.write(content)

    oss_client.upload(local_tmp, oss_path)

    record = EduConstructFile(
        file_id=file_id,
        file_name=file.filename,
        file_type=ext.lower() if ext in {"mp4", "ts", "pdf"} else "unknown",
        file_storage_path=oss_path,
        file_size=len(content),
        group_name=group_name,
    )
    session.add(record)
    session.commit()

    scheduler.enqueue(file_id=record.file_id, file_type=record.file_type, oss_path=oss_path)
    return FileResponse(file_id=file_id, status="pending")


@router.post("/files/register", response_model=FileResponse)
def register_file(
    req: RegisterRequest,
    scheduler: Scheduler = Depends(get_scheduler),
    session: Session = Depends(get_db_session),
):
    file_id = str(uuid.uuid4())
    record = EduConstructFile(
        file_id=file_id,
        file_name=req.file_name,
        file_type=req.file_type,
        file_storage_path=req.oss_path,
        file_size=req.file_size,
        group_name=req.group_name,
    )
    session.add(record)
    session.commit()

    scheduler.enqueue(file_id=file_id, file_type=req.file_type, oss_path=req.oss_path)
    return FileResponse(file_id=file_id, status="pending")


@router.get("/files/{file_id}")
def get_file(file_id: str, session: Session = Depends(get_db_session)):
    record = session.query(EduConstructFile).filter_by(file_id=file_id).first()
    if not record:
        raise HTTPException(status_code=404, detail="file not found")
    return {
        "file_id": record.file_id,
        "file_name": record.file_name,
        "file_type": record.file_type,
        "parse_status": record.parse_status,
        "file_storage_path": record.file_storage_path,
        "parsed_text_path": record.parsed_text_path,
        "frame_count": record.frame_count,
        "error_msg": record.error_msg,
        "created_at": record.created_at.isoformat() if record.created_at else None,
    }


@router.post("/files/{file_id}/parse")
def parse_file(
    file_id: str,
    sync: bool = Query(False),
    scheduler: Scheduler = Depends(get_scheduler),
    session: Session = Depends(get_db_session),
):
    record = session.query(EduConstructFile).filter_by(file_id=file_id).first()
    if not record:
        raise HTTPException(status_code=404, detail="file not found")

    if sync:
        scheduler.direct_parse(
            file_id=file_id, file_type=record.file_type, oss_path=record.file_storage_path
        )
        return {"file_id": file_id, "status": "completed"}

    scheduler.enqueue(
        file_id=file_id, file_type=record.file_type, oss_path=record.file_storage_path, force=True
    )
    return {"file_id": file_id, "status": "pending"}


@router.get("/files/{file_id}/download")
def download_file(
    file_id: str,
    type: str = Query("parsed", enum=["original", "parsed"]),
    oss_client: OssClient = Depends(get_oss_client),
    session: Session = Depends(get_db_session),
):
    record = session.query(EduConstructFile).filter_by(file_id=file_id).first()
    if not record:
        raise HTTPException(status_code=404, detail="file not found")

    path = record.parsed_text_path if type == "parsed" else record.file_storage_path
    if not path:
        raise HTTPException(status_code=404, detail="file not available")

    url = oss_client.presigned_url(path)
    return {"file_id": file_id, "url": url}
