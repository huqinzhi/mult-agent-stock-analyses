"""
初筛 Agent（Prescreening Agent）

用于批量分析前的快速筛选，基于板块轮动/热点/动量信号
将大量候选股票缩减到约 top_n*2 只候选股票，降低 context 膨胀风险。

初筛维度权重：
- 板块资金流：30%（资金主动流入的板块优先）
- 板块热度：20%（市场关注度高的板块优先）
- 动量信号：30%（RSI/成交量等趋势指标）
- 热点匹配：20%（与当前市场热点主题匹配度）
"""

from typing import Any, Dict, List, Optional

from src.graph.state import AgentState, DataQuality
from src.llm import get_minimax_client
from src.tools import get_akshare_client


# ─────────────────────────────────────────────────────────────
# 系统提示词
# ─────────────────────────────────────────────────────────────

SYSTEM_PROMPT = """你是一位股票筛选专家，负责基于客观数据快速筛选候选股票。

你的职责：
1. 基于板块资金流数据筛选资金主动流入的板块
2. 基于板块热度排名筛选市场关注度高的板块
3. 基于动量指标（RSI、成交量比）筛选趋势向上的股票
4. 基于热点主题匹配度筛选与当前市场热点相关的股票

输出要求：
- 筛选理由：简洁说明每只股票被选中的原因（1-2句话）
- 不输出任何投资建议，仅客观描述筛选依据

【评分标准】
- 80-100：筛选理由充分，数据质量高
- 60-79：筛选理由较充分
- 40-59：筛选理由一般
- 0-39：筛选依据不足

【重要】你只输出筛选理由，不提供任何买卖建议。"""


# ─────────────────────────────────────────────────────────────
# 辅助函数
# ─────────────────────────────────────────────────────────────


def _calculate_rsi(prices: List[float], period: int = 14) -> Optional[float]:
    """计算 RSI 指标

    Args:
        prices: 价格序列
        period: 计算周期，默认14

    Returns:
        RSI 值（0-100），计算失败返回 None
    """
    if len(prices) < period + 1:
        return None

    try:
        deltas = [prices[i] - prices[i - 1] for i in range(1, len(prices))]
        gains = [d if d > 0 else 0 for d in deltas[-period:]]
        losses = [-d if d < 0 else 0 for d in deltas[-period:]]

        avg_gain = sum(gains) / period
        avg_loss = sum(losses) / period

        if avg_loss == 0:
            return 100.0
        rs = avg_gain / avg_loss
        rsi = 100 - (100 / (1 + rs))
        return rsi
    except Exception:
        return None


def _calculate_volume_ratio(volumes: List[float]) -> Optional[float]:
    """计算成交量比（今日成交量/5日平均成交量）

    Args:
        volumes: 成交量序列

    Returns:
        成交量比值，计算失败返回 None
    """
    if len(volumes) < 5:
        return None

    try:
        avg_5d = sum(volumes[-5:]) / 5
        today_vol = volumes[-1]
        if avg_5d == 0:
            return None
        return today_vol / avg_5d
    except Exception:
        return None


def _normalize_score(value: float, min_val: float, max_val: float) -> float:
    """将值归一化到 0-100

    Args:
        value: 原始值
        min_val: 最小值
        max_val: 最大值

    Returns:
        归一化后的分数
    """
    if max_val == min_val:
        return 50.0
    normalized = (value - min_val) / (max_val - min_val) * 100
    return max(0.0, min(100.0, normalized))


def _get_sector_score(sector_name: str, sector_flow_df, sector_hot_df) -> float:
    """获取板块得分

    Args:
        sector_name: 板块名称
        sector_flow_df: 板块资金流 DataFrame
        sector_hot_df: 板块热度 DataFrame

    Returns:
        板块得分（0-100）
    """
    score = 0.0
    count = 0

    # 资金流得分
    if sector_flow_df is not None and not sector_flow_df.empty:
        try:
            flow_cols = [c for c in sector_flow_df.columns if "主力净流入" in c or "净流入" in c]
            if flow_cols:
                flow_values = sector_flow_df[flow_cols[0]].astype(str).str.replace(",", "").str.extract(r'([-\d.]+)').astype(float)
                max_flow = flow_values.max().max() if flow_values.max().max() != 0 else 1
                min_flow = flow_values.min().min()
                # 找到匹配板块
                for idx, row in sector_flow_df.iterrows():
                    if sector_name in str(row.get("板块名称", "")):
                        flow_val = flow_values.iloc[idx, 0] if idx < len(flow_values) else 0
                        score += _normalize_score(flow_val, min_flow, max_flow) * 0.5
                        count += 1
                        break
        except Exception:
            pass

    # 热度得分
    if sector_hot_df is not None and not sector_hot_df.empty:
        try:
            hot_rank_col = None
            for col in ["排名", "rank", "热度", "关注度"]:
                if col in sector_hot_df.columns:
                    hot_rank_col = col
                    break
            if hot_rank_col:
                max_rank = len(sector_hot_df)
                for idx, row in sector_hot_df.iterrows():
                    if sector_name in str(row.get("板块名称", "")):
                        rank = row.get(hot_rank_col, max_rank)
                        score += _normalize_score(max_rank - rank, 0, max_rank) * 0.5
                        count += 1
                        break
        except Exception:
            pass

    if count == 0:
        return 50.0  # 默认中等得分
    return score


def _calculate_momentum_score(df, sector_name: str = "") -> float:
    """计算动量得分

    Args:
        df: K线 DataFrame
        sector_name: 所属板块名称（用于板块加成）

    Returns:
        动量得分（0-100）
    """
    if df is None or df.empty or len(df) < 20:
        return 50.0

    try:
        # 收盘价列表
        close_col = "close" if "close" in df.columns else "收盘"
        if close_col not in df.columns:
            return 50.0

        closes = df[close_col].tolist()
        volumes = df["volume"].tolist() if "volume" in df.columns else df.get("成交量", []).tolist()

        # RSI 计算
        rsi = _calculate_rsi(closes, 14) or 50.0
        rsi_score = rsi  # RSI 本身就是 0-100

        # 成交量比
        vol_ratio = _calculate_volume_ratio(volumes) or 1.0
        vol_score = min(100.0, vol_ratio * 50)  # 成交量比 2x = 100分

        # 动量得分
        momentum = rsi_score * 0.6 + vol_score * 0.4

        # 板块加成（如果板块资金流好，适当加分）
        sector_bonus = 0.0
        if sector_name:
            # 近5日涨跌趋势
            if len(closes) >= 5:
                trend = (closes[-1] - closes[-5]) / closes[-5] * 100
                if trend > 5:
                    sector_bonus = 10.0  # 强势板块加分
                elif trend < -5:
                    sector_bonus = -10.0  # 弱势板块减分

        return max(0.0, min(100.0, momentum + sector_bonus))
    except Exception:
        return 50.0


def _match_hot_topics(stock_name: str, sector_name: str, hot_topics: List[str]) -> float:
    """计算热点匹配得分

    Args:
        stock_name: 股票名称
        sector_name: 板块名称
        hot_topics: 当前热点主题列表

    Returns:
        热点匹配得分（0-100）
    """
    if not hot_topics:
        return 50.0

    score = 0.0
    count = 0

    stock_keywords = f"{stock_name} {sector_name}".lower()

    for topic in hot_topics:
        topic_lower = topic.lower()
        if topic_lower in stock_keywords:
            score += 100.0
            count += 1
        elif any(kw in stock_keywords for kw in topic_lower.split() if len(kw) > 2):
            score += 60.0
            count += 1

    if count == 0:
        return 50.0
    return score / count


def _calculate_prescreening_score(
    stock_info: Dict[str, Any],
    sector_flow_df,
    sector_hot_df,
    hot_topics: List[str],
) -> Dict[str, Any]:
    """计算单只股票的初筛综合得分

    Args:
        stock_info: 股票信息（包含 ts_code, name, sector 等）
        sector_flow_df: 板块资金流数据
        sector_hot_df: 板块热度数据
        hot_topics: 当前热点主题列表

    Returns:
        包含得分和详情的字典
    """
    ts_code = stock_info.get("ts_code", "")
    stock_name = stock_info.get("name", stock_info.get("stock_name", ""))
    sector_name = stock_info.get("sector", stock_info.get("industry", ""))

    # 1. 板块得分（资金流 30% + 热度 20%）
    sector_score = _get_sector_score(sector_name, sector_flow_df, sector_hot_df)
    sector_flow_weight = 0.3
    sector_hot_weight = 0.2
    sector_contribution = sector_score * (sector_flow_weight + sector_hot_weight) / 0.5

    # 2. 动量得分（30%）
    akshare = get_akshare_client()
    momentum_score = 50.0
    try:
        from datetime import datetime, timedelta
        end_date = datetime.now().strftime("%Y%m%d")
        start_date = (datetime.now() - timedelta(days=60)).strftime("%Y%m%d")
        df = akshare.get_historical_kline(ts_code, start_date, end_date)
        momentum_score = _calculate_momentum_score(df, sector_name)
    except Exception:
        pass

    # 3. 热点匹配得分（20%）
    sentiment_score = _match_hot_topics(stock_name, sector_name, hot_topics)

    # 综合得分
    # 板块资金流(30%) + 板块热度(20%) + 动量信号(30%) + 热点匹配(20%)
    total_score = (
        sector_contribution * 0.5 +  # 板块部分（资金流+热度）
        momentum_score * 0.3 +        # 动量部分
        sentiment_score * 0.2          # 热点部分
    )

    return {
        "ts_code": ts_code,
        "name": stock_name,
        "sector": sector_name,
        "total_score": total_score,
        "sector_score": sector_score,
        "momentum_score": momentum_score,
        "sentiment_score": sentiment_score,
    }


# ─────────────────────────────────────────────────────────────
# Prescreening Agent
# ─────────────────────────────────────────────────────────────


def create_prescreening_agent(
    model: str = "MiniMax-Text-01",
) -> Dict[str, Any]:
    """创建初筛 Agent

    Args:
        model: 模型名称，默认 MiniMax-Text-01

    Returns:
        包含 prescreening 节点的字典
    """

    def prescreening(state: AgentState) -> AgentState:
        """初筛节点

        根据板块轮动/热点/动量筛选候选股票

        Args:
            state: AgentState 状态对象

        Returns:
            更新后的 AgentState
        """
        stock_list = getattr(state, "stock_list", []) or []
        target_count = getattr(state, "prescreening_target", 10)

        if not stock_list:
            state.candidates = []
            state.prescreening_completed = True
            state.prescreening_reason = "候选股票列表为空，跳过初筛"
            return state

        # 1. 获取板块资金流/热度数据
        akshare = get_akshare_client()
        sector_flow_df = None
        sector_hot_df = None
        hot_topics = []

        try:
            sector_flow_df = akshare.get_sector_fund_flow()
        except Exception:
            pass

        try:
            # 板块热度（使用资金流排名作为代理）
            sector_hot_df = sector_flow_df
        except Exception:
            pass

        # 2. 获取热点主题（简单实现：取资金流前5板块作为热点）
        try:
            if sector_flow_df is not None and not sector_flow_df.empty:
                hot_topics = sector_flow_df.head(5)["板块名称"].tolist() if "板块名称" in sector_flow_df.columns else []
        except Exception:
            pass

        # 3. 并行计算每只股票的初筛得分
        candidates_with_scores = []

        for stock in stock_list:
            score_info = _calculate_prescreening_score(
                stock, sector_flow_df, sector_hot_df, hot_topics
            )
            candidates_with_scores.append(score_info)

        # 4. 按综合得分排序
        candidates_with_scores.sort(key=lambda x: x["total_score"], reverse=True)

        # 5. 取前 target_count 只
        top_candidates = candidates_with_scores[:target_count]

        # 6. 调用 LLM 生成筛选理由
        client = get_minimax_client()
        stock_summary = "\n".join([
            f"- {c['name']} ({c['ts_code']}): "
            f"板块得分={c['sector_score']:.1f}, "
            f"动量得分={c['momentum_score']:.1f}, "
            f"热点匹配={c['sentiment_score']:.1f}"
            for c in top_candidates
        ])

        prompt = f"""请为以下初筛结果生成简要理由（每只股票 1-2 句话）：

股票列表及得分：
{stock_summary}

目标候选数量：{target_count} 只

请按以下格式输出（仅输出内容，不需要其他说明）：
筛选结果：
"""

        try:
            messages = [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": prompt},
            ]
            response = client.chat(messages)
            llm_content = response["choices"][0]["message"]["content"]

            # 解析 LLM 返回的理由
            reasons = {}
            current_stock = None
            for line in llm_content.split("\n"):
                line = line.strip()
                if not line:
                    continue
                # 尝试匹配股票名称
                for c in top_candidates:
                    if c["name"] in line or c["ts_code"] in line:
                        current_stock = c["ts_code"]
                        reasons[current_stock] = line
                        break
                if current_stock and ":" in line and "筛选结果" not in line:
                    reasons[current_stock] = line

            # 更新候选股票的理由
            for c in top_candidates:
                if c["ts_code"] in reasons:
                    c["reason"] = reasons[c["ts_code"]]
                else:
                    c["reason"] = f"综合得分 {c['total_score']:.1f}，排名靠前"

        except Exception as e:
            # LLM 调用失败时使用默认理由
            for c in top_candidates:
                c["reason"] = f"综合得分 {c['total_score']:.1f}（板块{c['sector_score']:.1f}+动量{c['momentum_score']:.1f}+热点{c['sentiment_score']:.1f}）"

        # 7. 更新状态
        state.candidates = top_candidates
        state.prescreening_completed = True
        state.prescreening_reason = f"初筛完成，从 {len(stock_list)} 只股票中筛选出 {len(top_candidates)} 只候选"

        # 计算数据质量
        data_quality = DataQuality(
            quality_score=0.8 if sector_flow_df is not None else 0.5,
            completeness=0.8 if len(stock_list) > 5 else 0.6,
            timeliness=1.0,
            consistency=0.9,
            details={
                "input_count": len(stock_list),
                "output_count": len(top_candidates),
                "sector_flow_available": sector_flow_df is not None,
            },
        )
        state.prescreening_quality = data_quality

        return state

    return {"prescreening": prescreening}
