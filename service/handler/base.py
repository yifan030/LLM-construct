from abc import ABC, abstractmethod
from typing import List


class FileHandler(ABC):
    @abstractmethod
    def extract_images(self, file_path: str, file_id: str) -> List[str]:
        """返回本地图片路径列表。"""
        ...
