import tempfile
from pathlib import Path
from typing import List, Tuple

from pydantic import BaseModel

from core.models import EduConstructFile
from libs.oss_client import OssClient
from libs.settings import Settings
from service.handler.base import FileHandler
from service.ocr.base import OcrAdapter


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

        file_record.parse_status = 1
        session.commit()

        try:
            with tempfile.TemporaryDirectory(prefix=f"parse_{task.file_id}_") as tmpdir:
                local_file = self.oss.download(task.oss_path, tmpdir)
                parsed_dir = self._parsed_dir(task.oss_path)

                if task.file_type == "video":
                    md_path, frame_count = self._parse_video(
                        local_file, task.file_id, parsed_dir, tmpdir
                    )
                elif task.file_type == "pdf":
                    md_path, frame_count = self._parse_pdf(
                        local_file, task.file_id, parsed_dir, tmpdir
                    )
                else:
                    raise ValueError(f"unsupported file_type: {task.file_type}")

                md_oss_path = f"{parsed_dir}/{Path(md_path).name}"
                self.oss.upload(md_path, md_oss_path)
                file_record.parse_status = 2
                file_record.parsed_text_path = md_oss_path
                file_record.frame_count = frame_count
                session.commit()
        except Exception as e:
            file_record.parse_status = 3
            file_record.error_msg = str(e)
            session.commit()
            raise

    def _parsed_dir(self, oss_path: str) -> str:
        p = Path(oss_path)
        return str(p.parent / f"{p.stem}_parsed")

    def _parse_video(
        self, local_file: str, file_id: str, parsed_dir: str, tmpdir: str
    ) -> Tuple[str, int]:
        frames_dir = Path(tmpdir) / "frames"
        frames_dir.mkdir(parents=True, exist_ok=True)
        frames = self.video_handler.extract_images(
            local_file, file_id, str(frames_dir)
        )

        frame_texts: List[str] = []
        for i, frame_path in enumerate(frames):
            oss_frame_path = f"{parsed_dir}/frames/{Path(frame_path).name}"
            self.oss.upload(frame_path, oss_frame_path)
            text = self.ocr.parse_image(frame_path)
            frame_texts.append(f"## Frame {i + 1}\n\n{text}\n")

        md_content = "\n".join(frame_texts)
        md_path = Path(tmpdir) / f"{Path(local_file).stem}.md"
        md_path.write_text(md_content, encoding="utf-8")
        return str(md_path), len(frames)

    def _parse_pdf(
        self, local_file: str, file_id: str, parsed_dir: str, tmpdir: str
    ) -> Tuple[str, int]:
        pages_dir = Path(tmpdir) / "pages"
        pages_dir.mkdir(parents=True, exist_ok=True)
        pages = self.pdf_handler.extract_images(local_file, file_id, str(pages_dir))

        page_texts: List[str] = []
        for i, page_path in enumerate(pages):
            text = self.ocr.parse_image(page_path)
            page_texts.append(f"## Page {i + 1}\n\n{text}\n")

        md_content = "\n".join(page_texts)
        md_path = Path(tmpdir) / f"{Path(local_file).stem}.md"
        md_path.write_text(md_content, encoding="utf-8")
        return str(md_path), len(pages)
