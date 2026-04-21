"""
风险评估师 Agent 模块

负责市场风险量化、估值风险分析、流动性评估和止损位计算。

分析流程：
    1. 获取 K线数据（AKShare）
    2. 计算风险指标（波动率、VaR、最大回撤）
    3. 估算止损位（波动率止损、支撑位止损、ATR止损）
    4. 调用 LLM 生成风险分析结论
    5. 写入 state.risk_result

Agent 结果：
    - score: 风险评分（0-100，评分越高越安全）
    - conclusion: 风险分析结论
    - key_findings: 风险发现
    - raw_data: 包含 stop_loss（止损位数据），Supervisor 会使用这个数据
"""

# ─── 标准库 ─────────────────────────────────────────────────────────────────
import time  # 计时

from typing import Any, Dict  # 类型注解

# ─── 第三方库 ─────────────────────────────────────────────────────────────────
import pandas as pd  # 数据处理

# ─── 项目内部导入 ──────────────────────────────────────────────────────────────
from src.graph.state import AgentResult, AgentState, DataQuality, calculate_confidence_from_quality
from src.llm import get_minimax_client  # MiniMax API 客户端
from src.tools import get_akshare_client  # AKShare 数据客户端


# ══════════════════════════════════════════════════════════════════════════════
# 系统提示词
# ══════════════════════════════════════════════════════════════════════════════

SYSTEM_PROMPT = """你是一位专业的风险评估师，负责量化风险和控制建议。

你的职责：
1. 市场风险量化（Beta、波动率、VaR 等）
2. 估值风险分析（PE/PB/PS 分位数、与行业平均对比）
3. 流动性风险评估（换手率、成交量、大宗交易）
4. 融资融券分析（杠杆比例、爆仓风险）
5. 止损位计算（基于波动率的动态止损建议）
6. 风险敞口和资金管理建议

输出要求：
- 评分：风险评分 0-100（评分越高风险越低，越安全）
- 分析内容：详细的风险分析说明
- 关键发现：3-5 个重要风险发现

【评分标准】（评分越高越安全，与其他维度相反）
- 80-100: 极低风险
- 60-79: 低风险
- 40-59: 中等风险
- 20-39: 高风险
- 0-19: 极高风险

【重要】你只输出分析内容，不提供任何买卖建议。"""


# ══════════════════════════════════════════════════════════════════════════════
# 辅助函数
# ══════════════════════════════════════════════════════════════════════════════

def _calculate_risk_metrics(df: pd.DataFrame) -> Dict[str, Any]:
    """
    计算风险指标

    从 K线数据计算以下风险指标：
    - 年化波动率（Volatility）：衡量价格波动程度
    - VaR（Value at Risk）：在给定的置信度下，的最大损失
    - 最大回撤（Max Drawdown）：从高点到低点的最大跌幅
    - 价格位置（Price Position）：当前价格在近 20 日区间的位置

    Args:
        df: K线 DataFrame，必须包含 close/high/low/volume 列

    Returns:
        风险指标字典
    """
    if df is None or df.empty or len(df) < 20:
        return {}

    close = df["close"]
    high = df["high"]
    low = df["low"]
    volume = df["volume"]

    metrics = {}

    # ── 1. 计算日收益率序列 ─────────────────────────────────────────────
    # 日收益率 = (今日收盘 - 昨日收盘) / 昨日收盘
    returns = close.pct_change().dropna()

    # ── 2. 年化波动率 ──────────────────────────────────────────────────
    # 波动率 = 日收益率标准差 * sqrt(252)
    # sqrt(252) 是一年交易日的平方根
    if len(returns) >= 20:
        volatility = returns.std() * (252 ** 0.5)  # 年化波动率
        metrics["volatility_annual"] = round(float(volatility), 4)   # 如 0.25 表示 25%
        metrics["volatility_daily"] = round(float(returns.std()), 4)  # 日波动率

        # ── VaR（Value at Risk）─────────────────────────────────────────
        # VaR(95%, 1日) = 收益率分布的 5% 分位数
        # 含义：有 95% 的把握，每日的损失不会超过这个值
        var_95 = float(returns.quantile(0.05))  # 5% 分位数（负数表示损失）
        metrics["var_95_1d"] = round(var_95, 4)
        metrics["var_95_1d_pct"] = round(var_95 * 100, 2)  # 转为百分比

    # ── 3. 最大回撤 ─────────────────────────────────────────────────────
    # 最大回撤 = 从历史高点到低点的最大跌幅
    if len(close) >= 20:
        rolling_max = close.expanding().max()  # 截至每日的最高价
        drawdown = (close - rolling_max) / rolling_max  # 回撤比例
        max_drawdown = float(drawdown.min())  # 最大回撤（负数）
        metrics["max_drawdown"] = round(max_drawdown * 100, 2)  # 转为百分比

    # ── 4. 价格位置 ──────────────────────────────────────────────────────
    # 当前价格在近 20 日区间的位置（0% = 最低点，100% = 最高点）
    if len(close) >= 20:
        high_20 = float(high.iloc[-20:].max())  # 近 20 日最高价
        low_20 = float(low.iloc[-20:].min())   # 近 20 日最低价
        current = float(close.iloc[-1])        # 当前收盘价
        price_position = (current - low_20) / (high_20 - low_20) if high_20 > low_20 else 0.5
        metrics["price_position_20d"] = round(price_position * 100, 1)

    # ── 5. 换手率（如果有数据）───────────────────────────────────────────
    if "turnover" in df.columns:
        metrics["avg_turnover_5d"] = round(float(df["turnover"].iloc[-5:].mean()), 2)

    return metrics


def _estimate_stop_loss(df: pd.DataFrame, volatility: float = None) -> Dict[str, Any]:
    """
    估算止损位

    提供三种止损位计算方法：
    1. 波动率止损：基于 2 倍年化波动率
    2. 支撑位止损：近 20 日最低点
    3. ATR 止损：基于平均真实范围（Average True Range）

    Args:
        df: K线 DataFrame
        volatility: 年化波动率（可选，如果不传则自动计算）

    Returns:
        止损位字典，包含：
        - current_price: 当前价格
        - volatility_stop_price: 波动率止损价
        - volatility_stop_pct: 波动率止损百分比
        - support_20d_price: 20 日支撑位
        - support_20d_pct: 距支撑位百分比
        - atr_stop_price: ATR 止损价
    """
    if df is None or df.empty:
        return {}

    # 获取当前价格
    current_price = float(df.iloc[-1]["close"])

    # ── 如果没有传入波动率，自动计算 ───────────────────────────────────
    if volatility is None:
        returns = df["close"].pct_change().dropna()
        if len(returns) < 20:
            return {}
        volatility = float(returns.std() * (252 ** 0.5))

    # ── 1. 波动率止损 ───────────────────────────────────────────────────
    # 2 倍波动率作为止损距离
    # 如果年化波动率是 25%，止损距离 = 50%
    stop_loss_pct = volatility * 2
    stop_loss_price = current_price * (1 - stop_loss_pct)

    # ── 2. 支撑位止损 ───────────────────────────────────────────────────
    # 近 20 日最低点作为止损价（技术分析支撑位）
    low_20 = float(df["low"].iloc[-20:].min())

    # ── 3. ATR 止损 ─────────────────────────────────────────────────────
    # ATR（Average True Range）是衡量波动性的指标
    # ATR = (High - Low) 的 14 日均值
    # 2 倍 ATR 作为止损距离
    high_low = df["high"].iloc[-14:] - df["low"].iloc[-14:]
    atr = float(high_low.mean())
    atr_stop = current_price - 2 * atr

    return {
        "current_price": current_price,                              # 当前价格
        "volatility_stop_pct": round(stop_loss_pct * 100, 2),        # 止损百分比（如 8.5 表示 8.5%）
        "volatility_stop_price": round(stop_loss_price, 2),           # 波动率止损价格
        "support_20d_price": round(low_20, 2),                        # 20 日支撑位
        "support_20d_pct": round((current_price - low_20) / current_price * 100, 2),  # 距支撑位 %
        "atr_stop_price": round(atr_stop, 2),                          # ATR 止损价格
    }


def _format_risk_data(
    df: pd.DataFrame,
    metrics: Dict[str, Any],
    stop_loss: Dict[str, Any],
    ts_code: str,
    stock_name: str,
) -> str:
    """
    构建发给 LLM 的风险分析数据文本

    Args:
        df: K线 DataFrame
        metrics: 风险指标字典
        stop_loss: 止损位字典
        ts_code: 股票代码
        stock_name: 股票名称

    Returns:
        格式化的风险数据文本
    """
    lines = []
    lines.append(f"=== {stock_name} ({ts_code}) 风险分析数据 ===\n")

    # ── 1. 最新行情 ────────────────────────────────────────────────────
    if df is not None and not df.empty:
        latest = df.iloc[-1]
        prev = df.iloc[-2] if len(df) > 1 else latest
        lines.append(f"【最新行情】")
        lines.append(f"最新价: {latest['close']:.2f} 元")
        lines.append(f"近20日最高: {df['high'].iloc[-20:].max():.2f} 元")
        lines.append(f"近20日最低: {df['low'].iloc[-20:].min():.2f} 元")
        lines.append("")

    # ── 2. 风险指标 ───────────────────────────────────────────────────
    if metrics:
        lines.append(f"【风险指标】")
        if "volatility_annual" in metrics:
            lines.append(f"年化波动率: {metrics['volatility_annual']*100:.2f}%")
        if "var_95_1d" in metrics:
            lines.append(f"VaR (95%, 1日): {metrics['var_95_1d_pct']:.2f}%")
        if "max_drawdown" in metrics:
            lines.append(f"最大回撤: {metrics['max_drawdown']:.2f}%")
        if "price_position_20d" in metrics:
            pos = metrics["price_position_20d"]
            lines.append(f"当前价格位置: 在近20日区间的 {pos:.1f}% 位置")
        lines.append("")

    # ── 3. 止损位参考 ──────────────────────────────────────────────────
    if stop_loss:
        lines.append(f"【止损位参考】")
        lines.append(f"当前价格: {stop_loss['current_price']:.2f} 元")
        if "volatility_stop_price" in stop_loss:
            lines.append(f"波动率止损位: {stop_loss['volatility_stop_price']:.2f} 元（距 {stop_loss['volatility_stop_pct']:.1f}%）")
        if "support_20d_price" in stop_loss:
            lines.append(f"20日支撑位: {stop_loss['support_20d_price']:.2f} 元（距 {stop_loss.get('support_20d_pct', 0):.1f}%）")
        if "atr_stop_price" in stop_loss:
            lines.append(f"ATR止损位: {stop_loss['atr_stop_price']:.2f} 元")
        lines.append("")

    return "\n".join(lines)


# ══════════════════════════════════════════════════════════════════════════════
# Agent 创建函数
# ══════════════════════════════════════════════════════════════════════════════

def create_risk_analyst(model: str = "MiniMax-Text-01") -> Dict[str, Any]:
    """
    创建风险评估师 Agent

    Args:
        model: 模型名称

    Returns:
        包含 analyze_risk 函数的字典
    """

    def analyze_risk(state: AgentState) -> AgentState:
        """
        执行风险评估

        LangGraph 节点函数：
        - 输入：AgentState（包含 query）
        - 输出：AgentState（包含 risk_result）

        注意：risk_result.raw_data["stop_loss"] 会被 Supervisor 提取用于报告
        """
        start_time = time.time()
        print(f"  ⏳ [风险评估师] 开始分析...")

        query = state.query
        if query is None:
            return state

        ts_code = query.ts_code
        stock_name = query.stock_name or ts_code
        start_date = query.start_date
        end_date = query.end_date

        # ── 1. 获取 K线数据 ─────────────────────────────────────────────
        akshare = get_akshare_client()
        kline_df, quality_score, quality_details = akshare.get_historical_kline_with_quality(
            ts_code, start_date, end_date
        )

        # ── 2. 计算风险指标 ───────────────────────────────────────────────
        risk_metrics = _calculate_risk_metrics(kline_df)

        # ── 3. 估算止损位 ────────────────────────────────────────────────
        volatility = risk_metrics.get("volatility_annual")
        stop_loss = _estimate_stop_loss(kline_df, volatility)

        # ── 4. 构建分析数据 ─────────────────────────────────────────────
        analysis_data = _format_risk_data(
            kline_df, risk_metrics, stop_loss, ts_code, stock_name
        )

        # ── 5. 构建 prompt ───────────────────────────────────────────────
        user_prompt = f"""{analysis_data}

请根据以上风险数据，进行风险量化分析。

输出格式（严格按此格式）：
评分: [0-100的数值，评分越高越安全]
分析内容: [详细的风险分析说明，3-5句话，重点关注波动率和回撤风险]
关键发现: [3-5个关键发现，每行一个，格式如 "- 发现1"]
"""

        # ── 6. 调用 LLM ─────────────────────────────────────────────────
        client = get_minimax_client()
        messages = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ]
        response = client.chat(messages)
        content = response["choices"][0]["message"]["content"]

        # ── 7. 解析结果 ─────────────────────────────────────────────────
        score = None
        conclusion = ""
        key_findings = []

        for line in content.split("\n"):
            line = line.strip()
            if line.startswith("评分:"):
                try:
                    score = float(line.split("评分:")[1].strip())
                except ValueError:
                    pass
            elif line.startswith("分析内容:"):
                conclusion = line.split("分析内容:")[1].strip()
            elif line.startswith("- "):
                key_findings.append(line)

        # ── 8. 计算置信度 ────────────────────────────────────────────────
        data_quality = DataQuality(
            quality_score=quality_score,
            completeness=1.0 - quality_details.get("null_ratio", 0),
            timeliness=1.0 if quality_details.get("days_old", 0) <= 3 else 0.8,
            consistency=1.0 - quality_details.get("invalid_close_ratio", 0),
            details=quality_details,
        )
        confidence = calculate_confidence_from_quality(data_quality)

        # ── 9. 构建 AgentResult ─────────────────────────────────────────
        result = AgentResult(
            agent_name="risk",             # Agent 名称
            score=score,                   # 风险评分（越高越安全）
            confidence=confidence,         # 置信度
            data_quality=data_quality,    # 数据质量
            conclusion=conclusion or content[:200],
            recommendation="风险评估已完成，请参考评分和关键发现",
            key_findings=key_findings[:5],
            raw_data={
                "risk_metrics": risk_metrics,   # 风险指标
                "stop_loss": stop_loss,          # 止损位（Supervisor 会用这个）
                "quality_score": quality_score,
            },
        )

        # ── 10. 更新状态 ────────────────────────────────────────────────
        elapsed = time.time() - start_time
        print(f"  ✅ [风险评估师] 完成 - 耗时: {elapsed:.1f}s")
        if result.conclusion:
            print(f"     结论: {result.conclusion}")

        state.risk_result = result
        existing_tasks = getattr(state, "completed_tasks", [])
        state.completed_tasks = list(existing_tasks) + ["risk"]

        return state

    return {"analyze_risk": analyze_risk}