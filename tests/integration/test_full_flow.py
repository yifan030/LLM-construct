import time
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from service.main import app


def test_upload_pdf_and_parse(tmp_path: Path):
    client = TestClient(app)

    pdf = tmp_path / "math.pdf"
    try:
        import fitz
        doc = fitz.open()
        page = doc.new_page()
        page.insert_text((50, 50), "一元二次方程")
        doc.save(str(pdf))
        doc.close()
    except Exception:
        pytest.skip("fitz not available")

    with patch("service.main.create_ocr_adapter") as mock_factory:
        adapter = mock_factory.return_value
        adapter.parse_image.return_value = "一元二次方程"

        with client:
            with open(pdf, "rb") as f:
                resp = client.post("/api/v1/files/upload", files={"file": ("math.pdf", f, "application/pdf")})
            assert resp.status_code == 200
            file_id = resp.json()["file_id"]

            # 等待 consumer 处理
            for _ in range(30):
                status_resp = client.get(f"/api/v1/files/{file_id}")
                if status_resp.json()["parse_status"] == 2:
                    break
                time.sleep(1)

            assert status_resp.json()["parse_status"] == 2
            assert status_resp.json()["parsed_text_path"].endswith("math_parsed/math.md")
