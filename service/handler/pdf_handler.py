from pathlib import Path
from typing import List

import fitz

from service.handler.base import FileHandler


class PdfHandler(FileHandler):
    def extract_images(self, file_path: str, file_id: str, output_dir: str) -> List[str]:
        doc = fitz.open(file_path)
        images = []
        for i, page in enumerate(doc):
            pix = page.get_pixmap(dpi=150)
            out = Path(output_dir) / f"page_{i:04d}.jpg"
            pix.save(str(out))
            images.append(str(out))
        doc.close()
        return images
