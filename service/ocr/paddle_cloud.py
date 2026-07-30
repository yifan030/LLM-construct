import base64
from pathlib import Path
from typing import Any, Dict

import requests

from service.ocr.base import OcrAdapter


class PaddleCloudAdapter(OcrAdapter):
    def __init__(self, cfg):
        self.base_url = cfg.base_url or cfg.job_url
        self.api_key = cfg.api_key or cfg.token
        self.model = cfg.model

    def _call_api(self, payload: Dict[str, Any]) -> str:
        headers = {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}
        resp = requests.post(self.base_url, json=payload, headers=headers, timeout=120)
        resp.raise_for_status()
        data = resp.json()
        # 根据实际 API 响应结构调整
        return data.get("result", "")

    def parse_image(self, image_path: str) -> str:
        b64 = base64.b64encode(Path(image_path).read_bytes()).decode()
        payload = {"model": self.model, "image": b64}
        return self._call_api(payload)

    def parse_pdf(self, pdf_path: str) -> str:
        b64 = base64.b64encode(Path(pdf_path).read_bytes()).decode()
        payload = {"model": self.model, "pdf": b64}
        return self._call_api(payload)
