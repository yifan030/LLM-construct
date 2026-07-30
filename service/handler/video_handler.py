import json
import shutil
import subprocess
from pathlib import Path
from typing import List

from service.handler.base import FileHandler


class VideoHandler(FileHandler):
    def __init__(self, settings=None):
        from libs.settings import get_settings
        resolved = settings or get_settings()
        self.cfg = resolved.ffmpeg
        self.video_cfg = resolved.video

    def extract_images(self, file_path: str, file_id: str, output_dir: str) -> List[str]:
        out_pattern = Path(output_dir) / "frame_%04d.jpg"
        cmd = [
            self.cfg.path,
            "-i", file_path,
            "-vf", f"fps={self.cfg.frame_rate}",
            "-q:v", str(self.cfg.quality),
            str(out_pattern),
        ]
        subprocess.run(cmd, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)

        frames = sorted(str(p) for p in Path(output_dir).glob("frame_*.jpg"))
        metadata = {
            "file_id": file_id,
            "source_video": file_path,
            "frames": [
                {"file": Path(f).name, "timestamp": i / max(self.cfg.frame_rate, 1)}
                for i, f in enumerate(frames)
            ],
        }
        Path(output_dir).joinpath("metadata.json").write_text(json.dumps(metadata, ensure_ascii=False))
        return frames
