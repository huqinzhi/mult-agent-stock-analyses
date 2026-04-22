"""
记忆系统数据结构定义
"""

from datetime import datetime
from typing import List, Optional
from pydantic import BaseModel, Field


class ExperienceLog(BaseModel):
    """经验日志"""
    timestamp: datetime = Field(default_factory=datetime.now)
    task_type: str
    stock_code: str
    intent_type: str
    agents_used: List[str]
    execution_time: float
    success: bool
    quality_score: float
    key_learnings: List[str] = Field(default_factory=list)
    improvement_notes: str = ""


class StockProfile(BaseModel):
    """股票画像"""
    ts_code: str
    name: str
    analysis_count: int = 0
    last_analysis: Optional[datetime] = None
    common_issues: List[str] = Field(default_factory=list)
    preferred_agents: List[str] = Field(default_factory=list)
    avg_quality_score: float = 0.0


class UserPreferences(BaseModel):
    """用户偏好"""
    default_weight_mode: str = "fixed"
    default_notification: str = "console"
    preferred_agents: List[str] = Field(default_factory=list)
    analysis_count: int = 0
