import json
import subprocess
import tempfile
from pathlib import Path
from typing import List

from service.handler.base import FileHandler


class VideoHandler(FileHandler):
    def __init__(self, settings=None):
        from libs.settings import get_settings
        self.cfg = (settings or get_settings()).ffmpeg
        self.video_cfg = (settings or get_settings()).video

    def extract_images(self, file_path: str, file_id: str) -> List[str]:
        tmpdir = tempfile.mkdtemp(prefix=f"video_{file_id}_")
        out_pattern = Path(tmpdir) / "frame_%04d.jpg"
        cmd = [
            self.cfg.path,
            "-i", file_path,
            "-vf", f"fps={self.cfg.frame_rate}",
            "-q:v", str(self.cfg.quality),
            str(out_pattern),
        ]
        subprocess.run(cmd, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)

        frames = sorted(str(p) for p in Path(tmpdir).glob("frame_*.jpg"))
        metadata = {
            "file_id": file_id,
            "source_video": file_path,
            "frames": [
                {"file": Path(f).name, "timestamp": i / max(self.cfg.frame_rate, 1)}
                for i, f in enumerate(frames)
            ],
        }
        Path(tmpdir).joinpath("metadata.json").write_text(json.dumps(metadata, ensure_ascii=False))
        return frames
