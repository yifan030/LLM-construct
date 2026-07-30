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

    def probe_video(self, file_path: str) -> dict:
        """用 ffprobe 读取源视频的真实时长/分辨率/帧率。"""
        cmd = [
            self.cfg.ffprobe_path,
            "-v", "error",
            "-select_streams", "v:0",
            "-show_entries", "stream=width,height,avg_frame_rate:format=duration",
            "-of", "json",
            file_path,
        ]
        result = subprocess.run(
            cmd, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True
        )
        data = json.loads(result.stdout)
        stream = (data.get("streams") or [{}])[0]

        fps = None
        rate = stream.get("avg_frame_rate")
        if rate and rate != "0/0":
            num, _, den = rate.partition("/")
            fps = round(float(num) / float(den or 1))

        duration = data.get("format", {}).get("duration")
        width, height = stream.get("width"), stream.get("height")
        return {
            "duration": float(duration) if duration is not None else None,
            "resolution": f"{width}x{height}" if width and height else None,
            "fps": fps,
        }

    def extract_images(self, file_path: str, file_id: str, output_dir: str) -> List[str]:
        out_pattern = Path(output_dir) / "frame_%04d.jpg"
        mode = self.video_cfg.dedup_mode

        if mode == "scene":
            frames, metadata = self._extract_scene_frames(file_path, file_id, out_pattern)
        elif mode == "hash":
            all_frames = self._extract_fps_frames(file_path, file_id, out_pattern)
            kept = self._filter_hash_duplicates(all_frames)
            frames = [path for _, path in kept]
            rate = max(self.cfg.frame_rate, 1)
            metadata = self._build_metadata(
                file_id,
                file_path,
                frames,
                mode="hash",
                timestamps=[i / rate for i, _ in kept],
            )
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

    _FRAME_INFO_RE = re.compile(r"frame:\d+\s+pts:\S+\s+pts_time:([\d.]+)")
    _SCENE_SCORE_RE = re.compile(r"lavfi\.scene_score=([\d.eE+-]+)")

    def _extract_scene_frames(
        self, file_path: str, file_id: str, out_pattern: Path
    ) -> Tuple[List[str], dict]:
        # metadata=print（而非 showinfo）才能输出每帧的 lavfi.scene_score
        vf = f"select=gt(scene\\,{self.video_cfg.scene_threshold})+eq(n\\,0),metadata=print"
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
        scene_info = self._parse_frame_metadata(result.stderr)

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

    def _parse_frame_metadata(self, stderr: str) -> List[dict]:
        infos: List[dict] = []
        for line in stderr.splitlines():
            m = self._FRAME_INFO_RE.search(line)
            if m:
                infos.append({"pts_time": float(m.group(1)), "scene_score": 0.0})
                continue
            s = self._SCENE_SCORE_RE.search(line)
            if s and infos:
                infos[-1]["scene_score"] = float(s.group(1))
        return infos

    def _filter_hash_duplicates(self, frames: List[str]) -> List[Tuple[int, str]]:
        """按 phash 去重，返回 (原始帧序号, 帧路径) 列表，序号用于推算真实时间戳。"""
        try:
            import imagehash
            from PIL import Image
        except ImportError as e:
            raise RuntimeError("hash dedup requires imagehash and Pillow") from e

        kept: List[Tuple[int, str]] = []
        last_hash = None
        for i, frame in enumerate(frames):
            try:
                h = imagehash.phash(
                    Image.open(frame), hash_size=self.video_cfg.hash_size
                )
            except Exception as e:
                logger.warning("hash compute failed for %s: %s", frame, e)
                kept.append((i, frame))
                last_hash = None
                continue

            if last_hash is None or h - last_hash > self.video_cfg.hash_threshold:
                kept.append((i, frame))
                last_hash = h
            else:
                logger.debug("dedup skipped frame %s", frame)
        return kept

    def _build_metadata(
        self,
        file_id: str,
        source_video: str,
        frames: List[str],
        mode: str,
        timestamps: List[float] | None = None,
    ) -> dict:
        rate = max(self.cfg.frame_rate, 1)
        if timestamps is None:
            timestamps = [i / rate for i in range(len(frames))]
        metadata = {
            "file_id": file_id,
            "source_video": source_video,
            "dedup_mode": mode,
            "frames": [
                {"file": Path(f).name, "timestamp": ts}
                for f, ts in zip(frames, timestamps)
            ],
        }
        if mode == "hash":
            metadata["hash_size"] = self.video_cfg.hash_size
            metadata["hash_threshold"] = self.video_cfg.hash_threshold
        return metadata
