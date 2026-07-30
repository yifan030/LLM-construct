import logging
import tempfile
from pathlib import Path
from typing import List, Tuple

from pydantic import BaseModel

from core.models import EduConstructFile, EduVideoMeta
from libs.oss_client import OssClient
from libs.settings import Settings
from service.handler.base import FileHandler
from service.ocr.base import OcrAdapter

logger = logging.getLogger(__name__)


class ParseTask(BaseModel):
    file_id: str
    file_type: str  # video | pdf
    oss_path: str
    force: bool = False


class ParseWorker:
    def __init__(
        self,
        settings: Settings,
        oss_client: OssClient,
        ocr_adapter: OcrAdapter,
        video_handler: FileHandler,
        pdf_handler: FileHandler,
    ):
        self.settings = settings
        self.oss = oss_client
        self.ocr = ocr_adapter
        self.video_handler = video_handler
        self.pdf_handler = pdf_handler

    def _set_status(
        self,
        record: EduConstructFile,
        parse_status: int,
        stage: str,
        progress: int,
        message: str | None = None,
    ) -> None:
        record.parse_status = parse_status
        record.parse_stage = stage
        record.parse_progress = progress
        if message is not None:
            record.error_msg = message
        logger.info(
            "parse progress file_id=%s status=%s stage=%s progress=%d%s",
            record.file_id,
            parse_status,
            stage,
            progress,
            f" msg={message}" if message else "",
        )

    def parse(self, task: ParseTask, session) -> None:
        file_record = (
            session.query(EduConstructFile).filter_by(file_id=task.file_id).first()
        )
        if not file_record:
            raise ValueError(f"file not found: {task.file_id}")

        if (
            not task.force
            and file_record.parse_status == 2
            and file_record.parsed_text_path
        ):
            return

        self._set_status(file_record, parse_status=1, stage="downloading", progress=0)
        file_record.error_msg = None
        session.commit()

        try:
            with tempfile.TemporaryDirectory(prefix=f"parse_{task.file_id}_") as tmpdir:
                local_file = self.oss.download(task.oss_path, tmpdir)
                parsed_dir = self._parsed_dir(task.oss_path)

                if task.file_type == "video":
                    md_path, frame_count = self._parse_video(
                        local_file, task.file_id, file_record, parsed_dir, tmpdir, session
                    )
                elif task.file_type == "pdf":
                    md_path, frame_count = self._parse_pdf(
                        local_file, task.file_id, file_record, parsed_dir, tmpdir, session
                    )
                else:
                    raise ValueError(f"unsupported file_type: {task.file_type}")

                self._set_status(
                    file_record, parse_status=1, stage="uploading_md", progress=90
                )
                session.commit()

                md_oss_path = f"{parsed_dir}/{Path(md_path).name}"
                self.oss.upload(md_path, md_oss_path)
                self._set_status(
                    file_record, parse_status=2, stage="completed", progress=100
                )
                file_record.parsed_text_path = md_oss_path
                file_record.frame_count = frame_count
                session.commit()
        except Exception as e:
            self._set_status(
                file_record,
                parse_status=3,
                stage="failed",
                progress=file_record.parse_progress or 0,
                message=str(e),
            )
            session.commit()
            raise

    def _parsed_dir(self, oss_path: str) -> str:
        p = Path(oss_path)
        return str(p.parent / f"{p.stem}_parsed")

    def _get_or_create_video_meta(
        self, file_id: str, file_record: EduConstructFile, session
    ) -> EduVideoMeta:
        video_meta = getattr(file_record, "video_meta", None)
        if video_meta is None:
            video_meta = EduVideoMeta(file_id=file_id)
            file_record.video_meta = video_meta
            session.add(video_meta)
        return video_meta

    def _parse_video(
        self,
        local_file: str,
        file_id: str,
        file_record: EduConstructFile,
        parsed_dir: str,
        tmpdir: str,
        session,
    ) -> Tuple[str, int]:
        frames_dir = Path(tmpdir) / "frames"
        frames_dir.mkdir(parents=True, exist_ok=True)

        self._set_status(
            file_record, parse_status=1, stage="extracting_frames", progress=10
        )
        session.commit()

        frames = self.video_handler.extract_images(
            local_file, file_id, str(frames_dir)
        )

        self._set_status(
            file_record, parse_status=1, stage="deduplicating", progress=30
        )
        session.commit()

        video_meta = self._get_or_create_video_meta(file_id, file_record, session)
        video_meta.dedup_mode = self.settings.video.dedup_mode
        video_meta.scene_threshold = (
            self.settings.video.scene_threshold
            if self.settings.video.dedup_mode == "scene"
            else None
        )
        video_meta.fps = self.settings.ffmpeg.frame_rate
        session.commit()

        self._set_status(
            file_record, parse_status=1, stage="uploading_frames", progress=40
        )
        session.commit()

        frame_texts: List[str] = []
        failed_frames: List[dict] = []
        total = len(frames)
        for i, frame_path in enumerate(frames):
            oss_frame_path = f"{parsed_dir}/frames/{Path(frame_path).name}"
            self.oss.upload(frame_path, oss_frame_path)

            try:
                text = self.ocr.parse_image(frame_path)
            except Exception as e:
                logger.warning(
                    "OCR failed for frame %s (%d/%d): %s",
                    frame_path,
                    i + 1,
                    total,
                    e,
                )
                failed_frames.append(
                    {
                        "index": i,
                        "file": Path(frame_path).name,
                        "oss_path": oss_frame_path,
                        "error": str(e),
                    }
                )
                continue

            frame_texts.append(f"## Frame {i + 1}\n\n{text}\n")
            progress = 60 + int(30 * (i + 1) / total)
            self._set_status(
                file_record, parse_status=1, stage="ocr", progress=progress
            )
            session.commit()

        if failed_frames:
            video_meta.failed_frames = failed_frames
            session.commit()

        if not frame_texts:
            raise RuntimeError(
                f"OCR failed for all {total} frame(s); no markdown generated"
            )

        md_content = "\n".join(frame_texts)
        md_path = Path(tmpdir) / f"{Path(local_file).stem}.md"
        md_path.write_text(md_content, encoding="utf-8")
        return str(md_path), len(frames)

    def _parse_pdf(
        self,
        local_file: str,
        file_id: str,
        file_record: EduConstructFile,
        parsed_dir: str,
        tmpdir: str,
        session,
    ) -> Tuple[str, int]:
        pages_dir = Path(tmpdir) / "pages"
        pages_dir.mkdir(parents=True, exist_ok=True)

        self._set_status(
            file_record, parse_status=1, stage="extracting_pages", progress=20
        )
        session.commit()

        pages = self.pdf_handler.extract_images(local_file, file_id, str(pages_dir))

        self._set_status(
            file_record, parse_status=1, stage="ocr", progress=50
        )
        session.commit()

        page_texts: List[str] = []
        for i, page_path in enumerate(pages):
            text = self.ocr.parse_image(page_path)
            page_texts.append(f"## Page {i + 1}\n\n{text}\n")

        md_content = "\n".join(page_texts)
        md_path = Path(tmpdir) / f"{Path(local_file).stem}.md"
        md_path.write_text(md_content, encoding="utf-8")
        return str(md_path), len(pages)
