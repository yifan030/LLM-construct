# service/api/files.py
import hashlib
import os
import re
import tempfile
import uuid
from pathlib import Path
from typing import Literal, Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from pydantic import BaseModel
from sqlalchemy.orm import Session

from core.models import EduConstructFile
from libs.db import get_db_session
from libs.oss_client import OssClient
from libs.settings import get_settings
from service.worker.scheduler import Scheduler

router = APIRouter(tags=["files"])


_SAFE_FILENAME_RE = re.compile(r'^[^/\\<>:"|?*\x00-\x1f][^\\<>:"|?*\x00-\x1f]*$')


class RegisterRequest(BaseModel):
    file_name: str
    file_type: Literal["video", "pdf", "image"]
    oss_path: str
    file_size: Optional[int] = None
    group_name: Optional[str] = None
    category: Optional[str] = None
    paper_file_id: Optional[str] = None


class FileResponse(BaseModel):
    file_id: str
    status: str
    paper_id: Optional[str] = None


def _safe_filename(filename: Optional[str]) -> str:
    if not filename:
        raise HTTPException(status_code=400, detail="filename is required")
    name = Path(filename).name
    if not name or name in (".", "..") or not _SAFE_FILENAME_RE.match(name):
        raise HTTPException(status_code=400, detail="invalid filename")
    return name


def _derive_file_type(filename: str) -> Literal["video", "pdf", "image", "unknown"]:
    ext = filename.split(".")[-1].lower() if "." in filename else ""
    if ext in {"mp4", "ts"}:
        return "video"
    if ext == "pdf":
        return "pdf"
    if ext in {"jpg", "jpeg", "png"}:
        return "image"
    return "unknown"


def _gen_content_hash(raw: bytes) -> str:
    """原始文件字节 → 内容指纹（裸 32 位 hex，无前缀）。

    与 llm-extract 的 ``libs.id_gen.gen_content_hash_bytes`` 保持一致，保证同一
    原始文件在两个服务中派生出相同的 content_hash / paper_id。
    """
    return hashlib.md5(raw).hexdigest()


def _paper_id_from_content_hash(content_hash: str) -> str:
    """内容指纹 → 试卷 ID，格式 ``paper_{32 位 hex}``。"""
    return f"paper_{content_hash}"


def get_oss_client():
    return OssClient(get_settings())


def get_scheduler():
    return Scheduler(get_settings())


_CATEGORIES = {"paper", "answer", "answer_sheet"}


@router.post("/files/upload", response_model=FileResponse)
def upload_file(
    file: UploadFile = File(...),
    group_name: Optional[str] = Form(None),
    category: Optional[str] = Form(None),
    paper_file_id: Optional[str] = Form(None),
    oss_client: OssClient = Depends(get_oss_client),
    scheduler: Scheduler = Depends(get_scheduler),
    session: Session = Depends(get_db_session),
):
    if category is None:
        category = "paper"
    if category not in _CATEGORIES:
        raise HTTPException(status_code=400, detail=f"invalid category: {category}")
    if category in {"answer", "answer_sheet"} and not paper_file_id:
        raise HTTPException(status_code=400, detail=f"{category} 需要 paper_file_id")

    file_id = str(uuid.uuid4())
    safe_name = _safe_filename(file.filename)
    file_type = _derive_file_type(safe_name)

    if category == "paper":
        base = f"education/uploads/paper/{file_id}"
    else:
        base = f"education/uploads/{category}/{paper_file_id}/{file_id}"
    oss_path = f"{base}/{safe_name}"

    md5 = hashlib.md5()
    with tempfile.TemporaryDirectory(prefix=f"upload_{file_id}_") as tmpdir:
        local_tmp = Path(tmpdir) / safe_name
        with open(local_tmp, "wb") as tmp:
            while True:
                chunk = file.file.read(1024 * 1024)
                if not chunk:
                    break
                tmp.write(chunk)
                md5.update(chunk)
        file_size = os.path.getsize(local_tmp)
        content_hash = md5.hexdigest()
        oss_client.upload(str(local_tmp), oss_path)

    record = EduConstructFile(
        file_id=file_id,
        file_name=safe_name,
        file_type=file_type,
        file_storage_path=oss_path,
        file_size=file_size,
        group_name=group_name,
        category=category,
        paper_file_id=paper_file_id,
        content_hash=content_hash,
    )
    session.add(record)
    session.commit()

    scheduler.enqueue(file_id=record.file_id, file_type=record.file_type, oss_path=oss_path)

    if category == "paper":
        paper_id = _paper_id_from_content_hash(content_hash)
    else:
        # answer / answer_sheet：paper_id 指所属试卷，反查父试卷的 content_hash 推导
        parent = (
            session.query(EduConstructFile).filter_by(file_id=paper_file_id).first()
        )
        paper_id = (
            _paper_id_from_content_hash(parent.content_hash)
            if parent and parent.content_hash
            else None
        )
    return FileResponse(file_id=file_id, status="pending", paper_id=paper_id)


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
        category=req.category,
        paper_file_id=req.paper_file_id,
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
        "parse_stage": record.parse_stage,
        "parse_progress": record.parse_progress,
        "file_storage_path": record.file_storage_path,
        "parsed_text_path": record.parsed_text_path,
        "frame_count": record.frame_count,
        "failed_frames": record.video_meta.failed_frames if record.video_meta else None,
        "error_msg": record.error_msg,
        "created_at": record.created_at.isoformat() if record.created_at else None,
    }


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
