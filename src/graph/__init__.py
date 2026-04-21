"""
LangGraph 工作流模块

提供：
- AgentState: LangGraph 共享状态
- build_stock_analysis_graph: 构建股票分析工作流

使用示例：
    from src.graph import AgentState, build_stock_analysis_graph

    graph = build_stock_analysis_graph(weight_mode="auto")
    state = AgentState(query=query, messages=[], completed_tasks=[])
    result = graph.invoke(state)
"""

from src.graph.state import (
    AgentState,
    AgentResult,
    StockQuery,
    DataQuality,
    DataQualitySummary,
    calculate_confidence_from_quality,
    calculate_weighted_score,
)


def __getattr__(name):
    """延迟导入 builder，避免循环依赖"""
    if name == "build_stock_analysis_graph":
        from src.graph.builder import build_stock_analysis_graph

        return build_stock_analysis_graph
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

__all__ = [
    "AgentState",
    "AgentResult",
    "StockQuery",
    "DataQuality",
    "DataQualitySummary",
    "calculate_confidence_from_quality",
    "calculate_weighted_score",
    "build_stock_analysis_graph",
]