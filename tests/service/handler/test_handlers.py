import os
from pathlib import Path
from unittest.mock import patch

from service.handler.video_handler import VideoHandler
from service.handler.pdf_handler import PdfHandler
from libs.settings import Settings


def test_video_handler_extracts_frames(tmp_path: Path):
    handler = VideoHandler(Settings())
    video_path = tmp_path / "sample.mp4"
    # 用 ffmpeg 生成 1 秒测试视频
    os.system(
        f"ffmpeg -y -f lavfi -i testsrc=duration=1:size=320x240:rate=1 "
        f"-pix_fmt yuv420p {video_path} >/dev/null 2>&1"
    )
    frames = handler.extract_images(str(video_path), file_id="v1")
    assert len(frames) >= 1
    assert all(Path(f).exists() for f in frames)


def test_pdf_handler_extracts_pages(tmp_path: Path):
    handler = PdfHandler()
    # 创建一个极简 1 页 PDF
    pdf_path = tmp_path / "doc.pdf"
    try:
        import fitz
        doc = fitz.open()
        page = doc.new_page()
        page.insert_text((50, 50), "hello")
        doc.save(str(pdf_path))
        doc.close()
    except Exception:
        pytest.skip("fitz not available")

    pages = handler.extract_images(str(pdf_path), file_id="p1")
    assert len(pages) == 1
