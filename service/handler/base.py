from abc import ABC, abstractmethod
from typing import List


class FileHandler(ABC):
    @abstractmethod
    def extract_images(self, file_path: str, file_id: str, output_dir: str) -> List[str]:
        """将图片提取到 output_dir，返回本地图片路径列表。"""
        ...
