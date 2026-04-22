"""
记忆系统基础模块

提供 JSON 文件存储的抽象基类。
"""

import json
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any, Optional


class BaseMemory(ABC):
    """记忆基类"""

    def __init__(self, storage_path: str):
        """
        初始化记忆存储

        Args:
            storage_path: 存储文件路径
        """
        self.storage_path = Path(storage_path)
        self.storage_path.parent.mkdir(parents=True, exist_ok=True)

    @abstractmethod
    def save(self, data: Any) -> bool:
        """保存数据"""
        pass

    @abstractmethod
    def load(self) -> Any:
        """加载数据"""
        pass

    @abstractmethod
    def clear(self) -> bool:
        """清除数据"""
        pass


class JSONMemory(BaseMemory):
    """JSON 文件记忆存储"""

    def save(self, data: Any) -> bool:
        """保存数据到 JSON 文件"""
        try:
            with open(self.storage_path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2, default=str)
            return True
        except Exception as e:
            print(f"Save failed: {e}")
            return False

    def load(self) -> Any:
        """从 JSON 文件加载数据"""
        if not self.storage_path.exists():
            return None

        try:
            with open(self.storage_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            print(f"Load failed: {e}")
            return None

    def clear(self) -> bool:
        """清除数据文件"""
        try:
            if self.storage_path.exists():
                self.storage_path.unlink()
            return True
        except Exception as e:
            print(f"Clear failed: {e}")
            return False
