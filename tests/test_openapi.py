import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent


def test_openapi_json_exists_and_is_valid():
    path = ROOT / "openapi.json"
    assert path.exists(), "openapi.json should exist at project root"
    spec = json.loads(path.read_text(encoding="utf-8"))
    assert spec.get("openapi") == "3.1.0"
    assert "/health" in spec["paths"]
    assert "/api/edu/files/upload" in spec["paths"]
    assert "/api/edu/files/register" in spec["paths"]
    assert "/api/edu/files/{file_id}" in spec["paths"]
    assert "/api/edu/files/{file_id}/download" in spec["paths"]
    assert "/api/edu/construct-question/ocr-parse" in spec["paths"]
    assert "FileResponse" in spec["components"]["schemas"]
    assert "OcrParseResponse" in spec["components"]["schemas"]
    assert "OcrPage" in spec["components"]["schemas"]
    assert "RegisterRequest" in spec["components"]["schemas"]
