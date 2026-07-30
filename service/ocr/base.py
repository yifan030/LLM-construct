from abc import ABC, abstractmethod


class OcrAdapter(ABC):
    @abstractmethod
    def parse_image(self, image_path: str) -> str:
        """对单张图片进行 OCR，返回 markdown/文本。"""
        ...

    @abstractmethod
    def parse_pdf(self, pdf_path: str) -> str:
        """对 PDF 进行 OCR，返回 markdown/文本。"""
        ...
