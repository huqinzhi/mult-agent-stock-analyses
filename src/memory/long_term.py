"""
长期记忆模块

管理市场知识、行业模式和成功策略。
"""

import json
from datetime import datetime
from pathlib import Path
from typing import List, Optional, Dict

from src.memory.base import JSONMemory
from pydantic import BaseModel, Field


class IndustryPattern(BaseModel):
    """行业模式"""
    industry_name: str
    characteristics: List[str] = Field(default_factory=list)
    key_indicators: List[str] = Field(default_factory=list)
    common_risks: List[str] = Field(default_factory=list)
    recommended_agents: List[str] = Field(default_factory=list)


class AnalysisStrategy(BaseModel):
    """分析策略"""
    strategy_name: str
    applicable_industries: List[str] = Field(default_factory=list)
    applicable_intents: List[str] = Field(default_factory=list)
    recommended_agents: List[str] = Field(default_factory=list)
    success_rate: float = 0.0
    notes: str = ""


class MarketKnowledge(BaseModel):
    """市场知识"""
    last_updated: datetime = Field(default_factory=datetime.now)
    market_summary: str = ""
    key_events: List[str] = Field(default_factory=list)


class LongTermMemory:
    """长期记忆管理器"""

    def __init__(self, base_path: str = "memory/long_term"):
        self.base_path = Path(base_path)
        self.market_knowledge = JSONMemory(str(self.base_path / "market_knowledge.json"))
        self.industry_patterns = JSONMemory(str(self.base_path / "industry_patterns.json"))
        self.successful_strategies = JSONMemory(str(self.base_path / "successful_strategies.json"))

    def save_market_knowledge(self, knowledge: MarketKnowledge) -> bool:
        """保存市场知识"""
        return self.market_knowledge.save(knowledge.model_dump())

    def get_market_knowledge(self) -> Optional[MarketKnowledge]:
        """获取市场知识"""
        data = self.market_knowledge.load()
        if data:
            return MarketKnowledge(**data)
        return None

    def save_industry_pattern(self, pattern: IndustryPattern) -> bool:
        """保存行业模式"""
        patterns = self.industry_patterns.load() or {}
        patterns[pattern.industry_name] = pattern.model_dump()
        return self.industry_patterns.save(patterns)

    def get_industry_pattern(self, industry: str) -> Optional[IndustryPattern]:
        """获取行业模式"""
        patterns = self.industry_patterns.load() or {}
        data = patterns.get(industry)
        if data:
            return IndustryPattern(**data)
        return None

    def get_all_industry_patterns(self) -> Dict[str, IndustryPattern]:
        """获取所有行业模式"""
        patterns = self.industry_patterns.load() or {}
        return {k: IndustryPattern(**v) for k, v in patterns.items()}

    def add_successful_strategy(self, strategy: AnalysisStrategy) -> bool:
        """添加成功策略"""
        strategies = self.successful_strategies.load() or []
        strategies.append(strategy.model_dump())
        return self.successful_strategies.save(strategies)

    def get_successful_strategies(self) -> List[AnalysisStrategy]:
        """获取成功策略列表"""
        data = self.successful_strategies.load() or []
        return [AnalysisStrategy(**s) for s in data]

    def get_recommended_agents(self, industry: str = None, intent: str = None) -> List[str]:
        """根据行业和意图获取推荐的 Agent"""
        strategies = self.get_successful_strategies()
        recommended = []

        for strategy in strategies:
            if industry and industry in strategy.applicable_industries:
                recommended.extend(strategy.recommended_agents)
            if intent and intent in strategy.applicable_intents:
                recommended.extend(strategy.recommended_agents)

        return list(set(recommended))
