"""
图表分析师 Agent 模块

负责 K线形态识别、趋势线分析、支撑阻力位识别和成交量分析。

分析流程：
    1. 获取 K线数据（AKShare）
    2. 识别 K线形态（锤子线、吞没、十字星等）
    3. 分析支撑阻力位（20日高低点）
    4. 分析成交量（量比、量价背离）
    5. 调用 LLM 生成分析结论
    6. 写入 state.chart_result

Agent 结果：
    - score: 形态评分（0-100）
    - conclusion: 形态分析结论
    - key_findings: 支撑位、阻力位、形态信号等
    - raw_data: 形态识别原始数据（patterns, support_resistance, volume_analysis）
"""

# ─── 标准库 ─────────────────────────────────────────────────────────────────
import time  # 计时（统计分析耗时）

from typing import Any, Dict  # 类型注解

# ─── 第三方库 ─────────────────────────────────────────────────────────────────
import pandas as pd  # 数据处理（DataFrame）

# ─── 项目内部导入 ──────────────────────────────────────────────────────────────
from src.graph.state import AgentResult, AgentState, DataQuality, calculate_confidence_from_quality
from src.llm import get_minimax_client  # MiniMax API 客户端
from src.tools import get_akshare_client  # AKShare 数据客户端


# ══════════════════════════════════════════════════════════════════════════════
# 系统提示词
# ══════════════════════════════════════════════════════════════════════════════

SYSTEM_PROMPT = """你是一位技术图表分析专家，负责K线形态识别和图表模式分析。

你的职责：
1. K线形态识别（锤子线、吞没、十字星、早晨之星、黄昏星等反转形态）
2. 趋势线绘制与分析（上升趋势线、下降趋势线、通道线）
3. 支撑位和阻力位识别（关键价格位、成交密集区）
4. 成交量分析（放量、缩量、量价背离、量增价涨）
5. 常见图表模式识别（头肩顶/底、双顶/底、三角形、旗形、楔形等）

输出要求：
- 评分：图表形态评分 0-100（仅描述形态好坏，不作为投资建议）
- 分析内容：详细的图表分析说明
- 关键发现：3-5 个重要形态发现

【评分标准】（仅描述图表形态，不构成投资建议）
- 80-100: 图表形态极优，多重形态共振
- 60-79: 图表形态较优，趋势明确
- 40-59: 图表形态中性，无明显方向
- 20-39: 图表形态较差，趋势向下
- 0-19: 图表形态极差，反转信号明确

【重要】你只输出分析内容，不提供任何买卖建议。"""


# ══════════════════════════════════════════════════════════════════════════════
# 辅助函数
# ══════════════════════════════════════════════════════════════════════════════

def _identify_candlestick_patterns(df: pd.DataFrame) -> Dict[str, Any]:
    """
    识别 K线形态

    检测常见的反转形态：
    - 锤子线（Hammer）：下影线 >= 实体的 2 倍，预示反弹
    - 上涨吞没（Bullish Engulfing）：阳线包裹前一根阴线
    - 下跌吞没（Bearish Engulfing）：阴线包裹前一根阳线
    - 十字星（Doji）：开盘价和收盘价几乎相等

    Args:
        df: K线 DataFrame，必须包含 open/high/low/close 列

    Returns:
        形态分析字典，包含 patterns 列表
    """
    # 数据有效性检查
    if df is None or df.empty or len(df) < 5:
        return {}

    patterns = []  # 存储检测到的形态

    # 获取最近 5 根 K线进行分析
    recent = df.tail(5).copy()

    for i, row in recent.iterrows():
        # 提取价格数据
        open_price = row["open"]
        close_price = row["close"]
        high_price = row["high"]
        low_price = row["low"]

        # 计算 K线各部分
        body_size = abs(close_price - open_price)  # 实体大小
        upper_shadow = high_price - max(open_price, close_price)  # 上影线
        lower_shadow = min(open_price, close_price) - low_price   # 下影线
        total_range = high_price - low_price                        # 总范围

        if total_range == 0:
            continue  # 跳过无效数据

        # ── 锤子线（Hammer）────────────────────────────────────────────
        # 特征：下影线至少是实体的 2 倍，上影线短
        # 位置：下跌趋势中出现，预示反弹
        if lower_shadow >= 2 * body_size and body_size > 0:
            patterns.append({
                "type": "锤子线",
                "date": str(row.get("trade_date", row.get("date", ""))),
                "direction": "看涨"
            })

        # ── 吞没形态（Engulfing）────────────────────────────────────────
        # 需要前一根 K线的数据才能判断
        idx_list = recent.index.tolist()
        if i in idx_list and idx_list.index(i) > 0:
            prev_idx = idx_list[idx_list.index(i) - 1]  # 前一根 K线的索引
            prev_row = df.loc[prev_idx]
            # 安全检查：确保 prev_row 是有效的 Series
            if not isinstance(prev_row, pd.Series):
                continue

            prev_open = prev_row["open"]
            prev_close = prev_row["close"]

            # 上涨吞没（Bullish Engulfing）
            # 条件：今日阳线（收盘 > 开盘），前一日阴线（收盘 < 开盘）
            #       且今日收盘 > 昨日开盘，今日开盘 < 昨日收盘
            if close_price > open_price and prev_close < prev_open:
                if close_price > prev_open and open_price < prev_close:
                    patterns.append({
                        "type": "上涨吞没",
                        "date": str(row.get("trade_date", "")),
                        "direction": "看涨"
                    })

            # 下跌吞没（Bearish Engulfing）
            # 条件：今日阴线（收盘 < 开盘），前一日阳线（收盘 > 开盘）
            #       且今日开盘 > 昨日收盘，今日收盘 < 昨日开盘
            if close_price < open_price and prev_close > prev_open:
                if open_price > prev_close and close_price < prev_open:
                    patterns.append({
                        "type": "下跌吞没",
                        "date": str(row.get("trade_date", "")),
                        "direction": "看跌"
                    })

        # ── 十字星（Doji）───────────────────────────────────────────────
        # 特征：实体很小（< 总范围的 10%），上下影线差不多长
        if body_size < total_range * 0.1 and (upper_shadow > body_size and lower_shadow > body_size):
            patterns.append({
                "type": "十字星",
                "date": str(row.get("trade_date", "")),
                "direction": "中性"
            })

    # 返回最多 10 个形态（避免 prompt 过长）
    return {"patterns": patterns[:10]}


def _find_support_resistance(df: pd.DataFrame, window: int = 20) -> Dict[str, Any]:
    """
    识别支撑位和阻力位

    通过近 N 日的高低点计算支撑阻力：
    - 阻力位：近 N 日最高价（上涨天花板）
    - 支撑位：近 N 日最低价（下跌底线）
    - 中位价：(最高 + 最低) / 2

    Args:
        df: K线 DataFrame
        window: 窗口大小，默认 20 日

    Returns:
        支撑阻力位字典
    """
    if df is None or df.empty or len(df) < window:
        return {}

    # 取最近 window 日的数据
    recent = df.tail(window)

    # 计算 20 日最高价和最低价
    high_20d = float(recent["high"].max())   # 近 20 日最高价（阻力位）
    low_20d = float(recent["low"].min())     # 近 20 日最低价（支撑位）
    current_price = float(df.iloc[-1]["close"])  # 最新收盘价

    # 计算成交密集区（简化处理：取中间价作为参考）
    price_range = high_20d - low_20d
    if price_range == 0:
        return {}

    mid_price = (high_20d + low_20d) / 2  # 区间中位价

    # 计算当前价格在区间中的位置（百分比）
    # 接近 0% = 接近支撑位，接近 100% = 接近阻力位
    position_ratio = (current_price - low_20d) / price_range if price_range > 0 else 0.5

    return {
        "high_20d": high_20d,                        # 20 日最高价
        "low_20d": low_20d,                          # 20 日最低价
        "mid_price": mid_price,                      # 区间中位价
        "current_price": current_price,              # 当前价格
        "position_ratio": round(position_ratio * 100, 1),  # 所处位置百分比
        "distance_to_high": round((high_20d - current_price) / current_price * 100, 2),  # 距阻力位 %
        "distance_to_low": round((current_price - low_20d) / current_price * 100, 2),   # 距支撑位 %
    }


def _analyze_volume(df: pd.DataFrame) -> Dict[str, Any]:
    """
    分析成交量

    通过对比今日成交量与近 10 日平均成交量判断放量/缩量
    同时检测量价背离（价格与成交量走势不一致）

    Args:
        df: K线 DataFrame，必须包含 volume 列

    Returns:
        成交量分析字典
    """
    if df is None or df.empty or len(df) < 5:
        return {}

    # 取最近 10 日数据
    recent = df.tail(10)

    # 计算平均成交量
    avg_volume = float(recent["volume"].mean())
    current_volume = float(recent.iloc[-1]["volume"])

    # 量比 = 今日成交量 / 10 日平均成交量
    volume_ratio = current_volume / avg_volume if avg_volume > 0 else 1.0

    # 计算价格变化
    if len(recent) > 1:
        price_change = float(recent.iloc[-1]["close"] - recent.iloc[-2]["close"])
        prev_close = float(recent.iloc[-2]["close"])
        price_change_pct = price_change / prev_close * 100 if prev_close != 0 else 0
    else:
        price_change_pct = 0

    # 判断价格趋势和成交量趋势
    price_trend = "up" if recent.iloc[-1]["close"] > recent.iloc[0]["close"] else "down"
    volume_trend = "up" if current_volume > avg_volume else "down"

    # ── 量价背离检测 ─────────────────────────────────────────────────────
    # 顶背离：价格上涨 + 成交量萎缩 → 可能见顶
    # 底背离：价格下跌 + 成交量放大 → 可能见底
    divergence = None
    if price_trend == "up" and volume_trend == "down":
        divergence = "顶背离（价升量跌）"
    elif price_trend == "down" and volume_trend == "up":
        divergence = "底背离（价跌量升）"

    return {
        "avg_volume_10d": round(avg_volume / 10000, 2),   # 万股（转换单位）
        "current_volume": round(current_volume / 10000, 2),
        "volume_ratio": round(volume_ratio, 2),            # 量比
        "price_change_pct": round(price_change_pct, 2),    # 价格变化%
        "divergence": divergence,                          # 量价背离类型
    }


def _format_chart_data(
    df: pd.DataFrame,
    patterns: Dict[str, Any],
    support_resistance: Dict[str, Any],
    volume_analysis: Dict[str, Any],
    ts_code: str,
    stock_name: str,
) -> str:
    """
    构建发给 LLM 的图表分析数据文本

    将原始数据格式化为易读的文本。

    Args:
        df: K线 DataFrame
        patterns: 形态识别结果
        support_resistance: 支撑阻力位
        volume_analysis: 成交量分析
        ts_code: 股票代码
        stock_name: 股票名称

    Returns:
        格式化的图表数据文本
    """
    lines = []
    lines.append(f"=== {stock_name} ({ts_code}) 图表分析数据 ===\n")

    # ── 1. 最近 5 日 K线 ────────────────────────────────────────────────
    if df is not None and not df.empty:
        lines.append("【最近5日K线】")
        for _, row in df.tail(5).iterrows():
            date = row.get("trade_date", row.get("date", ""))
            o = row["open"]
            h = row["high"]
            l = row["low"]
            c = row["close"]
            v = row["volume"] / 10000  # 转换为万股
            lines.append(f"{date}: 开{o:.2f} 高{h:.2f} 低{l:.2f} 收{c:.2f} 量{v:.1f}万")
        lines.append("")

    # ── 2. K线形态信号 ──────────────────────────────────────────────────
    if patterns and patterns.get("patterns"):
        lines.append("【K线形态信号】")
        for p in patterns["patterns"]:
            lines.append(f"- {p['type']} ({p['date']}) - {p['direction']}")
        lines.append("")
    else:
        lines.append("【K线形态信号】无明显形态信号\n")

    # ── 3. 支撑位与阻力位 ───────────────────────────────────────────────
    if support_resistance:
        lines.append("【支撑位与阻力位】")
        lines.append(f"近20日最高: {support_resistance['high_20d']:.2f} 元（距现价 {support_resistance['distance_to_high']:.1f}%）")
        lines.append(f"近20日最低: {support_resistance['low_20d']:.2f} 元（距现价 {support_resistance['distance_to_low']:.1f}%）")
        lines.append(f"当前价格位置: 在区间的 {support_resistance['position_ratio']:.1f}% 位置")
        lines.append("")

    # ── 4. 成交量分析 ───────────────────────────────────────────────────
    if volume_analysis:
        lines.append("【成交量分析】")
        lines.append(f"近10日均量: {volume_analysis['avg_volume_10d']:.1f} 万股")
        lines.append(f"今日成交量: {volume_analysis['current_volume']:.1f} 万股")
        lines.append(f"量比: {volume_analysis['volume_ratio']:.2f}x")
        if volume_analysis.get("divergence"):
            lines.append(f"量价背离: {volume_analysis['divergence']}")
        lines.append("")

    return "\n".join(lines)


# ══════════════════════════════════════════════════════════════════════════════
# Agent 创建函数
# ══════════════════════════════════════════════════════════════════════════════

def create_chart_analyst(model: str = "MiniMax-Text-01") -> Dict[str, Any]:
    """
    创建图表分析师 Agent

    Args:
        model: 模型名称

    Returns:
        包含 analyze 函数的字典，用于 LangGraph add_node
    """

    def analyze(state: AgentState) -> AgentState:
        """
        执行图表分析

        LangGraph 节点函数：
        - 输入：AgentState（包含 query）
        - 输出：AgentState（包含 chart_result）
        """
        start_time = time.time()  # 记录开始时间
        print(f"  ⏳ [图表分析师] 开始分析...")

        query = state.query
        if query is None:
            return state  # 无查询，返回

        ts_code = query.ts_code          # 股票代码
        stock_name = query.stock_name or ts_code  # 股票名称
        start_date = query.start_date    # 开始日期
        end_date = query.end_date        # 结束日期

        # ── 1. 获取 K线数据（含质量评估）────────────────────────────────
        akshare = get_akshare_client()
        kline_df, quality_score, quality_details = akshare.get_historical_kline_with_quality(
            ts_code, start_date, end_date
        )

        # ── 2. K线形态识别 ───────────────────────────────────────────────
        patterns = _identify_candlestick_patterns(kline_df)

        # ── 3. 支撑阻力位 ────────────────────────────────────────────────
        support_resistance = _find_support_resistance(kline_df)

        # ── 4. 成交量分析 ────────────────────────────────────────────────
        volume_analysis = _analyze_volume(kline_df)

        # ── 5. 构建分析数据 ─────────────────────────────────────────────
        analysis_data = _format_chart_data(
            kline_df, patterns, support_resistance,
            volume_analysis, ts_code, stock_name
        )

        # ── 6. 构建 prompt ───────────────────────────────────────────────
        user_prompt = f"""{analysis_data}

请根据以上图表数据，进行技术形态分析。

输出格式（严格按此格式）：
评分: [0-100的数值]
分析内容: [详细的图表分析说明，3-5句话，重点关注形态信号和量价关系]
关键发现: [3-5个关键发现，每行一个，格式如 "- 发现1"]
"""

        # ── 7. 调用 LLM ───────────────────────────────────────────────────
        client = get_minimax_client()
        messages = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ]
        response = client.chat(messages)
        content = response["choices"][0]["message"]["content"]

        # ── 8. 解析 LLM 输出 ──────────────────────────────────────────────
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

        # ── 9. 计算置信度 ─────────────────────────────────────────────────
        data_quality = DataQuality(
            quality_score=quality_score,
            completeness=1.0 - quality_details.get("null_ratio", 0),
            timeliness=1.0 if quality_details.get("days_old", 0) <= 3 else 0.8,
            consistency=1.0 - quality_details.get("invalid_close_ratio", 0),
            details=quality_details,
        )
        confidence = calculate_confidence_from_quality(data_quality)

        # ── 10. 构建 AgentResult ──────────────────────────────────────────
        result = AgentResult(
            agent_name="chart",           # Agent 名称（路由键）
            score=score,                  # 形态评分
            confidence=confidence,        # 置信度
            data_quality=data_quality,   # 数据质量指标
            conclusion=conclusion or content[:200],  # 结论（兜底用内容前 200 字）
            recommendation="图表形态分析已完成，请参考评分和关键发现",  # 中性建议
            key_findings=key_findings[:5],  # 最多 5 个发现
            raw_data={
                "patterns_found": len(patterns.get("patterns", [])),  # 形态数量
                "support_resistance": support_resistance,  # 支撑阻力位
                "volume_analysis": volume_analysis,        # 成交量分析
                "quality_score": quality_score,            # 质量分数
            },
        )

        # ── 11. 更新状态 ──────────────────────────────────────────────────
        elapsed = time.time() - start_time
        print(f"  ✅ [图表分析师] 完成 - 耗时: {elapsed:.1f}s")
        if result.conclusion:
            print(f"     结论: {result.conclusion}")

        # 写入 state（供 Supervisor 汇总）
        state.chart_result = result

        # 追加到已完成任务列表
        existing_tasks = getattr(state, "completed_tasks", [])
        state.completed_tasks = list(existing_tasks) + ["chart"]

        return state

    return {"analyze": analyze}