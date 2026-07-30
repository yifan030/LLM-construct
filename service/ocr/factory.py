from libs.settings import Settings
from service.ocr.base import OcrAdapter
from service.ocr.paddle_cloud import PaddleCloudAdapter
from service.ocr.paddle_vl_local import PaddleVlLocalAdapter


def create_ocr_adapter(settings: Settings) -> OcrAdapter:
    if settings.ocr.provider == "paddle-cloud":
        return PaddleCloudAdapter(settings.ocr.paddle_cloud)
    elif settings.ocr.provider == "paddle-vl-local":
        return PaddleVlLocalAdapter(settings.ocr.paddle_vl_local)
    else:
        raise ValueError(f"unsupported ocr provider: {settings.ocr.provider}")
