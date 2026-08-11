# service/api/construct_question.py
"""在线解析接口 —— 直接调用本地 OCR 模型，返回 markdown 格式解析结果。"""
import logging
import tempfile
import uuid
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from pydantic import BaseModel

from libs.oss_client import OssClient
from libs.settings import Settings, get_settings
from service.ocr.factory import create_ocr_adapter
from service.ocr.paddle_vl_local import PaddleVlLocalAdapter

logger = logging.getLogger(__name__)

construct_question_router = APIRouter(tags=["construct_question"])

_OCR_IMAGES_PREFIX = "education/ocr_images"


class OcrPage(BaseModel):
    page_index: int
    markdown: str
    images: list[dict[str, Any]] = []


class OcrParseResponse(BaseModel):
    request_id: str
    status: str
    pages: list[OcrPage]


def _get_local_ocr(settings: Settings = Depends(get_settings)) -> PaddleVlLocalAdapter:
    adapter = create_ocr_adapter(settings)
    if not isinstance(adapter, PaddleVlLocalAdapter):
        raise HTTPException(
            status_code=400,
            detail=(
                f"online ocr parse requires paddle-vl-local provider, "
                f"current provider is {settings.ocr.provider}"
            ),
        )
    return adapter


def _get_oss_client(settings: Settings = Depends(get_settings)) -> OssClient:
    return OssClient(settings)


def _safe_suffix(filename: str | None) -> str:
    if not filename:
        raise HTTPException(status_code=400, detail="filename is required")
    suffix = Path(filename).suffix
    if not suffix:
        raise HTTPException(status_code=400, detail="file must have an extension")
    return suffix.lower()


@construct_question_router.post(
    "/construct-question/ocr-parse",
    response_model=OcrParseResponse,
    summary="在线 OCR 解析（Markdown）",
    description=(
        "上传图片（jpg/png/bmp/tiff）或 PDF 文件，"
        "直接调用本地 PaddleOCR-VL 模型进行同步解析，"
        "返回每页的 markdown 文本，文档内的嵌入图片自动上传至 OSS 并替换为预签名 URL。"
    ),
)
def ocr_parse(
    file: UploadFile = File(...),
    ocr: PaddleVlLocalAdapter = Depends(_get_local_ocr),
    oss: OssClient = Depends(_get_oss_client),
):
    request_id = str(uuid.uuid4())
    suffix = _safe_suffix(file.filename)

    with tempfile.NamedTemporaryFile(
        suffix=suffix, prefix=f"ocr_parse_{request_id}_", delete=False
    ) as tmp:
        try:
            chunk_size = 8192
            while True:
                chunk = file.file.read(chunk_size)
                if not chunk:
                    break
                tmp.write(chunk)
            tmp.flush()
            tmp_path = tmp.name
        except Exception:
            raise HTTPException(status_code=400, detail="failed to read uploaded file")

    try:
        pages = ocr.predict_markdown(
            tmp_path,
            oss_client=oss,
            oss_prefix=f"{_OCR_IMAGES_PREFIX}/{request_id}",
        )
    except RuntimeError as e:
        logger.error("ocr_parse request=%s error: %s", request_id, e)
        raise HTTPException(status_code=500, detail=str(e))
    except Exception as e:
        logger.error("ocr_parse request=%s unexpected error: %s", request_id, e)
        raise HTTPException(status_code=500, detail=f"ocr parse failed: {e}")
    finally:
        try:
            Path(tmp_path).unlink(missing_ok=True)
        except OSError:
            logger.warning(
                "ocr_parse request=%s failed to clean up temp file %s",
                request_id, tmp_path,
            )

    return OcrParseResponse(request_id=request_id, status="done", pages=pages)
