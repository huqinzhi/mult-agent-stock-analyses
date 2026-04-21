"""
量化分析师 Agent 模块

职责：技术指标计算、资金流向分析、趋势判断

分析流程：
    1. 获取 K线数据（AKShare，含质量评估）
    2. 获取资金流向数据
    3. 获取北向资金数据
    4. 计算技术指标（MA、RSI、MACD、布林带）
    5. 调用 LLM 生成分析结论
    6. 写入 state.quantitative_result

Agent 结果：
    - score: 技术面评分（0-100）
    - conclusion: 技术分析结论
    - key_findings: 3-5 个关键发现（如金叉、突破阻力位等）
    - raw_data: 技术指标原始数据
"""

# ─── 标准库 ─────────────────────────────────────────────────────────────────
import time  # 计时（统计分析耗时）

from typing import Any, Dict, List  # 类型注解

# ─── 第三方库 ─────────────────────────────────────────────────────────────────
import pandas as pd  # 数据处理（DataFrame）

# ─── 项目内部导入 ──────────────────────────────────────────────────────────────
# 从 state.py 导入数据结构
from src.graph.state import AgentResult, AgentState, DataQuality, calculate_confidence_from_quality

# 从 llm 模块导入 MiniMax 客户端
from src.llm import get_minimax_client

# 从 tools 模块导入 AKShare 客户端
from src.tools import get_akshare_client


# ══════════════════════════════════════════════════════════════════════════════
# 系统提示词
# ══════════════════════════════════════════════════════════════════════════════

# 量化分析师的系统提示词
# 定义角色：技术分析专家，负责技术指标计算和市场数据分析
SYSTEM_PROMPT = """你是一位量化分析专家，负责技术指标计算和市场数据分析。

你的职责：
1. 计算技术指标（MA、MACD、RSI、布林带等）
2. 分析资金流向（主力净流入、超大单、大单、中单、小单）
3. 趋势判断（上升趋势、下降趋势、横盘震荡）
4. 异常检测（成交量异常、价格异常）
5. 北向资金分析（如有数据）

输出要求：
- 评分：技术面评分 0-100（仅描述技术面强弱，不作为投资建议）
- 分析内容：详细的技术分析说明
- 关键发现：3-5 个重要技术发现

【评分标准】（仅描述技术面，不构成投资建议）
- 80-100: 技术面极强
- 60-79: 技术面较强
- 40-59: 技术面中性
- 20-39: 技术面较弱
- 0-19: 技术面极弱

【重要】你只输出分析内容，不提供任何买卖建议。"""


# ══════════════════════════════════════════════════════════════════════════════
# 辅助函数
# ══════════════════════════════════════════════════════════════════════════════

def _calculate_technical_indicators(df: pd.DataFrame) -> Dict[str, Any]:
    """
    计算技术指标

    从 K线 DataFrame 中计算常用技术指标：
    - MA（移动平均线）：MA5/MA10/MA20/MA60
    - RSI（相对强弱指数）：14日
    - 波动率（年化）
    - 价格变化率
    - 成交量比率
    - 20日高低点

    Args:
        df: K线 DataFrame，必须包含 open/high/low/close/volume 列

    Returns:
        技术指标字典，如 {"ma5": 10.5, "rsi": 65.2, "volatility": 0.25, ...}
    """
    # 数据有效性检查：DataFrame 不能为空，且至少需要 5 条数据
    if df is None or df.empty or len(df) < 5:
        return {}

    # 提取各列数据（使用 iloc 避免 SettingWithCopyWarning）
    close = df["close"]   # 收盘价序列
    high = df["high"]     # 最高价序列
    low = df["low"]       # 最低价序列
    volume = df["volume"] # 成交量序列

    indicators = {}  # 存储技术指标

    # ── 1. 移动平均线（MA）────────────────────────────────────────────────
    # MA 是过去 N 天收盘价的平均值
    if len(close) >= 5:
        indicators["ma5"] = float(close.iloc[-5:].mean())   # 5 日均线
    if len(close) >= 10:
        indicators["ma10"] = float(close.iloc[-10:].mean())  # 10 日均线
    if len(close) >= 20:
        indicators["ma20"] = float(close.iloc[-20:].mean())  # 20 日均线
    if len(close) >= 60:
        indicators["ma60"] = float(close.iloc[-60:].mean())  # 60 日均线

    # ── 2. 价格与均线的位置关系 ───────────────────────────────────────────
    # 判断当前价格在均线上方还是下方（用于判断趋势）
    if "ma20" in indicators:
        indicators["price_vs_ma20"] = "above" if close.iloc[-1] > indicators["ma20"] else "below"
    if "ma60" in indicators:
        indicators["price_vs_ma60"] = "above" if close.iloc[-1] > indicators["ma60"] else "below"

    # ── 3. RSI（相对强弱指标）──────────────────────────────────────────────
    # RSI = 100 - (100 / (1 + RS))
    # RS = 平均涨幅 / 平均跌幅
    # RSI > 70: 超买, RSI < 30: 超卖
    if len(close) >= 14:
        delta = close.diff()  # 价格变化（今日 - 昨日）
        gain = delta.where(delta > 0, 0.0)   # 上涨部分填 0
        loss = (-delta).where(delta < 0, 0.0)  # 下跌部分填 0（取绝对值）

        avg_gain = gain.iloc[-14:].mean()  # 近 14 日平均涨幅
        avg_loss = loss.iloc[-14:].mean()  # 近 14 日平均跌幅

        if avg_loss == 0:
            indicators["rsi"] = 100.0  # 如果没有下跌，RSI = 100（极强）
        else:
            rs = avg_gain / avg_loss     # 相对强度
            indicators["rsi"] = round(100 - (100 / (1 + rs)), 2)  # RSI 公式

    # ── 4. 波动率（年化）──────────────────────────────────────────────────
    # 波动率 = 日收益率标准差 * sqrt(252)
    # 252 是一年的交易日数
    if len(close) >= 20:
        returns = close.pct_change().dropna()  # 日收益率序列
        indicators["volatility"] = round(float(returns.std() * (252 ** 0.5)), 4)

    # ── 5. 价格变化率 ─────────────────────────────────────────────────────
    # 近 N 日价格变化百分比
    if len(close) >= 1:
        # 全程价格变化
        indicators["price_change_pct"] = round(
            float((close.iloc[-1] - close.iloc[0]) / close.iloc[0] * 100), 2
        )
    if len(close) >= 5:
        # 近 5 日价格变化
        indicators["price_change_5d"] = round(
            float((close.iloc[-1] - close.iloc[-5]) / close.iloc[-5] * 100), 2
        )

    # ── 6. 成交量分析 ────────────────────────────────────────────────────
    # 成交量比率 = 今日成交量 / 近 5 日平均成交量
    if len(volume) >= 5:
        avg_volume = volume.iloc[-5:].mean()
        indicators["volume_ratio"] = round(float(volume.iloc[-1] / avg_volume), 2) if avg_volume > 0 else 1.0
        indicators["volume_trend"] = "increasing" if volume.iloc[-1] > avg_volume else "decreasing"

    # ── 7. 近期高低点 ─────────────────────────────────────────────────────
    # 近 20 日最高价和最低价（用于判断支撑/阻力位）
    if len(close) >= 20:
        indicators["high_20d"] = float(high.iloc[-20:].max())
        indicators["low_20d"] = float(low.iloc[-20:].min())

    return indicators


def _format_analysis_data(
    kline_df: pd.DataFrame,
    money_flow_df: pd.DataFrame,
    north_flow_df: pd.DataFrame,
    indicators: Dict[str, Any],
    ts_code: str,
    stock_name: str,
) -> str:
    """
    构建发给 LLM 的分析数据文本

    将原始数据格式化为易读的文本，供 LLM 分析。

    Args:
        kline_df: K线 DataFrame
        money_flow_df: 资金流向 DataFrame
        north_flow_df: 北向资金 DataFrame
        indicators: 技术指标字典
        ts_code: 股票代码
        stock_name: 股票名称

    Returns:
        格式化的数据摘要字符串

    格式示例：
        === 平安银行 (000001.SZ) 技术分析数据 ===

        【最新行情】
        日期: 2024-04-19
        最新价: 12.50 元
        涨跌额: +0.30 元 (+2.46%)
        最高: 12.80 元
        最低: 12.20 元
        成交量: 2500.00 万股
        成交额: 31.25 亿元

        【技术指标】
        ma5: 12.30
        ma20: 12.10
        rsi: 65.20
        volatility: 0.25
        ...
    """
    lines = []
    lines.append(f"=== {stock_name} ({ts_code}) 技术分析数据 ===\n")

    # ── 1. 最新行情 ────────────────────────────────────────────────────────
    if kline_df is not None and not kline_df.empty:
        # 取最新一条数据（最后一行）
        latest = kline_df.iloc[-1]
        # 取前一天收盘价（用于计算涨跌）
        prev_close = kline_df.iloc[-2]["close"] if len(kline_df) > 1 else latest["close"]
        change_pct = (latest["close"] - prev_close) / prev_close * 100 if prev_close != 0 else 0

        lines.append(f"【最新行情】")
        # 尝试从 DataFrame 列名获取日期（兼容不同数据源格式）
        date_val = latest.get('trade_date', latest.get('date', 'N/A'))
        lines.append(f"日期: {date_val}")
        lines.append(f"最新价: {latest['close']:.2f} 元")
        lines.append(f"涨跌额: {latest['close'] - prev_close:.2f} 元 ({change_pct:+.2f}%)")
        lines.append(f"最高: {latest['high']:.2f} 元")
        lines.append(f"最低: {latest['low']:.2f} 元")
        lines.append(f"成交量: {latest['volume'] / 10000:.2f} 万股")
        # 成交额可能不在数据中
        amount = latest.get('amount', 0)
        if amount:
            lines.append(f"成交额: {amount / 100000000:.2f} 亿元")
        lines.append("")

    # ── 2. 技术指标 ────────────────────────────────────────────────────────
    if indicators:
        lines.append(f"【技术指标】")
        for key, value in indicators.items():
            if isinstance(value, float):
                lines.append(f"{key}: {value:.4f}")
            else:
                lines.append(f"{key}: {value}")
        lines.append("")

    # ── 3. 资金流向 ────────────────────────────────────────────────────────
    if money_flow_df is not None and not money_flow_df.empty:
        lines.append(f"【资金流向】（近5日）")
        for _, row in money_flow_df.head(5).iterrows():
            # 尝试获取日期和主力净流入
            date = row.get("trade_date", row.get("date", ""))
            net_flow = row.get('主力净流入-净额', 'N/A')
            lines.append(f"{date}: 主力净流入 {net_flow}")
        lines.append("")

    # ── 4. 北向资金 ────────────────────────────────────────────────────────
    if north_flow_df is not None and not north_flow_df.empty:
        lines.append(f"【北向资金】")
        for _, row in north_flow_df.head(3).iterrows():
            date = row.get('date', '')
            # 尝试兼容不同列名
            buy = row.get('buy', row.get('netbuy', 'N/A'))
            lines.append(f"{date}: 净买入 {buy}")
        lines.append("")

    return "\n".join(lines)


# ══════════════════════════════════════════════════════════════════════════════
# Agent 创建函数
# ══════════════════════════════════════════════════════════════════════════════

def create_quantitative_analyst(model: str = "MiniMax-Text-01") -> Dict[str, Any]:
    """
    创建量化分析师 Agent

    Args:
        model: 模型名称（传递给 LLM）

    Returns:
        包含 analyze 函数的字典，用于 LangGraph add_node

    使用示例：
        quantitative = create_quantitative_analyst("MiniMax-Text-01")
        workflow.add_node("quantitative", quantitative["analyze"])
    """

    def analyze(state: AgentState) -> AgentState:
        """
        执行量化分析

        这是 LangGraph 的节点函数：
        - 输入：AgentState（包含 query）
        - 输出：AgentState（包含 quantitative_result）

        分析流程：
            1. 获取 K线数据（含质量评估）
            2. 获取资金流向数据
            3. 获取北向资金数据
            4. 计算技术指标
            5. 调用 LLM 生成分析结论
            6. 构建 AgentResult 写入状态
        """
        start_time = time.time()  # 记录开始时间（用于计算耗时）
        print(f"  ⏳ [量化分析师] 开始分析...")

        # ── 1. 获取查询参数 ────────────────────────────────────────────────
        query = state.query
        if query is None:
            return state  # 无查询，返回（不应该发生）

        ts_code = query.ts_code          # 股票代码，如 "000001.SZ"
        stock_name = query.stock_name or ts_code  # 股票名称
        start_date = query.start_date     # 开始日期
        end_date = query.end_date         # 结束日期

        # ── 2. 获取 K线数据（含质量评估）────────────────────────────────────
        # AKShareClient.get_historical_kline_with_quality 返回：
        # - df: K线 DataFrame
        # - quality_score: 质量分数（0-1）
        # - quality_details: 详细质量信息
        akshare = get_akshare_client()
        kline_df, quality_score, quality_details = akshare.get_historical_kline_with_quality(
            ts_code, start_date, end_date
        )

        # ── 3. 获取资金流向数据（可选，失败不报错）──────────────────────────
        money_flow_df = None
        try:
            money_flow_df = akshare.get_money_flow(ts_code)
        except Exception:
            pass  # 资金流向数据可能不可用，继续分析

        # ── 4. 获取北向资金数据（可选）───────────────────────────────────────
        north_flow_df = None
        try:
            north_flow_df = akshare.get_north_money_flow(ts_code)
        except Exception:
            pass  # 北向资金可能不可用

        # ── 5. 计算技术指标 ─────────────────────────────────────────────────
        # 从 K线数据计算 MA、RSI、MACD 等指标
        indicators = _calculate_technical_indicators(kline_df)

        # ── 6. 构建分析数据 ─────────────────────────────────────────────────
        # 将原始数据格式化为易读的文本
        analysis_data = _format_analysis_data(
            kline_df, money_flow_df, north_flow_df,
            indicators, ts_code, stock_name
        )

        # ── 7. 构建 prompt ───────────────────────────────────────────────────
        # 告诉 LLM 需要输出的格式
        user_prompt = f"""{analysis_data}

请根据以上数据，进行量化分析。

输出格式（严格按此格式）：
评分: [0-100的数值]
分析内容: [详细的技术分析说明，3-5句话]
关键发现: [3-5个关键发现，每行一个，格式如 "- 发现1"]
"""

        # ── 8. 调用 LLM ────────────────────────────────────────────────────
        client = get_minimax_client()
        messages = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ]
        response = client.chat(messages)
        content = response["choices"][0]["message"]["content"]

        # ── 9. 解析 LLM 输出 ────────────────────────────────────────────────
        score = None
        conclusion = ""
        key_findings = []

        for line in content.split("\n"):
            line = line.strip()
            if line.startswith("评分:"):
                try:
                    score = float(line.split("评分:")[1].strip())
                except ValueError:
                    pass  # 解析失败，跳过
            elif line.startswith("分析内容:"):
                conclusion = line.split("分析内容:")[1].strip()
            elif line.startswith("- "):
                key_findings.append(line)  # 关键发现行

        # ── 10. 计算置信度 ──────────────────────────────────────────────────
        # 基于数据质量计算置信度
        # 数据质量越高，置信度越高
        data_quality = DataQuality(
            quality_score=quality_score,
            completeness=1.0 - quality_details.get("null_ratio", 0),  # 空值越少越完整
            timeliness=1.0 if quality_details.get("days_old", 0) <= 3 else 0.8,  # 3 天内数据时效性好
            consistency=1.0 - quality_details.get("invalid_close_ratio", 0),  # 逻辑一致性好
            details=quality_details,
        )
        confidence = calculate_confidence_from_quality(data_quality)

        # ── 11. 构建 AgentResult ────────────────────────────────────────────
        result = AgentResult(
            agent_name="quantitative",          # Agent 名称（路由键）
            score=score,                        # 技术面评分
            confidence=confidence,              # 置信度
            data_quality=data_quality,          # 数据质量指标
            conclusion=conclusion or content[:200],  # 结论（兜底用内容前 200 字）
            recommendation="技术面分析已完成，请参考评分和关键发现",  # 中性建议
            key_findings=key_findings[:5],      # 最多 5 个发现
            raw_data={
                "indicators": indicators,       # 技术指标原始数据
                "kline_rows": len(kline_df) if kline_df is not None else 0,  # K线条数
                "quality_score": quality_score,  # 质量分数
            },
        )

        # ── 12. 更新状态 ───────────────────────────────────────────────────
        elapsed = time.time() - start_time  # 计算耗时
        print(f"  ✅ [量化分析师] 完成 - 耗时: {elapsed:.1f}s")
        if result.conclusion:
            print(f"     结论: {result.conclusion}")

        # 写入 state（供 Supervisor 汇总）
        state.quantitative_result = result

        # 追加到已完成任务列表
        existing_tasks = getattr(state, "completed_tasks", [])
        state.completed_tasks = list(existing_tasks) + ["quantitative"]

        return state

    return {"analyze": analyze}