from pathlib import Path
from unittest.mock import ANY, MagicMock

import pytest

from libs.settings import Settings
from service.worker.parse_worker import ParseTask, ParseWorker


def _make_session(file_record):
    session = MagicMock()
    session.query.return_value.filter_by.return_value.first.return_value = file_record
    return session


def test_parse_video_uploads_md_and_updates_db():
    oss = MagicMock()
    oss.download.return_value = "/tmp/x.mp4"
    ocr = MagicMock()
    ocr.parse_image.return_value = "frame text"
    video_handler = MagicMock()
    video_handler.extract_images.return_value = ["/tmp/frame.jpg"]
    pdf_handler = MagicMock()

    db_file = MagicMock()
    db_file.video_meta = None
    db_session = _make_session(db_file)

    worker = ParseWorker(
        settings=Settings(),
        oss_client=oss,
        ocr_adapter=ocr,
        video_handler=video_handler,
        pdf_handler=pdf_handler,
    )

    task = ParseTask(
        file_id="f1", file_type="video", oss_path="education/video/2024/x.mp4"
    )
    worker.parse(task, session=db_session)

    assert db_file.parse_status == 2
    assert db_file.parse_stage == "completed"
    assert db_file.parse_progress == 100
    assert db_file.parsed_text_path.endswith("x_parsed/x.md")
    assert db_file.frame_count == 1

    video_handler.extract_images.assert_called_once()
    args, _ = video_handler.extract_images.call_args
    assert args[0] == "/tmp/x.mp4"
    assert args[1] == "f1"
    assert Path(args[2]).name == "frames"

    ocr.parse_image.assert_called_once_with("/tmp/frame.jpg")
    oss.upload.assert_any_call(
        "/tmp/frame.jpg", "education/video/2024/x_parsed/frames/frame.jpg"
    )
    oss.upload.assert_any_call(
        ANY, "education/video/2024/x_parsed/metadata.json"
    )
    oss.upload.assert_any_call(ANY, "education/video/2024/x_parsed/x.md")
    assert oss.upload.call_count == 3


def test_parse_video_uploads_frame_metadata_and_records_path(tmp_path: Path):
    from unittest.mock import patch

    oss = MagicMock()
    oss.download.return_value = "/tmp/x.mp4"
    ocr = MagicMock()
    ocr.parse_image.return_value = "frame text"
    video_handler = MagicMock()
    video_handler.extract_images.return_value = ["/tmp/frame.jpg"]
    pdf_handler = MagicMock()

    db_file = MagicMock()
    db_file.video_meta = None
    db_session = _make_session(db_file)

    worker = ParseWorker(
        settings=Settings(),
        oss_client=oss,
        ocr_adapter=ocr,
        video_handler=video_handler,
        pdf_handler=pdf_handler,
    )

    task = ParseTask(
        file_id="f1", file_type="video", oss_path="education/video/2024/x.mp4"
    )
    with patch("service.worker.parse_worker.tempfile.TemporaryDirectory") as mock_tmp:
        mock_tmp.return_value.__enter__.return_value = str(tmp_path)
        worker.parse(task, session=db_session)

    oss.upload.assert_any_call(
        str(tmp_path / "frames" / "metadata.json"),
        "education/video/2024/x_parsed/metadata.json",
    )
    assert (
        db_file.video_meta.frame_metadata_path
        == "education/video/2024/x_parsed/metadata.json"
    )


def test_parse_video_populates_video_meta_from_probe(tmp_path: Path):
    from unittest.mock import patch

    oss = MagicMock()
    oss.download.return_value = "/tmp/x.mp4"
    ocr = MagicMock()
    ocr.parse_image.return_value = "frame text"
    video_handler = MagicMock()
    video_handler.extract_images.return_value = ["/tmp/frame.jpg"]
    video_handler.probe_video.return_value = {
        "duration": 2430.5,
        "resolution": "1920x1080",
        "fps": 25,
    }
    pdf_handler = MagicMock()

    db_file = MagicMock()
    db_file.video_meta = None
    db_session = _make_session(db_file)

    worker = ParseWorker(
        settings=Settings(),
        oss_client=oss,
        ocr_adapter=ocr,
        video_handler=video_handler,
        pdf_handler=pdf_handler,
    )

    task = ParseTask(
        file_id="f1", file_type="video", oss_path="education/video/2024/x.mp4"
    )
    with patch("service.worker.parse_worker.tempfile.TemporaryDirectory") as mock_tmp:
        mock_tmp.return_value.__enter__.return_value = str(tmp_path)
        worker.parse(task, session=db_session)

    assert db_file.parse_status == 2
    assert db_file.video_meta.duration == 2430.5
    assert db_file.video_meta.resolution == "1920x1080"
    assert db_file.video_meta.fps == 25


def test_parse_video_tolerates_probe_failure(tmp_path: Path):
    from unittest.mock import patch

    oss = MagicMock()
    oss.download.return_value = "/tmp/x.mp4"
    ocr = MagicMock()
    ocr.parse_image.return_value = "frame text"
    video_handler = MagicMock()
    video_handler.extract_images.return_value = ["/tmp/frame.jpg"]
    video_handler.probe_video.side_effect = RuntimeError("ffprobe missing")
    pdf_handler = MagicMock()

    db_file = MagicMock()
    db_file.video_meta = None
    db_session = _make_session(db_file)

    worker = ParseWorker(
        settings=Settings(),
        oss_client=oss,
        ocr_adapter=ocr,
        video_handler=video_handler,
        pdf_handler=pdf_handler,
    )

    task = ParseTask(
        file_id="f1", file_type="video", oss_path="education/video/2024/x.mp4"
    )
    with patch("service.worker.parse_worker.tempfile.TemporaryDirectory") as mock_tmp:
        mock_tmp.return_value.__enter__.return_value = str(tmp_path)
        worker.parse(task, session=db_session)

    assert db_file.parse_status == 2
    assert db_file.video_meta.duration is None
    assert db_file.video_meta.resolution is None
    assert db_file.video_meta.fps is None


def test_parse_pdf():
    oss = MagicMock()
    oss.download.return_value = "/tmp/y.pdf"
    ocr = MagicMock()
    ocr.parse_image.return_value = "page text"
    video_handler = MagicMock()
    pdf_handler = MagicMock()
    pdf_handler.extract_images.return_value = ["/tmp/page.jpg"]

    db_file = MagicMock()
    db_session = _make_session(db_file)

    worker = ParseWorker(
        settings=Settings(),
        oss_client=oss,
        ocr_adapter=ocr,
        video_handler=video_handler,
        pdf_handler=pdf_handler,
    )

    task = ParseTask(
        file_id="f2", file_type="pdf", oss_path="education/pdf/2024/y.pdf"
    )
    worker.parse(task, session=db_session)

    assert db_file.parse_status == 2
    assert db_file.parse_stage == "completed"
    assert db_file.parse_progress == 100
    assert db_file.parsed_text_path.endswith("y_parsed/y.md")
    assert db_file.frame_count == 1

    pdf_handler.extract_images.assert_called_once()
    args, _ = pdf_handler.extract_images.call_args
    assert args[0] == "/tmp/y.pdf"
    assert args[1] == "f2"
    assert Path(args[2]).name == "pages"

    ocr.parse_image.assert_called_once_with("/tmp/page.jpg")
    oss.upload.assert_called_once_with(ANY, "education/pdf/2024/y_parsed/y.md")


def test_parse_missing_file_record():
    session = MagicMock()
    session.query.return_value.filter_by.return_value.first.return_value = None

    worker = ParseWorker(
        settings=Settings(),
        oss_client=MagicMock(),
        ocr_adapter=MagicMock(),
        video_handler=MagicMock(),
        pdf_handler=MagicMock(),
    )

    task = ParseTask(
        file_id="missing", file_type="video", oss_path="education/video/2024/x.mp4"
    )
    with pytest.raises(ValueError, match="file not found"):
        worker.parse(task, session=session)


def test_parse_failure_marks_status_failed_and_re_raises():
    oss = MagicMock()
    oss.download.return_value = "/tmp/x.mp4"
    ocr = MagicMock()
    ocr.parse_image.side_effect = RuntimeError("ocr down")
    video_handler = MagicMock()
    video_handler.extract_images.return_value = ["/tmp/frame.jpg"]
    pdf_handler = MagicMock()

    db_file = MagicMock()
    db_file.video_meta = None
    db_session = _make_session(db_file)

    worker = ParseWorker(
        settings=Settings(),
        oss_client=oss,
        ocr_adapter=ocr,
        video_handler=video_handler,
        pdf_handler=pdf_handler,
    )

    task = ParseTask(
        file_id="f1", file_type="video", oss_path="education/video/2024/x.mp4"
    )
    with pytest.raises(RuntimeError, match="OCR failed for all 1 frame"):
        worker.parse(task, session=db_session)

    assert db_file.parse_status == 3
    assert db_file.parse_stage == "failed"
    assert "OCR failed for all 1 frame" in db_file.error_msg


def test_parse_video_tolerates_single_ocr_failure(tmp_path: Path):
    from unittest.mock import patch

    oss = MagicMock()
    oss.download.return_value = "/tmp/x.mp4"
    ocr = MagicMock()
    ocr.parse_image.side_effect = ["frame one", RuntimeError("ocr down"), "frame three"]
    video_handler = MagicMock()
    video_handler.extract_images.return_value = [
        "/tmp/frame1.jpg", "/tmp/frame2.jpg", "/tmp/frame3.jpg"
    ]
    video_handler.probe_video.return_value = {
        "duration": 2430.5,
        "resolution": "1920x1080",
        "fps": 25,
    }
    pdf_handler = MagicMock()

    db_file = MagicMock()
    db_file.video_meta = None
    db_session = _make_session(db_file)

    worker = ParseWorker(
        settings=Settings(),
        oss_client=oss,
        ocr_adapter=ocr,
        video_handler=video_handler,
        pdf_handler=pdf_handler,
    )

    task = ParseTask(
        file_id="f1", file_type="video", oss_path="education/video/2024/x.mp4"
    )
    with patch("service.worker.parse_worker.tempfile.TemporaryDirectory") as mock_tmp:
        mock_tmp.return_value.__enter__.return_value = str(tmp_path)
        worker.parse(task, session=db_session)

    assert db_file.parse_status == 2
    assert db_file.parse_stage == "completed"
    assert db_file.parse_progress == 100
    assert db_file.frame_count == 3
    assert db_file.video_meta.dedup_mode == Settings().video.dedup_mode
    assert db_file.video_meta.fps == 25
    assert db_file.video_meta.duration == 2430.5
    assert db_file.video_meta.resolution == "1920x1080"
    assert db_file.video_meta.failed_frames == [
        {"index": 1, "file": "frame2.jpg", "oss_path": "education/video/2024/x_parsed/frames/frame2.jpg", "error": "ocr down"}
    ]

    md_file = list(tmp_path.glob("*.md"))[0]
    content = md_file.read_text(encoding="utf-8")
    assert "## Frame 1" in content
    assert "frame one" in content
    assert "## Frame 2" not in content
    assert "## Frame 3" in content
    assert "frame three" in content


def test_parse_unsupported_file_type():
    oss = MagicMock()
    oss.download.return_value = "/tmp/z.doc"
    db_file = MagicMock()
    db_session = _make_session(db_file)

    worker = ParseWorker(
        settings=Settings(),
        oss_client=oss,
        ocr_adapter=MagicMock(),
        video_handler=MagicMock(),
        pdf_handler=MagicMock(),
    )

    task = ParseTask(
        file_id="f3", file_type="doc", oss_path="education/docs/z.doc"
    )
    with pytest.raises(ValueError, match="unsupported file_type"):
        worker.parse(task, session=db_session)

    assert db_file.parse_status == 3
    assert db_file.parse_stage == "failed"
    assert "unsupported file_type" in db_file.error_msg


def test_parse_skips_when_already_parsed_and_force_false():
    oss = MagicMock()
    ocr = MagicMock()
    video_handler = MagicMock()
    pdf_handler = MagicMock()

    db_file = MagicMock()
    db_file.parse_status = 2
    db_file.parsed_text_path = "education/video/2024/x_parsed/x.md"
    db_session = _make_session(db_file)

    worker = ParseWorker(
        settings=Settings(),
        oss_client=oss,
        ocr_adapter=ocr,
        video_handler=video_handler,
        pdf_handler=pdf_handler,
    )

    task = ParseTask(
        file_id="f1", file_type="video", oss_path="education/video/2024/x.mp4", force=False
    )
    worker.parse(task, session=db_session)

    assert db_file.parse_status == 2
    oss.download.assert_not_called()
    video_handler.extract_images.assert_not_called()
    ocr.parse_image.assert_not_called()
    oss.upload.assert_not_called()


def test_parse_re_parses_when_force_true():
    oss = MagicMock()
    oss.download.return_value = "/tmp/x.mp4"
    ocr = MagicMock()
    ocr.parse_image.return_value = "frame text"
    video_handler = MagicMock()
    video_handler.extract_images.return_value = ["/tmp/frame.jpg"]
    pdf_handler = MagicMock()

    db_file = MagicMock()
    db_file.parse_status = 2
    db_file.parsed_text_path = "education/video/2024/x_parsed/x.md"
    db_file.video_meta = None
    db_session = _make_session(db_file)

    worker = ParseWorker(
        settings=Settings(),
        oss_client=oss,
        ocr_adapter=ocr,
        video_handler=video_handler,
        pdf_handler=pdf_handler,
    )

    task = ParseTask(
        file_id="f1", file_type="video", oss_path="education/video/2024/x.mp4", force=True
    )
    worker.parse(task, session=db_session)

    assert db_file.parse_status == 2
    assert db_file.parse_stage == "completed"
    assert db_file.parse_progress == 100
    assert db_file.parsed_text_path.endswith("x_parsed/x.md")
    video_handler.extract_images.assert_called_once()
    oss.upload.assert_any_call(ANY, "education/video/2024/x_parsed/x.md")


def test_parse_updates_progress_and_stage():
    oss = MagicMock()
    oss.download.return_value = "/tmp/x.mp4"
    ocr = MagicMock()
    ocr.parse_image.return_value = "frame text"
    video_handler = MagicMock()
    video_handler.extract_images.return_value = ["/tmp/frame.jpg"]
    pdf_handler = MagicMock()

    db_file = MagicMock()
    db_file.video_meta = None
    db_session = _make_session(db_file)

    worker = ParseWorker(
        settings=Settings(),
        oss_client=oss,
        ocr_adapter=ocr,
        video_handler=video_handler,
        pdf_handler=pdf_handler,
    )

    task = ParseTask(
        file_id="f1", file_type="video", oss_path="education/video/2024/x.mp4"
    )
    worker.parse(task, session=db_session)

    assert db_file.parse_status == 2
    assert db_file.parse_stage == "completed"
    assert db_file.parse_progress == 100
    assert db_session.commit.call_count >= 5
