import json
import shutil
import subprocess
from pathlib import Path

import pytest

from libs.settings import Settings
from service.handler.video_handler import VideoHandler
from service.handler.pdf_handler import PdfHandler


def _make_test_video(tmp_path: Path, duration: int = 1, rate: int = 1) -> Path:
    video = tmp_path / "sample.mp4"
    subprocess.run(
        [
            "ffmpeg", "-y", "-f", "lavfi",
            "-i", f"testsrc=duration={duration}:size=320x240:rate={rate}",
            "-pix_fmt", "yuv420p", str(video),
        ],
        check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
    )
    return video


@pytest.mark.skipif(not shutil.which("ffprobe"), reason="ffprobe not available")
def test_video_handler_probe_video_returns_real_metadata(tmp_path: Path):
    handler = VideoHandler(Settings())
    video = _make_test_video(tmp_path, duration=2, rate=25)

    info = handler.probe_video(str(video))
    assert info["duration"] == pytest.approx(2.0, abs=0.1)
    assert info["resolution"] == "320x240"
    assert info["fps"] == 25


@pytest.mark.skipif(not shutil.which("ffmpeg"), reason="ffmpeg not available")
def test_video_handler_fps_mode(tmp_path: Path):
    settings = Settings()
    settings.video.dedup_mode = "none"
    handler = VideoHandler(settings)

    output_dir = tmp_path / "out"
    output_dir.mkdir()
    video = _make_test_video(tmp_path, duration=2, rate=1)

    frames = handler.extract_images(str(video), file_id="v1", output_dir=str(output_dir))
    assert len(frames) == 2
    assert all(Path(f).exists() for f in frames)

    metadata = json.loads((output_dir / "metadata.json").read_text(encoding="utf-8"))
    assert metadata["dedup_mode"] == "none"
    assert len(metadata["frames"]) == 2


@pytest.mark.skipif(not shutil.which("ffmpeg"), reason="ffmpeg not available")
def test_video_handler_scene_mode(tmp_path: Path):
    settings = Settings()
    settings.video.dedup_mode = "scene"
    settings.video.scene_threshold = 0.05
    handler = VideoHandler(settings)

    output_dir = tmp_path / "out"
    output_dir.mkdir()
    video = _make_test_video(tmp_path, duration=2, rate=1)

    frames = handler.extract_images(str(video), file_id="v2", output_dir=str(output_dir))
    assert len(frames) >= 1
    assert all(Path(f).exists() for f in frames)

    metadata = json.loads((output_dir / "metadata.json").read_text(encoding="utf-8"))
    assert metadata["dedup_mode"] == "scene"
    assert "scene_score" in metadata["frames"][0]


@pytest.mark.skipif(not shutil.which("ffmpeg"), reason="ffmpeg not available")
def test_video_handler_scene_mode_records_real_timestamps(tmp_path: Path):
    settings = Settings()
    settings.video.dedup_mode = "scene"
    settings.video.scene_threshold = 0.05
    handler = VideoHandler(settings)

    # 4 x 2s solid-color segments -> scene cuts at t=2, 4, 6
    video = tmp_path / "cuts.mp4"
    subprocess.run(
        [
            "ffmpeg", "-y",
            "-f", "lavfi", "-i", "color=red:s=320x240:d=2:r=25",
            "-f", "lavfi", "-i", "color=blue:s=320x240:d=2:r=25",
            "-f", "lavfi", "-i", "color=green:s=320x240:d=2:r=25",
            "-f", "lavfi", "-i", "color=yellow:s=320x240:d=2:r=25",
            "-filter_complex", "[0:v][1:v][2:v][3:v]concat=n=4:v=1[v]",
            "-map", "[v]", "-pix_fmt", "yuv420p", str(video),
        ],
        check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
    )

    output_dir = tmp_path / "out"
    output_dir.mkdir()
    frames = handler.extract_images(str(video), file_id="cuts", output_dir=str(output_dir))
    assert len(frames) == 4

    metadata = json.loads((output_dir / "metadata.json").read_text(encoding="utf-8"))
    timestamps = [f["timestamp"] for f in metadata["frames"]]
    assert timestamps == pytest.approx([0, 2, 4, 6], abs=0.2)
    scores = [f["scene_score"] for f in metadata["frames"]]
    assert scores[0] == 0.0
    assert all(s > settings.video.scene_threshold for s in scores[1:])


@pytest.mark.skipif(not shutil.which("ffmpeg"), reason="ffmpeg not available")
def test_video_handler_hash_mode(tmp_path: Path):
    pytest.importorskip("imagehash")
    settings = Settings()
    settings.video.dedup_mode = "hash"
    settings.video.hash_size = 8
    settings.video.hash_threshold = 8
    handler = VideoHandler(settings)

    static_img = tmp_path / "static.jpg"
    subprocess.run(
        [
            "ffmpeg", "-y", "-f", "lavfi",
            "-i", "color=c=black:s=64x64:r=1",
            "-frames:v", "1", str(static_img),
        ],
        check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
    )
    video = tmp_path / "static.mp4"
    subprocess.run(
        [
            "ffmpeg", "-y", "-loop", "1", "-i", str(static_img),
            "-c:v", "libx264", "-t", "3", "-pix_fmt", "yuv420p", "-r", "1",
            str(video),
        ],
        check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
    )

    output_dir = tmp_path / "out"
    output_dir.mkdir()
    frames = handler.extract_images(str(video), file_id="v3", output_dir=str(output_dir))
    assert len(frames) == 1

    metadata = json.loads((output_dir / "metadata.json").read_text(encoding="utf-8"))
    assert metadata["dedup_mode"] == "hash"


@pytest.mark.skipif(not shutil.which("ffmpeg"), reason="ffmpeg not available")
def test_video_handler_hash_mode_records_original_timestamps(tmp_path: Path):
    pytest.importorskip("imagehash")
    settings = Settings()
    settings.video.dedup_mode = "hash"
    settings.video.hash_size = 8
    settings.video.hash_threshold = 1
    handler = VideoHandler(settings)

    # 4 帧序列（1fps）：t=0,1 相同，t=2,3 相同 -> 去重后保留 t=0 和 t=2
    imgs = []
    for name, pattern in [("p1", "testsrc"), ("p2", "smptebars")]:
        img = tmp_path / f"{name}.jpg"
        subprocess.run(
            [
                "ffmpeg", "-y", "-f", "lavfi",
                "-i", f"{pattern}=duration=1:size=64x64:rate=1",
                "-frames:v", "1", str(img),
            ],
            check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        )
        imgs.append(img)
    for seq, src in enumerate([imgs[0], imgs[0], imgs[1], imgs[1]], start=1):
        shutil.copy(src, tmp_path / f"seq_{seq}.jpg")
    video = tmp_path / "two_scenes.mp4"
    subprocess.run(
        [
            "ffmpeg", "-y", "-framerate", "1",
            "-i", str(tmp_path / "seq_%d.jpg"),
            "-c:v", "libx264", "-pix_fmt", "yuv420p", str(video),
        ],
        check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
    )

    output_dir = tmp_path / "out"
    output_dir.mkdir()
    frames = handler.extract_images(str(video), file_id="v4", output_dir=str(output_dir))
    assert len(frames) == 2

    metadata = json.loads((output_dir / "metadata.json").read_text(encoding="utf-8"))
    assert metadata["dedup_mode"] == "hash"
    assert metadata["hash_size"] == 8
    assert metadata["hash_threshold"] == 1
    timestamps = [f["timestamp"] for f in metadata["frames"]]
    assert timestamps == pytest.approx([0.0, 2.0], abs=0.1)


def test_pdf_handler_extracts_pages(tmp_path: Path):
    handler = PdfHandler()
    pdf_path = tmp_path / "doc.pdf"
    output_dir = tmp_path / "pdf_out"
    output_dir.mkdir()
    try:
        import fitz
        doc = fitz.open()
        page = doc.new_page()
        page.insert_text((50, 50), "hello")
        doc.save(str(pdf_path))
        doc.close()
    except Exception:
        pytest.skip("fitz not available")

    pages = handler.extract_images(str(pdf_path), file_id="p1", output_dir=str(output_dir))
    assert len(pages) == 1
