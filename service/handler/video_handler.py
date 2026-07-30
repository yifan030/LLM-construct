import json
import logging
import re
import subprocess
from pathlib import Path
from typing import List, Tuple

from service.handler.base import FileHandler

logger = logging.getLogger(__name__)


class VideoHandler(FileHandler):
    def __init__(self, settings=None):
        from libs.settings import get_settings
        resolved = settings or get_settings()
        self.cfg = resolved.ffmpeg
        self.video_cfg = resolved.video

    def extract_images(self, file_path: str, file_id: str, output_dir: str) -> List[str]:
        out_pattern = Path(output_dir) / "frame_%04d.jpg"
        mode = self.video_cfg.dedup_mode

        if mode == "scene":
            frames, metadata = self._extract_scene_frames(file_path, file_id, out_pattern)
        elif mode == "hash":
            all_frames = self._extract_fps_frames(file_path, file_id, out_pattern)
            frames = self._filter_hash_duplicates(all_frames)
            metadata = self._build_metadata(file_id, file_path, frames, mode="hash")
        elif mode in (None, "none"):
            frames = self._extract_fps_frames(file_path, file_id, out_pattern)
            metadata = self._build_metadata(file_id, file_path, frames, mode="none")
        else:
            raise ValueError(f"unsupported dedup_mode: {mode}")

        Path(output_dir).joinpath("metadata.json").write_text(
            json.dumps(metadata, ensure_ascii=False), encoding="utf-8"
        )
        return frames

    def _extract_fps_frames(self, file_path: str, file_id: str, out_pattern: Path) -> List[str]:
        cmd = [
            self.cfg.path,
            "-i", file_path,
            "-vf", f"fps={self.cfg.frame_rate}",
            "-q:v", str(self.cfg.quality),
            str(out_pattern),
        ]
        subprocess.run(cmd, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        return sorted(str(p) for p in out_pattern.parent.glob("frame_*.jpg"))

    _SHOWINFO_RE = re.compile(r"pts_time:\s*([\d.]+)\s+scene_score:\s*([\d.eE+-]+)")

    def _extract_scene_frames(
        self, file_path: str, file_id: str, out_pattern: Path
    ) -> Tuple[List[str], dict]:
        vf = f"select=gt(scene\\,{self.video_cfg.scene_threshold})+eq(n\\,0),showinfo"
        cmd = [
            self.cfg.path,
            "-i", file_path,
            "-vf", vf,
            "-vsync", "vfr",
            "-q:v", str(self.cfg.quality),
            str(out_pattern),
        ]
        result = subprocess.run(
            cmd, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True
        )
        frames = sorted(str(p) for p in out_pattern.parent.glob("frame_*.jpg"))
        scene_info = self._parse_showinfo(result.stderr)

        if len(scene_info) != len(frames):
            logger.warning(
                "scene info count mismatch: info=%d frames=%d",
                len(scene_info),
                len(frames),
            )
            scene_info = scene_info[: len(frames)] + [
                {
                    "pts_time": i / max(self.cfg.frame_rate, 1),
                    "scene_score": 0.0,
                }
                for i in range(len(scene_info), len(frames))
            ]

        metadata = {
            "file_id": file_id,
            "source_video": file_path,
            "dedup_mode": "scene",
            "scene_threshold": self.video_cfg.scene_threshold,
            "frames": [
                {
                    "file": Path(f).name,
                    "timestamp": info.get("pts_time", i / max(self.cfg.frame_rate, 1)),
                    "scene_score": info.get("scene_score", 0.0),
                }
                for i, (f, info) in enumerate(zip(frames, scene_info))
            ],
        }
        return frames, metadata

    def _parse_showinfo(self, stderr: str) -> List[dict]:
        lines = []
        for line in stderr.splitlines():
            if "scene_score:" in line:
                m = self._SHOWINFO_RE.search(line)
                if m:
                    lines.append(
                        {"pts_time": float(m.group(1)), "scene_score": float(m.group(2))}
                    )
        return lines

    def _filter_hash_duplicates(self, frames: List[str]) -> List[str]:
        try:
            import imagehash
            from PIL import Image
        except ImportError as e:
            raise RuntimeError("hash dedup requires imagehash and Pillow") from e

        kept = []
        last_hash = None
        for frame in frames:
            try:
                h = imagehash.phash(
                    Image.open(frame), hash_size=self.video_cfg.hash_size
                )
            except Exception as e:
                logger.warning("hash compute failed for %s: %s", frame, e)
                kept.append(frame)
                last_hash = None
                continue

            if last_hash is None or h - last_hash > self.video_cfg.hash_threshold:
                kept.append(frame)
                last_hash = h
            else:
                logger.debug("dedup skipped frame %s", frame)
        return kept

    def _build_metadata(
        self, file_id: str, source_video: str, frames: List[str], mode: str
    ) -> dict:
        return {
            "file_id": file_id,
            "source_video": source_video,
            "dedup_mode": mode,
            "frames": [
                {"file": Path(f).name, "timestamp": i / max(self.cfg.frame_rate, 1)}
                for i, f in enumerate(frames)
            ],
        }
