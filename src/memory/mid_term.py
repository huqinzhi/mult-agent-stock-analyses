"""
中期记忆模块

管理经验日志、用户偏好和股票画像。
"""

import json
from datetime import datetime
from pathlib import Path
from typing import List, Optional

from src.memory.base import JSONMemory
from src.memory.schemas import ExperienceLog, StockProfile, UserPreferences


class MidTermMemory:
    """中期记忆管理器"""

    def __init__(self, base_path: str = "memory/mid_term"):
        self.base_path = Path(base_path)
        self.experience_logs = JSONMemory(str(self.base_path / "experience_logs.json"))
        self.user_prefs = JSONMemory(str(self.base_path / "user_preferences.json"))

    def add_experience(self, log: ExperienceLog) -> bool:
        """添加经验日志"""
        logs = self.experience_logs.load() or []
        logs.append(log.model_dump())
        return self.experience_logs.save(logs)

    def get_recent_experiences(self, limit: int = 10) -> List[ExperienceLog]:
        """获取最近的经验"""
        logs = self.experience_logs.load() or []
        return logs[-limit:]

    def update_stock_profile(self, profile: StockProfile) -> bool:
        """更新股票画像"""
        profiles = self._load_stock_profiles()
        profiles[profile.ts_code] = profile.model_dump()
        return self._save_stock_profiles(profiles)

    def get_stock_profile(self, ts_code: str) -> Optional[StockProfile]:
        """获取股票画像"""
        profiles = self._load_stock_profiles()
        data = profiles.get(ts_code)
        if data:
            return StockProfile(**data)
        return None

    def update_user_preferences(self, prefs: UserPreferences) -> bool:
        """更新用户偏好"""
        return self.user_prefs.save(prefs.model_dump())

    def get_user_preferences(self) -> UserPreferences:
        """获取用户偏好"""
        data = self.user_prefs.load()
        if data:
            return UserPreferences(**data)
        return UserPreferences()

    def _load_stock_profiles(self) -> dict:
        path = self.base_path / "stock_profiles.json"
        if path.exists():
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        return {}

    def _save_stock_profiles(self, profiles: dict) -> bool:
        path = self.base_path / "stock_profiles.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        try:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(profiles, f, ensure_ascii=False, indent=2)
            return True
        except Exception:
            return False
