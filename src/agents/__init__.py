"""Agent 模块

6 个专业 Agent：
- 量化分析师 (quantitative): 25%
- 图表分析师 (chart): 15%
- 情报官 (intelligence): 10%
- 风险评估师 (risk): 20%
- 基本面分析师 (fundamental): 20%
- 舆情监控师 (sentiment): 10%

所有 Agent 权重统一在 src/config.py 的 AGENT_WEIGHTS 中配置。
"""
from .quantitative_analyst import create_quantitative_analyst
from .chart_analyst import create_chart_analyst
from .intelligence_officer import create_intelligence_officer
from .risk_analyst import create_risk_analyst
from .fundamental_analyst import create_fundamental_analyst
from .sentiment_analyst import create_sentiment_analyst
from .supervisor import create_supervisor
from .prescreening_agent import create_prescreening_agent

__all__ = [
    "create_quantitative_analyst",
    "create_chart_analyst",
    "create_intelligence_officer",
    "create_risk_analyst",
    "create_fundamental_analyst",
    "create_sentiment_analyst",
    "create_supervisor",
    "create_prescreening_agent",
]
