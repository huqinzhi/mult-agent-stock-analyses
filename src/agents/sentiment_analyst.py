"""
舆情监控师 Agent 模块

负责市场情绪分析、分析师评级追踪、公告信息提取和龙虎榜分析。

分析流程：
    1. 搜索分析师评级（search_analyst_rating）
    2. 搜索社交媒体情绪（search_social_sentiment）
    3. 搜索最新公告和新闻（search_news）
    4. 获取龙虎榜数据（AKShare）
    5. 调用 LLM 生成舆情分析结论
    6. 写入 state.sentiment_result

Agent 结果：
    - score: 舆情评分（0-100）
    - conclusion: 舆情分析结论
    - key_findings: 情绪发现
    - raw_data: 分析师评级数量、社交数据数量、龙虎榜信息
"""

# ─── 标准库 ─────────────────────────────────────────────────────────────────
import time  # 计时

from typing import Any, Dict  # 类型注解

# ─── 项目内部导入 ──────────────────────────────────────────────────────────────
from src.graph.state import AgentResult, AgentState, DataQuality, calculate_confidence_from_quality
from src.llm import get_minimax_client  # MiniMax API 客户端
from src.tools import (
    get_akshare_client,    # AKShare 数据客户端
    search_news,           # 新闻搜索
    search_analyst_rating, # 分析师评级搜索
    search_social_sentiment  # 社交媒体情绪搜索
)


# ══════════════════════════════════════════════════════════════════════════════
# 系统提示词
# ══════════════════════════════════════════════════════════════════════════════

SYSTEM_PROMPT = """你是一位舆情监控专家，负责市场情绪分析。

你的职责：
1. 社交媒体情绪分析（雪球、股吧、微博讨论的情绪倾向）
2. 分析师评级追踪（券商研报评级变化、目标价调整）
3. 公告信息提取（业绩预告、重大合同、股权变动等重要公告）
4. 机构持仓分析（机构持仓变化、十大股东变动）
5. 预期偏差检测（市场一致预期 vs 实际业绩偏差）
6. 龙虎榜分析（营业部操作、机构席位追踪）

输出要求：
- 评分：舆情评分 0-100（评分越高市场情绪越好）
- 分析内容：详细的市场情绪分析说明
- 关键发现：3-5 个重要舆情发现

【评分标准】（评分越高市场情绪越好）
- 80-100: 市场情绪极佳
- 60-79: 市场情绪较好
- 40-59: 市场情绪中性
- 20-39: 市场情绪较差
- 0-19: 市场情绪极差

【重要】你只输出分析内容，不提供任何买卖建议。"""


# ══════════════════════════════════════════════════════════════════════════════
# 辅助函数
# ══════════════════════════════════════════════════════════════════════════════

def _get_lhb_data(akshare, end_date: str, ts_code: str) -> Dict[str, Any]:
    """
    获取龙虎榜数据

    龙虎榜是每日涨幅/跌幅超过一定幅度的股票交易数据汇总，
    包含机构和营业部席位的买卖信息。

    Args:
        akshare: AKShare 客户端
        end_date: 结束日期（YYYYMMDD）
        ts_code: 股票代码

    Returns:
        龙虎榜汇总信息字典，包含：
        - count: 上榜次数
        - latest_date: 最近上榜日期
        - total_volume: 累计成交量
    """
    try:
        # ── 计算近 30 日的日期范围 ─────────────────────────────────────────
        from datetime import datetime, timedelta
        start_date = (datetime.strptime(end_date, "%Y%m%d") - timedelta(days=30)).strftime("%Y%m%d")

        # 获取龙虎榜明细数据
        lhb_df = akshare.get_lhb_detail(start_date, end_date)

        if lhb_df is not None and not lhb_df.empty:
            # 筛选当前股票（ts_code 如 "000001.SZ" → "000001"）
            code = ts_code.split(".")[0]
            stock_lhb = lhb_df[lhb_df.apply(
                lambda x: code in str(x.get("股票代码", "")), axis=1
            )]

            if not stock_lhb.empty:
                return {
                    "count": len(stock_lhb),  # 上榜次数
                    "latest_date": str(stock_lhb.iloc[-1].get("交易日期", "")),
                    "total_volume": float(stock_lhb["成交量"].sum()) if "成交量" in stock_lhb.columns else 0,
                }
    except Exception:
        pass  # 龙虎榜数据可能不可用
    return {}


def _format_sentiment_data(
    analyst_ratings: list,
    social_data: list,
    news_data: list,
    lhb_info: Dict[str, Any],
    ts_code: str,
    stock_name: str,
) -> str:
    """
    构建发给 LLM 的舆情分析数据文本

    将分析师评级、社交媒体情绪、公告新闻、龙虎榜格式化为易读的文本。

    Args:
        analyst_ratings: 分析师评级列表
        social_data: 社交媒体数据列表
        news_data: 新闻列表
        lhb_info: 龙虎榜信息
        ts_code: 股票代码
        stock_name: 股票名称

    Returns:
        格式化的舆情数据文本
    """
    lines = []
    lines.append(f"=== {stock_name} ({ts_code}) 舆情分析数据 ===\n")

    # ── 1. 分析师评级 ─────────────────────────────────────────────────────
    if analyst_ratings:
        lines.append(f"【分析师评级】（共 {len(analyst_ratings)} 条）")
        for rating in analyst_ratings[:5]:  # 最多显示 5 条
            title = rating.get("title", "")[:80]
            snippet = rating.get("snippet", "")[:100]
            lines.append(f"- {title}")
            if snippet:
                lines.append(f"  摘要: {snippet}...")
        lines.append("")
    else:
        lines.append("【分析师评级】未找到相关研报评级")
        lines.append("")

    # ── 2. 社交媒体情绪 ───────────────────────────────────────────────────
    if social_data:
        lines.append(f"【社交媒体讨论】（共 {len(social_data)} 条）")

        # 定义看多和看空关键词
        sentiment_keywords = ["看好", "买入", "推荐", "利多", "多头", "上涨"]
        bearish_keywords = ["看空", "卖出", "减持", "利空", "空头", "下跌", "风险"]

        # 统计看多/看空帖子数量
        bullish_count = 0
        bearish_count = 0

        for item in social_data[:10]:  # 只统计前 10 条
            text = item.get("title", "") + item.get("snippet", "")
            if any(kw in text for kw in sentiment_keywords):
                bullish_count += 1
            if any(kw in text for kw in bearish_keywords):
                bearish_count += 1

        total = min(len(social_data), 10)
        lines.append(f"看多讨论: {bullish_count}/{total}")
        lines.append(f"看空讨论: {bearish_count}/{total}")

        # 判断整体情绪倾向
        if bullish_count > bearish_count * 2:
            lines.append("整体情绪: 偏积极")
        elif bearish_count > bullish_count * 2:
            lines.append("整体情绪: 偏消极")
        else:
            lines.append("整体情绪: 中性")
        lines.append("")
    else:
        lines.append("【社交媒体讨论】未找到相关讨论")
        lines.append("")

    # ── 3. 最新公告/新闻 ──────────────────────────────────────────────────
    if news_data:
        lines.append(f"【最新公告/新闻】（共 {len(news_data)} 条）")
        for news in news_data[:5]:  # 最多显示 5 条
            title = news.get("title", "")[:80]
            date = news.get("date", "")
            lines.append(f"- {title}")
            if date:
                lines.append(f"  日期: {date}")
        lines.append("")

    # ── 4. 龙虎榜 ────────────────────────────────────────────────────────
    if lhb_info:
        lines.append(f"【龙虎榜】（近30日，共 {lhb_info.get('count', 0)} 次上榜）")
        lines.append(f"最近上榜日期: {lhb_info.get('latest_date', 'N/A')}")
        if lhb_info.get("total_volume"):
            lines.append(f"累计成交量: {lhb_info['total_volume']/10000:.2f} 万股")
        lines.append("")
    else:
        lines.append("【龙虎榜】近30日无上榜记录")
        lines.append("")

    return "\n".join(lines)


# ══════════════════════════════════════════════════════════════════════════════
# Agent 创建函数
# ══════════════════════════════════════════════════════════════════════════════

def create_sentiment_analyst(model: str = "MiniMax-Text-01") -> Dict[str, Any]:
    """
    创建舆情监控师 Agent

    Args:
        model: 模型名称

    Returns:
        包含 analyze_sentiment 函数的字典
    """

    def analyze_sentiment(state: AgentState) -> AgentState:
        """
        执行舆情分析

        LangGraph 节点函数：
        - 输入：AgentState（包含 query）
        - 输出：AgentState（包含 sentiment_result）
        """
        start_time = time.time()
        print(f"  ⏳ [舆情监控师] 开始分析...")

        query = state.query
        if query is None:
            return state

        ts_code = query.ts_code           # 股票代码
        stock_name = query.stock_name or ts_code  # 股票名称
        end_date = query.end_date         # 结束日期（用于龙虎榜查询）

        # ── 1. 搜索分析师评级 ───────────────────────────────────────────────
        analyst_ratings = []
        try:
            # 通过 DuckDuckGo 搜索券商研报和分析师评级
            analyst_ratings = search_analyst_rating(stock_name, max_results=5)
        except Exception:
            pass

        # ── 2. 搜索社交媒体情绪 ───────────────────────────────────────────
        social_data = []
        try:
            # 通过 DuckDuckGo 搜索社交媒体讨论
            social_data = search_social_sentiment(stock_name, max_results=10)
        except Exception:
            pass

        # ── 3. 搜索最新公告和新闻 ──────────────────────────────────────────
        news_data = []
        try:
            # 搜索股票相关的公告和业绩新闻
            news_data = search_news(f"{stock_name} 公告 业绩", max_results=5)
        except Exception:
            pass

        # ── 4. 获取龙虎榜数据 ───────────────────────────────────────────────
        akshare = get_akshare_client()
        lhb_info = _get_lhb_data(akshare, end_date, ts_code)

        # ── 5. 构建分析数据 ─────────────────────────────────────────────
        analysis_data = _format_sentiment_data(
            analyst_ratings, social_data, news_data, lhb_info, ts_code, stock_name
        )

        # ── 6. 构建 prompt ───────────────────────────────────────────────
        user_prompt = f"""{analysis_data}

请根据以上舆情信息，进行市场情绪分析。

输出格式（严格按此格式）：
评分: [0-100的数值]
分析内容: [详细的市场情绪分析说明，3-5句话，重点关注分析师评级和社交媒体情绪倾向]
关键发现: [3-5个关键发现，每行一个，格式如 "- 发现1"]
"""

        # ── 7. 调用 LLM ─────────────────────────────────────────────────
        client = get_minimax_client()
        messages = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ]
        response = client.chat(messages)
        content = response["choices"][0]["message"]["content"]

        # ── 8. 解析结果 ─────────────────────────────────────────────────
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

        # ── 9. 计算置信度 ────────────────────────────────────────────────
        # 舆情数据来源分散（社交媒体、研报、新闻），质量参差不齐
        sentiment_count = len(analyst_ratings) + len(social_data) + len(news_data)
        base_quality = min(1.0, sentiment_count / 15) if sentiment_count > 0 else 0.2
        data_quality = DataQuality(
            quality_score=base_quality,
            completeness=min(1.0, sentiment_count / 10),
            timeliness=1.0,  # 搜索的都是近期信息
            consistency=0.7,  # 舆情来源分散，一致性较低
            details={
                "analyst_ratings_count": len(analyst_ratings),
                "social_data_count": len(social_data),
                "news_count": len(news_data),
                "lhb_count": lhb_info.get("count", 0),
            },
        )
        confidence = calculate_confidence_from_quality(data_quality, base_confidence=0.6)

        # ── 10. 构建 AgentResult ─────────────────────────────────────────
        result = AgentResult(
            agent_name="sentiment",        # Agent 名称
            score=score,                   # 舆情评分
            confidence=confidence,          # 置信度
            data_quality=data_quality,     # 数据质量
            conclusion=conclusion or content[:200],
            recommendation="舆情分析已完成，请参考评分和关键发现",
            key_findings=key_findings[:5],
            raw_data={
                "analyst_ratings_count": len(analyst_ratings),  # 分析师评级数量
                "social_data_count": len(social_data),           # 社交数据数量
                "news_count": len(news_data),                     # 新闻数量
                "lhb_info": lhb_info,                            # 龙虎榜信息
            },
        )

        # ── 11. 更新状态 ──────────────────────────────────────────────────
        elapsed = time.time() - start_time
        print(f"  ✅ [舆情监控师] 完成 - 耗时: {elapsed:.1f}s")
        if result.conclusion:
            print(f"     结论: {result.conclusion}")

        state.sentiment_result = result
        existing_tasks = getattr(state, "completed_tasks", [])
        state.completed_tasks = list(existing_tasks) + ["sentiment"]

        return state

    return {"analyze_sentiment": analyze_sentiment}