import logging
from typing import Any, Iterable, List

from service.ocr.base import OcrAdapter

logger = logging.getLogger(__name__)

try:
    from paddleocr import PaddleOCRVL
except ImportError:  # pragma: no cover - installed in production container
    PaddleOCRVL = None  # type: ignore


class PaddleVlLocalAdapter(OcrAdapter):
    """本地 paddleocr genai_server (vLLM backend) OCR 适配器。

    通过 PaddleOCRVL SDK 的 vllm-server 模式连接本地服务，
    对图片或 PDF 执行 OCR 并返回 markdown 文本。
    """

    def __init__(self, cfg):
        if PaddleOCRVL is None:
            raise RuntimeError(
                "paddleocr is not installed; required for paddle-vl-local provider"
            )

        self.server_url = cfg.server_url
        self.device = cfg.device
        self.pipeline_version = getattr(cfg, "pipeline_version", "v1.5")
        self.model_name = getattr(cfg, "model_name", None) or None

        kwargs: dict[str, Any] = {
            "pipeline_version": self.pipeline_version,
            "vl_rec_backend": "vllm-server",
            "vl_rec_server_url": self.server_url,
        }
        if self.model_name:
            kwargs["model_name"] = self.model_name

        self._pipeline = PaddleOCRVL(**kwargs)

    def parse_image(self, image_path: str) -> str:
        try:
            results = self._pipeline.predict(image_path)
        except Exception as e:
            raise RuntimeError(f"PaddleVlLocal OCR failed for image {image_path}: {e}") from e
        return self._extract_markdown(results)

    def parse_pdf(self, pdf_path: str) -> str:
        try:
            results = list(self._pipeline.predict(pdf_path))
        except Exception as e:
            raise RuntimeError(f"PaddleVlLocal OCR failed for pdf {pdf_path}: {e}") from e

        if not results:
            return ""

        markdowns = [self._get_markdown_dict(res) for res in results]
        try:
            return self._pipeline.concatenate_markdown_pages(markdowns)
        except AttributeError:
            logger.warning(
                "concatenate_markdown_pages not available; falling back to simple join"
            )
            return "\n\n".join(
                md.get("text", "") if isinstance(md, dict) else str(md)
                for md in markdowns
            )

    def _extract_markdown(self, results: Iterable[Any]) -> str:
        texts: List[str] = []
        for res in results:
            text = self._get_markdown_text(res)
            if text:
                texts.append(text)
        return "\n\n".join(texts)

    @staticmethod
    def _get_markdown_text(res: Any) -> str:
        md = getattr(res, "markdown", None)
        if isinstance(md, dict):
            return md.get("text", "") or ""
        if isinstance(md, str):
            return md
        return ""

    @staticmethod
    def _get_markdown_dict(res: Any) -> dict[str, Any]:
        md = getattr(res, "markdown", None)
        if isinstance(md, dict):
            return md
        return {"text": str(md) if md is not None else ""}
