from abc import ABC, abstractmethod
from typing import Any


class OcrAdapter(ABC):
    @abstractmethod
    def parse_image(self, image_path: str) -> str:
        """对单张图片进行 OCR，返回 markdown/文本。"""
        ...

    @abstractmethod
    def parse_pdf(self, pdf_path: str) -> str:
        """对 PDF 进行 OCR，返回 markdown/文本。"""
        ...

    def predict_markdown(
        self,
        file_path: str,
        oss_client: Any = None,
        oss_prefix: str = "",
    ) -> list[dict[str, Any]]:
        """默认实现：调用 parse_image，返回单页结构（无图片上传）。

        子类（如 PaddleVlLocalAdapter）可覆盖以支持嵌入图片上传 OSS
        并替换 markdown 中的引用为预签名 URL。
        """
        markdown = self.parse_image(file_path)
        return [{"markdown": markdown, "images": [], "page_index": 0}]
