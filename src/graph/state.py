"""
LangGraph 工作流共享状态定义模块

定义整个多智能体系统中使用的数据结构：
- StockQuery: 用户查询请求（股票代码、日期范围）
- AgentResult: 单个 Agent 的分析结果（评分、结论、置信度）
- DataQuality: 数据质量指标（完整性、时效性、一致性）
- AgentState: 工作流共享状态（所有 Agent 读写的黑板）

数据流：
    CLI 输入 → StockQuery → AgentState.query
    各 Agent 分析 → AgentResult → AgentState.xxx_result
    Supervisor 汇总 → AgentState.final_report → 输出报告

使用示例：
    from src.graph.state import AgentState, StockQuery, AgentResult

    query = StockQuery(ts_code="000001.SZ", stock_name="平安银行")
    state = AgentState(query=query, messages=[], completed_tasks=[])
"""

# ─── 引入 typing 模块 ─────────────────────────────────────────────────────────
# typing 模块提供 Python 类型注解的支持
# Literal: 限制取值范围（如 query_type 只能是 "quick" 或 "comprehensive"）
# Optional: 允许值为 None（如 Optional[str] 等价于 str | None）
# Any: 任意类型（不做类型检查）
# Dict, List, Tuple: 集合类型注解
from typing import Any, Dict, List, Literal, Optional

# ─── 引入 Pydantic ────────────────────────────────────────────────────────────
# Pydantic 是数据验证库，用于定义数据模型（类似 TypeScript 的 interface）
# BaseModel: Pydantic 数据模型的基类
# Field: 给字段添加元数据（如默认值、描述）
from pydantic import BaseModel, Field

# ─── 引入 LangGraph 的 add_messages ─────────────────────────────────────────
# add_messages 是一个 reducer 函数，用于合并消息列表
# 当多个节点往状态里添加消息时，会把新消息追加到现有消息后面
from typing_extensions import Annotated  # 用于给类型添加注解（如降级）

from langgraph.graph import add_messages  # 消息合并逻辑


# ══════════════════════════════════════════════════════════════════════════════
# 数据质量模型
# ══════════════════════════════════════════════════════════════════════════════

class DataQuality(BaseModel):
    """
    数据质量指标

    用于评估数据源的可靠性，影响 Agent 分析结果的置信度。

    属性：
        quality_score: 综合质量分数（0-1），由各维度加权计算得出
        completeness: 完整性（0-1），数据完整程度（非空率）
        timeliness: 时效性（0-1），数据的新鲜程度（距今天数）
        consistency: 一致性（0-1），数据内部逻辑一致性（如收盘价是否在高低价之间）
        details: 详细的质量评估信息（各维度的具体问题）
    """
    quality_score: float = 1.0   # 综合质量分数（0-1），1.0 = 完美
    completeness: float = 1.0    # 完整性（0-1），空值比例越低越完整
    timeliness: float = 1.0      # 时效性（0-1），数据越新鲜越高
    consistency: float = 1.0    # 一致性（0-1），数据逻辑一致无矛盾
    details: Dict[str, Any] = Field(default_factory=dict)  # 详细问题描述


class DataQualitySummary(BaseModel):
    """
    数据质量汇总

    汇总各维度数据的质量指标，用于综合评估分析结果的可靠性。
    """
    kline_quality: Optional[DataQuality] = None         # K线数据质量
    money_flow_quality: Optional[DataQuality] = None   # 资金流数据质量
    industry_quality: Optional[DataQuality] = None     # 行业数据质量
    news_quality: Optional[DataQuality] = None          # 新闻数据质量


# ══════════════════════════════════════════════════════════════════════════════
# 查询请求模型
# ══════════════════════════════════════════════════════════════════════════════

class StockQuery(BaseModel):
    """
    股票查询请求

    用户输入的查询参数，包含股票代码、名称、查询类型和日期范围。

    使用示例：
        query = StockQuery(ts_code="000001.SZ", stock_name="平安银行")
        # 或
        query = StockQuery(ts_code="000001.SZ", query_type="comprehensive")
    """
    ts_code: str  # 股票代码（如 "000001.SZ"）
                  # 格式：6位数字 + .SZ（深圳）或 .SH（上海）

    stock_name: Optional[str] = None  # 股票名称（用于显示，如"平安银行"）

    query_type: Literal["quick", "comprehensive"] = "comprehensive"
    # 查询类型：
    # - "quick": 快速扫描（数据量少，分析快）
    # - "comprehensive": 全面分析（默认，近90日数据）

    start_date: Optional[str] = None  # 开始日期，格式 YYYYMMDD（如 "20240101"）
                                      # 默认值：90天前

    end_date: Optional[str] = None    # 结束日期，格式 YYYYMMDD
                                      # 默认值：今天

    def __init__(self, **data):
        """
        初始化股票查询，自动填充默认日期

        如果用户没有指定 start_date 或 end_date，自动设为近90日。
        """
        # 如果未提供 start_date，自动计算90天前的日期
        if data.get("start_date") is None:
            from datetime import datetime, timedelta  # 日期时间处理
            end = datetime.now()
            start = end - timedelta(days=90)  # 90天前
            data["start_date"] = start.strftime("%Y%m%d")  # 格式化为 YYYYMMDD

        # 如果未提供 end_date，默认今天
        if data.get("end_date") is None:
            from datetime import datetime
            data["end_date"] = datetime.now().strftime("%Y%m%d")

        super().__init__(**data)


# ══════════════════════════════════════════════════════════════════════════════
# Agent 结果模型
# ══════════════════════════════════════════════════════════════════════════════

class AgentResult(BaseModel):
    """
    单个 Agent 的分析结果

    每个 Agent 分析完成后，生成一个 AgentResult，包含评分、结论、置信度等。

    使用示例：
        result = AgentResult(
            agent_name="quantitative",
            score=75.0,
            confidence=0.85,
            conclusion="技术面偏强，RSI 处于健康区间",
            key_findings=["MA5 上穿 MA20 金叉", "成交量放大 1.5 倍"],
            raw_data={"rsi": 65, "macd": "金叉"}
        )
    """
    agent_name: str                          # Agent 名称（路由键）
                                              # 如 "quantitative", "chart", "risk"

    score: Optional[float] = None            # 评分 0-100
                                              # 50 = 中性，>70 = 偏强，<30 = 偏弱

    confidence: Optional[float] = None       # 置信度 0-1
                                              # 基于数据质量：数据质量高 → 置信度高

    data_quality: Optional[DataQuality] = None  # 数据质量指标

    conclusion: str = ""                     # 分析结论（一句话总结）
                                             # 如 "技术面偏强，MACD 现金叉"

    recommendation: str = ""                 # 中性建议（非投资建议）
                                             # 如 "技术面分析已完成，请参考评分"

    key_findings: List[str] = Field(default_factory=list)
    # 关键发现列表（3-5个）
    # 如 ["MA5 上穿 MA20 金叉", "成交量放大 1.5 倍", "RSI 处于 65 区间"]

    raw_data: Dict[str, Any] = Field(default_factory=dict)
    # 原始数据（Agent -specific 数据，如技术指标值、止损位等）
    # 如 risk_agent 会返回 raw_data["stop_loss"] = {"volatility_stop_price": 9.5}


# ══════════════════════════════════════════════════════════════════════════════
# Agent 状态（LangGraph 共用状态）
# ══════════════════════════════════════════════════════════════════════════════

class AgentState(BaseModel):
    """
    LangGraph 工作流共享状态

    这是整个工作流的"共享黑板"：
    - 所有 Agent 都读写这个状态
    - Supervisor 读取各 Agent 的结果，生成最终报告
    - 每个 Agent 完成后写入自己的结果（xxx_result）

    状态转换流程：
        初始状态 → Supervisor → (并行分发) → 6个Agent → Supervisor → END

    属性详解：
        messages: 对话历史（LangGraph 内置，用于 add_messages 合并）
        query: 用户查询（股票代码、日期范围）
        6个 xxx_result: 各 Agent 的分析结果
        final_report: Supervisor 生成的综合报告
        routing_target: 路由控制（"parallel" = 分发任务）
        completed_tasks: 已完成的 Agent 列表
    """
    # ── LangGraph 内置字段 ──────────────────────────────────────────────────

    messages: Annotated[List[Any], add_messages] = Field(default_factory=list)
    # 消息列表，使用 add_messages reducer 合并新消息
    # Annotated[List[Any], add_messages] 表示列表会被合并而非替换

    # ── 用户查询 ────────────────────────────────────────────────────────────

    query: Annotated[Optional[StockQuery], lambda a, b: a if a is not None else b] = None
    # 查询请求，使用 lambda reducer：优先使用非 None 值

    data_quality_summary: Annotated[DataQualitySummary, lambda a, b: b if b is not None else a] = Field(default_factory=DataQualitySummary)
    # 数据质量汇总，lambda reducer 选择后者（非 None 的值）

    # ── 6 个子 Agent 的分析结果 ─────────────────────────────────────────────
    # 每个 Agent 完成后将自己的结果写入对应字段

    quantitative_result: Annotated[Optional[AgentResult], lambda a, b: b if b is not None else a] = None
    # 量化分析师结果（技术指标、资金流向）
    # lambda reducer 表示：如果新值非 None，则使用新值（覆盖旧值）

    chart_result: Annotated[Optional[AgentResult], lambda a, b: b if b is not None else a] = None
    # 图表分析师结果（K线形态、支撑阻力位）

    intelligence_result: Annotated[Optional[AgentResult], lambda a, b: b if b is not None else a] = None
    # 情报官结果（政策、行业动态）

    risk_result: Annotated[Optional[AgentResult], lambda a, b: b if b is not None else a] = None
    # 风险评估师结果（风险量化、止损位）

    fundamental_result: Annotated[Optional[AgentResult], lambda a, b: b if b is not None else a] = None
    # 基本面分析师结果（财报、估值）

    sentiment_result: Annotated[Optional[AgentResult], lambda a, b: b if b is not None else a] = None
    # 舆情监控师结果（情绪、分析师评级）

    # ── 最终输出 ────────────────────────────────────────────────────────────

    final_report: Annotated[Optional[str], lambda a, b: b if b is not None else a] = None
    # Supervisor 生成的综合报告
    # 报告经过 DisclaimerFilter 过滤 + MandatoryDisclaimer 注入

    # ── 路由控制 ────────────────────────────────────────────────────────────

    routing_target: Annotated[Optional[Literal[
        "quantitative", "chart", "intelligence",
        "risk", "fundamental", "sentiment",
        "parallel", "report"
    ]], lambda a, b: a if a is not None else b] = None
    # 路由目标，控制条件边的走向
    # - "parallel": Supervisor 已设置，分发任务到 6 个 Agent
    # - None: 不设置路由，使用默认逻辑

    # ── 执行追踪 ────────────────────────────────────────────────────────────

    completed_tasks: Annotated[List[str], lambda a, b: a + b if b else a] = Field(default_factory=list)
    # 已完成的 Agent 列表，用于追踪分析进度
    # lambda reducer: 合并两个列表（a + b）

    # ── Batch 相关字段（V2 批量分析使用）───────────────────────────────────

    stock_list: Optional[List[Dict[str, Any]]] = None       # 候选股票列表（输入）
    prescreening_target: Optional[int] = None               # 目标候选数量（默认 top_n*2）
    candidates: Optional[List[Dict[str, Any]]] = None       # 筛选后的候选股票（输出）
    prescreening_completed: Optional[bool] = None           # 初筛是否完成
    prescreening_reason: Optional[str] = None               # 初筛摘要
    prescreening_quality: Optional[DataQuality] = None     # 初筛数据质量


# ══════════════════════════════════════════════════════════════════════════════
# 辅助函数
# ══════════════════════════════════════════════════════════════════════════════

def calculate_confidence_from_quality(
    data_quality: Optional[DataQuality],
    base_confidence: float = 0.8,
) -> float:
    """
    基于数据质量计算置信度

    数据质量越高，置信度越高。

    Args:
        data_quality: 数据质量指标（可为 None）
        base_confidence: 基础置信度（当 data_quality 为 None 时使用）

    Returns:
        调整后的置信度（0-1）
    """
    if data_quality is None:
        return base_confidence  # 无数据质量信息，返回默认值

    # 综合质量分数（单个维度）
    quality_score = data_quality.quality_score

    # 加权计算综合置信度
    # 各维度权重：quality_score 40%, completeness 20%, timeliness 20%, consistency 20%
    weighted = (
        quality_score * 0.4 +
        data_quality.completeness * 0.2 +
        data_quality.timeliness * 0.2 +
        data_quality.consistency * 0.2
    )

    # 最终置信度 = 加权分数 * 基础置信度
    return max(0.0, min(1.0, weighted * base_confidence))


def calculate_weighted_score(
    results: List[AgentResult],
    weights: Dict[str, float],
) -> float:
    """
    计算加权综合评分

    根据各 Agent 的权重，计算加权平均分。

    Args:
        results: Agent 结果列表
        weights: 权重字典（key 为 agent_name 或路由键）

    Returns:
        加权综合评分（0-100）

    示例：
        results = [quantitative_result, chart_result, ...]
        weights = {"quantitative": 0.25, "chart": 0.15, ...}
        score = calculate_weighted_score(results, weights)
    """
    if not results:
        return 0.0  # 无结果返回 0

    total_score = 0.0   # 加权总分
    total_weight = 0.0  # 权重总和

    for result in results:
        if result.score is None:
            continue  # 跳过无评分的结果

        # 尝试从 agent_name 匹配权重
        weight = weights.get(result.agent_name, 0.0)
        if weight == 0.0:
            # 尝试从路由键匹配（如 "quantitative"）
            for key, w in weights.items():
                if key in result.agent_name.lower():
                    weight = w
                    break

        total_score += result.score * weight
        total_weight += weight

    if total_weight == 0:
        return 0.0  # 无有效权重

    # 归一化：加权总分 / 权重总和 * 100
    return total_score / total_weight * 100