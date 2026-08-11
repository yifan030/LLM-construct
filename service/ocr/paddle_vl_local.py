import logging
from io import BytesIO
from typing import Any, Iterable, List

from service.ocr.base import OcrAdapter

logger = logging.getLogger(__name__)

try:
    from paddleocr import PaddleOCRVL
except ImportError:  # pragma: no cover - installed in production container
    PaddleOCRVL = None  # type: ignore

# PIL.Image 仅在提取 markdown_images 时需要
try:
    from PIL.Image import Image as PILImage
except ImportError:  # pragma: no cover
    PILImage = None  # type: ignore


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
            kwargs["vl_rec_model_name"] = self.model_name

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
                md.get("markdown_texts", "") if isinstance(md, dict) else str(md)
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
            return md.get("markdown_texts", "") or ""
        if isinstance(md, str):
            return md
        return ""

    @staticmethod
    def _get_markdown_dict(res: Any) -> dict[str, Any]:
        md = getattr(res, "markdown", None)
        if isinstance(md, dict):
            return md
        return {"markdown_texts": str(md) if md is not None else ""}

    # ------------------------------------------------------------------
    # predict_markdown: 返回 markdown，图片自动上传 OSS 并替换引用
    # ------------------------------------------------------------------

    def predict_markdown(
        self,
        file_path: str,
        oss_client: Any = None,
        oss_prefix: str = "",
    ) -> list[dict[str, Any]]:
        """直接调用本地 OCR 模型，返回每页的 markdown 文本。

        嵌入图片自动上传到 OSS 并将 markdown 中的引用替换为预签名 URL。

        每个页面返回::

            {
                "markdown": "# Title\\n\\n...",   # 图片引用已替换为 OSS URL
                "images": [                        # 已上传的图片
                    {"name": "imgs/img_in_...jpg", "url": "http://minio/..."},
                ],
                "page_index": 0,
            }
        """
        try:
            results = list(self._pipeline.predict(file_path))
        except Exception as e:
            raise RuntimeError(
                f"PaddleVlLocal OCR failed for {file_path}: {e}"
            ) from e

        pages = [self._build_markdown_page(res) for res in results]
        if oss_client is not None:
            self._upload_and_replace(pages, oss_client, oss_prefix)
        return pages

    @staticmethod
    def _build_markdown_page(res: Any) -> dict[str, Any]:
        """将单个 PaddleOCRVLResult 转为 markdown + 图片 bytes。"""
        md_val = getattr(res, "markdown", None)
        if not isinstance(md_val, dict):
            return {"markdown": str(md_val) if md_val else "", "images": [], "page_index": -1}

        return {
            "markdown": md_val.get("markdown_texts", "") or "",
            "images": PaddleVlLocalAdapter._extract_image_bytes(md_val.get("markdown_images")),
            "page_index": md_val.get("page_index", -1),
        }

    @staticmethod
    def _extract_image_bytes(md_images: Any) -> list[dict[str, Any]]:
        """将 markdown_images 中的 PIL.Image 转为 PNG bytes。"""
        if not isinstance(md_images, dict) or not md_images:
            return []

        images: list[dict[str, Any]] = []
        for name, img in md_images.items():
            if PILImage is not None and isinstance(img, PILImage):
                buf = BytesIO()
                try:
                    img.save(buf, format="PNG")
                    data = buf.getvalue()
                except Exception:
                    logger.warning("Failed to encode image %s", name)
                    data = b""
                finally:
                    buf.close()
                images.append({"name": name, "data": data, "content_type": "image/png"})
            elif isinstance(img, bytes):
                images.append({"name": name, "data": img, "content_type": "image/png"})
            else:
                logger.warning("Unexpected image type for %s: %s", name, type(img).__name__)
        return images

    @staticmethod
    def _upload_and_replace(
        pages: list[dict[str, Any]],
        oss_client: Any,
        oss_prefix: str,
    ) -> None:
        """上传每页的嵌入图片到 OSS，并将 markdown 中的引用替换为预签名 URL。"""
        import tempfile
        from pathlib import Path as _Path

        for page in pages:
            images = page.get("images", [])
            if not images:
                continue

            uploaded: list[dict[str, Any]] = []
            for img in images:
                name: str = img.get("name", "")
                data: bytes = img.get("data", b"")
                content_type: str = img.get("content_type", "image/png")

                if not data:
                    uploaded.append({"name": name, "url": None})
                    continue

                oss_path = f"{oss_prefix}/{page.get('page_index', 0)}/{name}"
                url = None
                tmp_name = None
                try:
                    with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp:
                        tmp.write(data)
                        tmp.flush()
                        tmp_name = tmp.name
                    oss_client.upload(tmp_name, oss_path)
                    url = oss_client.presigned_url(oss_path)
                except Exception:
                    logger.exception("Failed to upload OCR image %s", oss_path)
                finally:
                    if tmp_name is not None:
                        try:
                            _Path(tmp_name).unlink(missing_ok=True)
                        except Exception:
                            pass

                if url:
                    page["markdown"] = page["markdown"].replace(name, url)

                uploaded.append({"name": name, "url": url})

            page["images"] = uploaded
