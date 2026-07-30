import json
import logging
import time
from io import BytesIO
from pathlib import Path
from typing import Any, Dict, List, Tuple

import requests

from service.ocr.base import OcrAdapter

logger = logging.getLogger(__name__)


class PaddleCloudAdapter(OcrAdapter):
    """PaddleOCR 云异步 API 适配器。

    使用 ``/api/v2/ocr/jobs`` 提交解析任务，轮询任务状态，
    完成后从 ``resultUrl.markdownUrl`` 下载 markdown 文本，
    若 ``markdownUrl`` 不存在则回退到 ``resultUrl.jsonUrl``。
    支持图片和 PDF。
    """

    DEFAULT_JOB_URL = "https://paddleocr.aistudio-app.com/api/v2/ocr/jobs"
    DEFAULT_POLL_INTERVAL = 2
    DEFAULT_POLL_TIMEOUT = 600

    def __init__(
        self,
        cfg,
        client: requests.Session | None = None,
        poll_interval: float | None = None,
        poll_timeout: float | None = None,
    ):
        # 当前使用异步 /api/v2/ocr/jobs 端点
        self.job_url = cfg.job_url or self.DEFAULT_JOB_URL
        self.api_key = cfg.api_key or cfg.token
        self.model = cfg.model
        self.optional_payload = json.dumps(
            {
                "useDocOrientationClassify": bool(cfg.use_doc_orientation_classify),
                "useDocUnwarping": bool(cfg.use_doc_unwarping),
                "useChartRecognition": bool(cfg.use_chart_recognition),
            },
            separators=(",", ":"),
        )
        self.poll_interval = poll_interval if poll_interval is not None else self.DEFAULT_POLL_INTERVAL
        self.poll_timeout = poll_timeout if poll_timeout is not None else self.DEFAULT_POLL_TIMEOUT
        self._client = client if client is not None else requests.Session()

    def _submit_job(self, file_path: str) -> str:
        path = Path(file_path)
        headers = {"Authorization": f"bearer {self.api_key}"}
        data = {"model": self.model, "optionalPayload": self.optional_payload}
        files = {"file": (path.name, BytesIO(path.read_bytes()))}
        resp = self._client.post(self.job_url, headers=headers, data=data, files=files, timeout=120)
        resp.raise_for_status()
        result = self._extract(resp.json(), "data") or {}
        job_id = result.get("jobId")
        if not job_id:
            raise RuntimeError(f"PaddleCloud OCR submit failed: no jobId in response: {resp.text}")
        return job_id

    def _poll_job(self, job_id: str) -> Tuple[str | None, str | None]:
        headers = {"Authorization": f"bearer {self.api_key}"}
        poll_url = f"{self.job_url}/{job_id}"
        deadline = time.time() + self.poll_timeout

        while time.time() < deadline:
            resp = self._client.get(poll_url, headers=headers, timeout=30)
            resp.raise_for_status()
            data = self._extract(resp.json(), "data") or {}
            state = data.get("state")

            if state == "done":
                result_url = data.get("resultUrl") or {}
                markdown_url = result_url.get("markdownUrl")
                json_url = result_url.get("jsonUrl")
                if not markdown_url and not json_url:
                    logger.warning(
                        "PaddleCloud OCR job %s done but no resultUrl: %s",
                        job_id,
                        resp.text,
                    )
                    raise RuntimeError(
                        f"PaddleCloud OCR job {job_id} done but no markdownUrl or jsonUrl"
                    )
                return markdown_url, json_url

            if state == "failed":
                error_msg = data.get("errorMsg") or "unknown error"
                raise RuntimeError(f"PaddleCloud OCR job {job_id} failed: {error_msg}")

            time.sleep(self.poll_interval)

        raise RuntimeError(f"PaddleCloud OCR job {job_id} polling timeout")

    def _fetch_markdown(self, url: str) -> str:
        resp = self._client.get(url, timeout=60)
        resp.raise_for_status()
        return resp.text

    def _fetch_json_result(self, url: str) -> str:
        resp = self._client.get(url, timeout=60)
        resp.raise_for_status()
        text = resp.text.strip()
        if not text:
            return ""

        all_texts: List[str] = []
        for line in text.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                data = json.loads(line)
            except json.JSONDecodeError:
                logger.warning("PaddleCloud jsonUrl line is not valid JSON: %s", line[:200])
                continue
            all_texts.extend(self._extract_markdown_texts(data))
        return "\n\n".join(all_texts)

    @staticmethod
    def _extract_markdown_texts(data: Dict[str, Any]) -> List[str]:
        result = data.get("result") if isinstance(data, dict) else None
        if isinstance(result, dict):
            layout_results = result.get("layoutParsingResults") or []
        else:
            layout_results = data.get("layoutParsingResults") or [] if isinstance(data, dict) else []

        texts: List[str] = []
        for item in layout_results:
            if not isinstance(item, dict):
                continue
            markdown = item.get("markdown")
            if isinstance(markdown, dict):
                text = markdown.get("text")
                if text:
                    texts.append(text)
        return texts

    @staticmethod
    def _extract(data: Dict[str, Any], key: str) -> Any:
        return data.get(key) if isinstance(data, dict) else None

    def _parse_file(self, file_path: str) -> str:
        job_id = self._submit_job(file_path)
        markdown_url, json_url = self._poll_job(job_id)
        if markdown_url:
            return self._fetch_markdown(markdown_url)
        if json_url:
            return self._fetch_json_result(json_url)
        raise RuntimeError(f"PaddleCloud OCR job {job_id} done but no markdownUrl or jsonUrl")

    def parse_image(self, image_path: str) -> str:
        return self._parse_file(image_path)

    def parse_pdf(self, pdf_path: str) -> str:
        return self._parse_file(pdf_path)
