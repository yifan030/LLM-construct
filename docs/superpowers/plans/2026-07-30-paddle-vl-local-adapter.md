# PaddleVlLocalAdapter Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement `service/ocr/paddle_vl_local.py` so the project can use a local `paddleocr genai_server` (vLLM backend) for image and PDF OCR.

**Architecture:** Add a small `PaddleVlLocalAdapter` that implements the existing `OcrAdapter` interface. It uses the `PaddleOCRVL` SDK client in `vllm-server` mode, calls `predict()` for images and PDFs, and returns merged markdown text. Settings and config are extended with pipeline/model options; unit tests mock the SDK.

**Tech Stack:** Python 3.10, FastAPI, Pydantic Settings, PaddleOCR SDK (`paddleocr>=3.4.0`), pytest.

## Global Constraints

- Adapter must implement `OcrAdapter` interface: `parse_image(image_path: str) -> str` and `parse_pdf(pdf_path: str) -> str`.
- Use `PaddleOCRVL(vl_rec_backend='vllm-server', vl_rec_server_url=cfg.server_url)` to connect to the local server.
- Return markdown text only; no JSON upload to OSS inside the adapter.
- `server_url` example: `http://127.0.0.1:8128/v1`.
- `pipeline_version` default: `"v1.5"`.
- Dependency: `paddleocr>=3.4.0`.

---

## File Structure

| File | Responsibility |
|---|---|
| `libs/settings.py` | Extend `PaddleVlLocalSettings` with `pipeline_version` and `model_name`. |
| `conf/config.yaml` | Add example values for `paddle_vl_local` settings. |
| `service/ocr/paddle_vl_local.py` | Implement `PaddleVlLocalAdapter` using `PaddleOCRVL`. |
| `tests/service/ocr/test_paddle_vl_local.py` | Unit tests mocking `PaddleOCRVL` and its result objects. |
| `requirements.txt` | Add `paddleocr>=3.4.0`. |

---

### Task 1: Extend Settings and Example Config

**Files:**
- Modify: `libs/settings.py:45-48`
- Modify: `conf/config.yaml:49-51`

**Interfaces:**
- Consumes: existing `PaddleVlLocalSettings` schema.
- Produces: `PaddleVlLocalSettings` now has `server_url`, `device`, `pipeline_version`, `model_name`.

- [ ] **Step 1: Add fields to `PaddleVlLocalSettings`**

```python
class PaddleVlLocalSettings(BaseSettings):
    server_url: str = ""
    device: str = "gpu:0"
    pipeline_version: str = "v1.5"
    model_name: str = ""
```

- [ ] **Step 2: Update `conf/config.yaml` example values**

```yaml
ocr:
  provider: paddle-cloud
  paddle_cloud:
    ...
  paddle_vl_local:
    server_url: "http://127.0.0.1:8128/v1"
    device: "gpu:0"
    pipeline_version: "v1.5"
    model_name: ""
```

- [ ] **Step 3: Verify settings load**

Run: `python -c "from libs.settings import Settings; print(Settings().ocr.paddle_vl_local)"`

Expected: prints a `PaddleVlLocalSettings` object with the new defaults.

- [ ] **Step 4: Commit**

```bash
git add libs/settings.py conf/config.yaml
git commit -m "feat(settings): extend paddle_vl_local settings with pipeline_version and model_name"
```

---

### Task 2: Implement `PaddleVlLocalAdapter`

**Files:**
- Modify: `service/ocr/paddle_vl_local.py` (replace placeholder)

**Interfaces:**
- Consumes: `cfg` of type `PaddleVlLocalSettings`.
- Produces: `PaddleVlLocalAdapter.parse_image(image_path: str) -> str` and `PaddleVlLocalAdapter.parse_pdf(pdf_path: str) -> str`.

- [ ] **Step 1: Implement the adapter**

Replace the contents of `service/ocr/paddle_vl_local.py` with:

```python
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
```

- [ ] **Step 2: Verify the module imports**

Run: `python -c "from service.ocr.paddle_vl_local import PaddleVlLocalAdapter; print(PaddleVlLocalAdapter)"`

Expected: prints class without error.

- [ ] **Step 3: Commit**

```bash
git add service/ocr/paddle_vl_local.py
git commit -m "feat(ocr): implement paddle-vl-local adapter with PaddleOCRVL SDK"
```

---

### Task 3: Add Unit Tests

**Files:**
- Create: `tests/service/ocr/test_paddle_vl_local.py`

**Interfaces:**
- Consumes: `PaddleVlLocalAdapter` from Task 2.
- Produces: passing tests covering image OCR, PDF OCR, empty results, and SDK errors.

- [ ] **Step 1: Write tests**

```python
from unittest.mock import MagicMock, patch

import pytest

from libs.settings import Settings
from service.ocr.paddle_vl_local import PaddleVlLocalAdapter


def _make_result(text: str):
    res = MagicMock()
    res.markdown = {"markdown_texts": text, "markdown_images": {}}
    return res


def _make_config():
    cfg = Settings().ocr.paddle_vl_local
    cfg.server_url = "http://localhost:8128/v1"
    return cfg


@patch("service.ocr.paddle_vl_local.PaddleOCRVL")
def test_parse_image_returns_concatenated_markdown(mock_cls):
    pipeline = MagicMock()
    pipeline.predict.return_value = [_make_result("line 1"), _make_result("line 2")]
    mock_cls.return_value = pipeline

    adapter = PaddleVlLocalAdapter(_make_config())
    result = adapter.parse_image("/tmp/frame.jpg")

    assert result == "line 1\n\nline 2"
    pipeline.predict.assert_called_once_with("/tmp/frame.jpg")


@patch("service.ocr.paddle_vl_local.PaddleOCRVL")
def test_parse_pdf_uses_concatenate_markdown_pages(mock_cls):
    pipeline = MagicMock()
    pipeline.predict.return_value = [_make_result("page 1"), _make_result("page 2")]
    pipeline.concatenate_markdown_pages.return_value = "merged markdown"
    mock_cls.return_value = pipeline

    adapter = PaddleVlLocalAdapter(_make_config())
    result = adapter.parse_pdf("/tmp/doc.pdf")

    assert result == "merged markdown"
    pipeline.predict.assert_called_once_with("/tmp/doc.pdf")
    pipeline.concatenate_markdown_pages.assert_called_once()


@patch("service.ocr.paddle_vl_local.PaddleOCRVL")
def test_parse_image_empty_result_returns_empty_string(mock_cls):
    pipeline = MagicMock()
    pipeline.predict.return_value = []
    mock_cls.return_value = pipeline

    adapter = PaddleVlLocalAdapter(_make_config())
    assert adapter.parse_image("/tmp/frame.jpg") == ""


@patch("service.ocr.paddle_vl_local.PaddleOCRVL")
def test_parse_image_wraps_sdk_error(mock_cls):
    pipeline = MagicMock()
    pipeline.predict.side_effect = RuntimeError("server down")
    mock_cls.return_value = pipeline

    adapter = PaddleVlLocalAdapter(_make_config())
    with pytest.raises(RuntimeError, match="PaddleVlLocal OCR failed"):
        adapter.parse_image("/tmp/frame.jpg")


@patch("service.ocr.paddle_vl_local.PaddleOCRVL")
def test_parse_pdf_falls_back_when_concatenate_unavailable(mock_cls):
    pipeline = MagicMock()
    pipeline.predict.return_value = [_make_result("page 1"), _make_result("page 2")]
    del pipeline.concatenate_markdown_pages
    mock_cls.return_value = pipeline

    adapter = PaddleVlLocalAdapter(_make_config())
    result = adapter.parse_pdf("/tmp/doc.pdf")

    assert result == "page 1\n\npage 2"
```

- [ ] **Step 2: Run the new tests**

Run: `pytest tests/service/ocr/test_paddle_vl_local.py -v`

Expected: all 5 tests pass.

- [ ] **Step 3: Commit**

```bash
git add tests/service/ocr/test_paddle_vl_local.py
git commit -m "test(ocr): add paddle-vl-local adapter unit tests"
```

---

### Task 4: Update Dependencies and Run Full OCR Test Suite

**Files:**
- Modify: `requirements.txt`

**Interfaces:**
- Consumes: all prior tasks.
- Produces: `requirements.txt` includes `paddleocr>=3.4.0`; all OCR tests pass.

- [ ] **Step 1: Add paddleocr to requirements**

Append to `requirements.txt`:

```text
paddleocr>=3.4.0
```

- [ ] **Step 2: Run OCR tests**

Run: `pytest tests/service/ocr/ -v`

Expected: all tests in `tests/service/ocr/` pass, including existing `test_ocr.py` and new `test_paddle_vl_local.py`.

- [ ] **Step 3: Commit**

```bash
git add requirements.txt
git commit -m "chore(deps): add paddleocr for local vl ocr adapter"
```

---

## Self-Review

**Spec coverage:**
- Adapter implements `OcrAdapter` interface → Task 2.
- Uses `PaddleOCRVL` SDK with `vllm-server` backend → Task 2.
- Supports image and PDF OCR with merged markdown → Tasks 2 and 3.
- No JSON upload to OSS → Task 2 returns text only.
- Settings extended with `pipeline_version`/`model_name` → Task 1.
- Error handling and tests → Tasks 2 and 3.

**Placeholder scan:**
- No TBD/TODO placeholders.
- All code snippets contain concrete implementation.

**Type consistency:**
- `parse_image` and `parse_pdf` signatures match `OcrAdapter`.
- `PaddleVlLocalSettings` fields are consistent across `libs/settings.py`, `conf/config.yaml`, and adapter usage.
