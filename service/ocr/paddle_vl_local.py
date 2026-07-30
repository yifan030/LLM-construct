from service.ocr.base import OcrAdapter


class PaddleVlLocalAdapter(OcrAdapter):
    """本地 paddle-vl 占位实现，后续替换为真实调用。"""

    def __init__(self, cfg):
        self.server_url = cfg.server_url
        self.device = cfg.device

    def parse_image(self, image_path: str) -> str:
        raise NotImplementedError("paddle-vl-local not ready yet")

    def parse_pdf(self, pdf_path: str) -> str:
        raise NotImplementedError("paddle-vl-local not ready yet")
