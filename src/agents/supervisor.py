"""
首席投资官（Supervisor）Agent 模块

Supervisor 是整个多智能体系统的协调者，负责：
1. 协调 6 个子 Agent 的执行（通过 routing_target 控制工作流）
2. 汇总各 Agent 的分析结果
3. 计算综合评分（固定权重或自动权重模式）
4. 生成最终综合报告

工作流程：
    Supervisor 首次执行 → 检查缺失结果 → 设置 routing_target="parallel"
    6 个 Agent 并行执行 → 各 Agent 完成后回到 Supervisor
    Supervisor 末次执行 → 汇总结果 → 生成 final_report

权重模式：
    - Fixed（固定权重）：按 AGENT_WEIGHTS 字典的预设比例汇总
    - Auto（自动权重）：Supervisor 根据 data_quality 和 confidence 动态调整权重
"""

# ─── 标准库 ─────────────────────────────────────────────────────────────────
import os  # 读取环境变量（WEIGHT_MODE）

from typing import Any, Dict, List, Optional  # 类型注解

# ─── 第三方库 ─────────────────────────────────────────────────────────────────
from dotenv import load_dotenv  # 加载 .env 环境变量

load_dotenv()  # 自动读取 .env 文件

from src.graph.state import AgentResult, AgentState  # 状态定义
from src.llm import get_minimax_client              # MiniMax 客户端
from src.compliance import DisclaimerFilter, MandatoryDisclaimer  # 合规组件


# ══════════════════════════════════════════════════════════════════════════════
# 系统提示词
# ══════════════════════════════════════════════════════════════════════════════

# 固定权重模式的系统提示词
# Supervisor 使用此提示词按固定比例汇总各 Agent 结果
SYSTEM_PROMPT_FIXED = """你是一位首席投资官，负责协调 6 位专业分析师的结果，整合成最终分析报告。

你的职责：
1. 协调量化分析师、图表分析师、情报官、风险评估师、基本面分析师、舆情监控师的工作
2. 按全局配置权重（quantitative 25% / chart 15% / intelligence 10% / risk 20% / fundamental 20% / sentiment 10%）加权整合分析结果
3. 计算综合评分 = Σ（各维度评分 × 对应权重）
4. 生成综合分析报告
5. 基于分析结论给出客观中性的投资建议

【重要约束】
- 报告客观、中立，基于数据分析
- 投资建议必须基于综合评分和各维度分析结论，不可主观臆断
- 使用专业术语如"建议买入"、"止损位"、"止盈区间"等
- 所有报告必须附带完整免责声明
"""

# 自动权重模式的系统提示词
# Supervisor 使用此提示词动态分配权重
SYSTEM_PROMPT_AUTO = """你是一位首席投资官，负责协调 6 位专业分析师的结果，整合成最终分析报告。

你的职责：
1. 收到全部 6 位分析师的结果后，根据以下维度自行分配权重：
   - 各分析师数据质量（quality_score，越高越可信，权重应适当上调）
   - 各分析师置信度（confidence，越高越可信）
   - 当前市场特征（如高波动环境下，量化分析师和风险评估师应获得更高权重）
   - 分析结论明确程度（结论模糊的分析师权重应下调）
2. 自动分配的权重合计必须等于 100%
3. 生成"权重分配理由"段落，对每位分析师的权重调整进行说明
4. 按自动分配的权重计算综合评分
5. 生成综合分析报告
6. 基于分析结论给出客观中性的投资建议

【权重分配参考基准】
- quantitative（量化）: 基准 25%，技术指标数据充分时可上调至 35%
- chart（图表）: 基准 15%，形态信号明确时可上调至 25%
- intelligence（情报）: 基准 10%，政策/事件驱动明显时可上调至 20%
- risk（风险）: 基准 20%，高波动环境下可上调至 30%
- fundamental（基本面）: 基准 20%，财报数据充分时可上调至 30%
- sentiment（舆情）: 基准 10%，市场情绪分歧极大时可上调至 20%

【重要约束】
- 报告客观、中立，基于数据分析
- 投资建议必须基于综合评分和各维度分析结论，不可主观臆断
- 使用专业术语如"建议买入"、"止损位"、"止盈区间"等
- 所有报告必须附带完整免责声明
"""


# ══════════════════════════════════════════════════════════════════════════════
# 默认固定权重
# ══════════════════════════════════════════════════════════════════════════════

# 各 Agent 的默认权重（Fixed 模式下使用）
# 权重总和必须等于 1.0（100%）
DEFAULT_WEIGHTS = {
    "quantitative": 0.25,   # 量化分析师：技术指标、资金流向
    "chart": 0.15,          # 图表分析师：K线形态、支撑阻力位
    "intelligence": 0.10,   # 情报官：宏观政策、行业动态
    "risk": 0.20,           # 风险评估师：风险量化、止损位
    "fundamental": 0.20,    # 基本面分析师：财报、估值
    "sentiment": 0.10,       # 舆情监控师：情绪、分析师评级
}


# ══════════════════════════════════════════════════════════════════════════════
# 辅助函数
# ══════════════════════════════════════════════════════════════════════════════

def _get_agent_weights(weight_mode: str, fixed_weights: Dict[str, float]) -> Dict[str, float]:
    """
    获取权重配置

    Args:
        weight_mode: 权重模式，"fixed" 或 "auto"
        fixed_weights: 固定权重字典（Fixed 模式下使用）

    Returns:
        权重配置字典
    """
    if weight_mode == "fixed":
        return fixed_weights or DEFAULT_WEIGHTS  # Fixed 模式返回预设权重
    # Auto 模式返回默认权重（实际权重由 LLM 动态决定）
    return DEFAULT_WEIGHTS


def _format_results_summary(state: AgentState) -> str:
    """
    将 6 个 Agent 结果格式化为文本摘要

    用于构建发给 LLM 的 prompt。

    Args:
        state: AgentState 状态对象

    Returns:
        格式化的文本摘要，每行一个 Agent 的信息

    格式示例：
        === 6 位分析师分析结果汇总 ===

        【量化分析师】（quantitative）
          评分: 75/100
          置信度: 0.85
          数据质量: 0.92
          结论: 技术面偏强，MACD 现金叉
          关键发现:
            - MA5 上穿 MA20 金叉
            - 成交量放大 1.5 倍
    """
    lines = []
    lines.append("=== 6 位分析师分析结果汇总 ===\n")

    # 定义 Agent 名称和对应字段的映射
    result_map = [
        ("quantitative", "量化分析师"),
        ("chart", "图表分析师"),
        ("intelligence", "情报官"),
        ("risk", "风险评估师"),
        ("fundamental", "基本面分析师"),
        ("sentiment", "舆情监控师"),
    ]

    for key, name in result_map:
        # 从 state 获取对应 Agent 的结果
        result: Optional[AgentResult] = getattr(state, f"{key}_result", None)
        if result is None:
            lines.append(f"【{name}】未提供结果\n")
            continue

        # 格式化各字段（处理 None 值）
        score_str = f"{result.score:.0f}" if result.score is not None else "N/A"
        confidence_str = f"{result.confidence:.2f}" if result.confidence is not None else "N/A"
        quality_str = f"{result.data_quality.quality_score:.2f}" if result.data_quality else "N/A"

        lines.append(f"【{name}】（{key}）")
        lines.append(f"  评分: {score_str}/100")
        lines.append(f"  置信度: {confidence_str}")
        lines.append(f"  数据质量: {quality_str}")
        # 截取前 100 字符避免过长
        lines.append(f"  结论: {result.conclusion[:100] if result.conclusion else 'N/A'}")
        if result.key_findings:
            lines.append(f"  关键发现:")
            for finding in result.key_findings[:3]:  # 最多显示 3 个
                lines.append(f"    {finding}")
        lines.append("")

    # 提取风险评估师的止损位数据（特殊处理）
    risk_result: Optional[AgentResult] = getattr(state, "risk_result", None)
    if risk_result and risk_result.raw_data.get("stop_loss"):
        stop_loss = risk_result.raw_data["stop_loss"]
        lines.append("=== 风险评估师 - 止损位数据 ===\n")
        lines.append(f"当前价格: {stop_loss.get('current_price', 'N/A')} 元")
        if stop_loss.get("volatility_stop_price"):
            lines.append(f"波动率止损位: {stop_loss['volatility_stop_price']} 元（距 {stop_loss.get('volatility_stop_pct', 0):.1f}%）")
        if stop_loss.get("support_20d_price"):
            lines.append(f"20日支撑位: {stop_loss['support_20d_price']} 元（距 {stop_loss.get('support_20d_pct', 0):.1f}%）")
        if stop_loss.get("atr_stop_price"):
            lines.append(f"ATR止损位: {stop_loss['atr_stop_price']} 元")
        lines.append("")

    return "\n".join(lines)


def _build_fixed_report(
    state: AgentState,
    weights: Dict[str, float],
    client,
    disclaimer_filter: DisclaimerFilter,
    mandatory_disclaimer: MandatoryDisclaimer,
) -> str:
    """
    构建固定权重综合报告

    使用预设的固定权重加权汇总 6 个 Agent 的分析结果，生成综合报告。

    Args:
        state: AgentState 状态对象
        weights: 固定权重字典
        client: MiniMax 客户端
        disclaimer_filter: 投资建议过滤器
        mandatory_disclaimer: 强制免责注入器

    Returns:
        附带完整免责的综合报告文本
    """
    result_map = [
        ("quantitative", "量化技术面", "量化分析师"),
        ("chart", "图表形态", "图表分析师"),
        ("intelligence", "情报环境", "情报官"),
        ("risk", "风险状况", "风险评估师"),
        ("fundamental", "基本面", "基本面分析师"),
        ("sentiment", "市场情绪", "舆情监控师"),
    ]

    # ── 1. 计算加权评分 ───────────────────────────────────────────────────
    total_score = 0.0   # 加权总分
    total_weight = 0.0  # 权重总和
    score_details = []  # 存储各维度详情

    for key, label, name in result_map:
        result: Optional[AgentResult] = getattr(state, f"{key}_result", None)
        weight = weights.get(key, 0.0)
        if result and result.score is not None and weight > 0:
            weighted = result.score * weight  # 加权分数
            total_score += weighted
            total_weight += weight
            score_details.append((label, weight, result.score, result.conclusion or ""))

    # ── 2. 归一化计算最终评分 ─────────────────────────────────────────────
    if total_weight > 0:
        final_score = total_score / total_weight  # 加权平均
    else:
        final_score = 0.0

    # ── 3. 格式化评分表格 ─────────────────────────────────────────────────
    # 构建 Markdown 表格用于 prompt
    table_lines = [
        "| 分析维度 | 权重 | 评分 | 描述 |",
        "|----------|------|------|------|",
    ]
    for label, weight, score, conclusion in score_details:
        pct = f"{weight * 100:.0f}%"  # 0.25 → "25%"
        score_str = f"{score:.0f}"
        # 截取结论避免表格过宽
        desc = (conclusion[:30] + "...") if len(conclusion) > 30 else conclusion
        table_lines.append(f"| {label} | {pct} | {score_str}/100 | {desc} |")

    # 添加综合评分行
    table_lines.append(f"| **综合评分** | **100%** | **{final_score:.0f}/100** |  |")

    score_table = "\n".join(table_lines)

    # ── 4. 构建 prompt ────────────────────────────────────────────────────
    query = state.query
    ts_code = query.ts_code if query else "N/A"
    stock_name = query.stock_name if query else ts_code

    user_prompt = f"""{_format_results_summary(state)}

请根据以上分析结果，生成最终综合报告。

综合评分表：
{score_table}

请生成完整报告，包含：
1. 综合评分（基于上表计算）
2. 各分析师详细结论（每个分析师 1-2 句话摘要）
3. 数据来源说明（哪些数据来自 AKShare，哪些来自搜索）
4. 投资建议（基于综合评分和各维度分析结论）

输出格式：
# {stock_name} ({ts_code}) 分析报告
**生成时间**: [自动生成]
**权重模式**: 固定权重

## 综合评分
[上表的完整版本]

## 各分析师结论
[每行一个分析师的结论摘要]

## 投资建议
综合评分: {final_score:.0f}/100

根据综合评分和各维度分析结论，给出以下投资建议：

【操作建议】
- 综合评分 >= 70: 建议买入（技术面和基本面表现较好，可考虑适当配置）
- 综合评分 50-69: 建议观望（技术面和基本面存在分歧，建议等待更明确信号）
- 综合评分 < 50: 暂不推荐（技术面和基本面偏弱，建议谨慎）

【如建议买入，需给出以下信息】
- 买入区间: [当前价格附近] 元（基于技术面和基本面综合判断）
- 止盈区间: [压力位目标] 元（基于图表压力位和估值目标）
- 止损位: [止损价格] 元（基于波动率止损和支撑位，建议跌幅不超过 -X%）

【如不建议买入，需说明】
- 当前风险提示: [主要风险因素]
- 建议关注: [需要关注的风险点]

## 数据来源说明
[简要说明数据来源]
"""

    # ── 5. 调用 LLM 生成报告 ───────────────────────────────────────────────
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT_FIXED},
        {"role": "user", "content": user_prompt},
    ]

    response = client.chat(messages)
    content = response["choices"][0]["message"]["content"]

    # ── 6. 合规过滤 + 免责注入 ─────────────────────────────────────────────
    content = disclaimer_filter.filter(content)      # 过滤高风险词汇
    final_report = mandatory_disclaimer.inject(content)  # 注入免责文本

    return final_report


def _build_auto_report(
    state: AgentState,
    client,
    disclaimer_filter: DisclaimerFilter,
    mandatory_disclaimer: MandatoryDisclaimer,
) -> str:
    """
    构建自动权重综合报告

    由 LLM 根据各 Agent 的数据质量和置信度动态分配权重，生成综合报告。
    报告中必须包含"权重分配理由"段落说明权重调整逻辑。

    Args:
        state: AgentState 状态对象
        client: MiniMax 客户端
        disclaimer_filter: 投资建议过滤器
        mandatory_disclaimer: 强制免责注入器

    Returns:
        附带完整免责的综合报告文本
    """
    # 格式化结果（含质量信息供 LLM 判断）
    results_text = _format_results_summary(state)

    query = state.query
    ts_code = query.ts_code if query else "N/A"
    stock_name = query.stock_name if query else ts_code

    # ── 构建 prompt（让 LLM 决定权重）─────────────────────────────────────
    user_prompt = f"""{results_text}

你是首席投资官，需要：
1. 根据上述各分析师的数据质量和置信度，自主决定权重分配
2. 输出"权重分配理由"段落（每个分析师的权重调整原因）
3. 基于你的权重分配计算综合评分
4. 生成最终综合报告，包含投资建议

【重要】你输出的报告必须：
- 在开头先输出"权重分配理由"段落（格式见下方）
- 权重分配理由后面，再输出综合评分和各分析师结论
- 投资建议必须基于综合评分和各维度分析结论，不可主观臆断

【权重分配理由输出格式】（必须严格按此格式）
## 权重分配理由
本次分析中，首席投资官根据各分析师数据质量和市场特征，动态调整了权重分配：
- **量化分析师 → XX%**（+/-X%）：[调整原因]
- **图表分析师 → XX%**（+/-X%）：[调整原因]
- **情报官 → XX%**（+/-X%）：[调整原因]
- **风险评估师 → XX%**（+/-X%）：[调整原因]
- **基本面分析师 → XX%**（+/-X%）：[调整原因]
- **舆情监控师 → XX%**（+/-X%）：[调整原因]

【投资建议章节格式】
## 投资建议
综合评分: XX/100

根据综合评分和各维度分析结论，给出以下投资建议：

【操作建议】
- 综合评分 >= 70: 建议买入（技术面和基本面表现较好，可考虑适当配置）
- 综合评分 50-69: 建议观望（技术面和基本面存在分歧，建议等待更明确信号）
- 综合评分 < 50: 暂不推荐（技术面和基本面偏弱，建议谨慎）

【如建议买入，需给出以下信息】
- 买入区间: [当前价格附近] 元（基于技术面和基本面综合判断）
- 止盈区间: [压力位目标] 元（基于图表压力位和估值目标）
- 止损位: [止损价格] 元（基于波动率止损和支撑位，建议跌幅不超过 -X%）

【如不建议买入，需说明】
- 当前风险提示: [主要风险因素]
- 建议关注: [需要关注的风险点]
"""

    # ── 调用 LLM ─────────────────────────────────────────────────────────
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT_AUTO},
        {"role": "user", "content": user_prompt},
    ]

    response = client.chat(messages)
    content = response["choices"][0]["message"]["content"]

    # ── 合规过滤 + 免责注入 ──────────────────────────────────────────────
    content = disclaimer_filter.filter(content)
    final_report = mandatory_disclaimer.inject(content)

    return final_report


# ══════════════════════════════════════════════════════════════════════════════
# Supervisor 创建函数
# ══════════════════════════════════════════════════════════════════════════════

def create_supervisor(
    model: str = "MiniMax-Text-01",
    weight_mode: str = None,
    fixed_weights: Dict[str, float] = None,
) -> Dict[str, Any]:
    """
    创建首席投资官 Agent

    Args:
        model: 模型名称
        weight_mode: 权重模式，"fixed" 或 "auto"，默认从环境变量 WEIGHT_MODE 读取
        fixed_weights: 固定权重字典，fixed 模式下使用

    Returns:
        包含 supervisor_node 函数的字典，用于 LangGraph 工作流

    使用示例：
        supervisor = create_supervisor(model="MiniMax-Text-01", weight_mode="fixed")
        workflow.add_node("supervisor", supervisor["supervisor_node"])
    """
    # 从环境变量读取权重模式（默认 "fixed"）
    if weight_mode is None:
        weight_mode = os.getenv("WEIGHT_MODE", "fixed")

    # 初始化合规组件
    disclaimer_filter = DisclaimerFilter()      # 过滤高风险词汇
    mandatory_disclaimer = MandatoryDisclaimer()  # 注入免责文本

    def supervisor_node(state: AgentState) -> AgentState:
        """
        Supervisor 节点函数（LangGraph 节点）

        Supervisor 的核心逻辑：
            1. 如果已有 final_report，说明已经生成过报告了，直接返回（不重复执行）
            2. 检查 6 个 Agent 结果是否齐全
            3. 如果还有缺失结果，设置 routing_target="parallel"，触发并行分发
            4. 如果结果都齐了，清除 routing_target，生成最终报告

        这个函数会被 LangGraph 多次调用：
            - 首次：设置 routing_target="parallel"
            - 中间：每个 Agent 完成后都会回到这里（但此时 routing_target 不是 "parallel"，不会重复分发）
            - 末次：所有结果齐了，生成报告

        Args:
            state: AgentState 当前状态

        Returns:
            AgentState 更新后的状态
        """
        # ── 1. 检查是否已有报告（避免重复执行）─────────────────────────────
        if getattr(state, "final_report", None):
            return state  # 已有报告，直接返回

        # ── 2. 检查 6 个 Agent 结果是否齐全 ──────────────────────────────
        required_results = [
            "quantitative_result",   # 量化分析师
            "chart_result",          # 图表分析师
            "intelligence_result",   # 情报官
            "risk_result",           # 风险评估师
            "fundamental_result",    # 基本面分析师
            "sentiment_result",      # 舆情监控师
        ]
        missing = [r for r in required_results if getattr(state, r, None) is None]

        print(f"  [Supervisor] missing={len(missing)}, routing={getattr(state, 'routing_target', None)}, final_report={'有' if getattr(state, 'final_report', None) else '无'}")

        # ── 3. 如果还有缺失结果，设置路由目标为 parallel ──────────────────
        if missing:
            if getattr(state, "routing_target", None) != "parallel":
                state.routing_target = "parallel"  # 设置路由目标，触发并行分发
            return state  # 返回（此时条件边会把任务分发给 6 个 Agent）

        # ── 4. 结果已齐，清除路由目标，生成报告 ────────────────────────────
        state.routing_target = None

        # ── 5. 获取 LLM 客户端 ──────────────────────────────────────────────
        client = get_minimax_client()

        # ── 6. 根据权重模式生成报告 ────────────────────────────────────────
        if weight_mode == "auto":
            # 自动权重模式：LLM 动态分配权重
            final_report = _build_auto_report(
                state, client, disclaimer_filter, mandatory_disclaimer
            )
        else:
            # 固定权重模式：使用预设权重
            weights = _get_agent_weights(weight_mode, fixed_weights)
            final_report = _build_fixed_report(
                state, weights, client, disclaimer_filter, mandatory_disclaimer
            )

        # ── 7. 设置最终报告 ────────────────────────────────────────────────
        state.final_report = final_report

        print(f"  [Supervisor] 报告生成完成，return state")

        return state

    # 返回节点函数（LangGraph add_node 需要字典格式）
    return {"supervisor_node": supervisor_node}