"""
情报官 Agent 模块

负责宏观经济分析、行业动态追踪、政策影响评估和板块资金轮动分析。

分析流程：
    1. 搜索相关新闻（通过 DuckDuckGo）
    2. 搜索行业动态和政策
    3. 获取板块资金流向数据（AKShare）
    4. 获取行业信息
    5. 调用 LLM 生成情报分析结论
    6. 写入 state.intelligence_result

Agent 结果：
    - score: 情报环境评分（0-100）
    - conclusion: 情报分析结论
    - key_findings: 政策/行业发现
    - raw_data: 新闻数量、行业信息
"""

# ─── 标准库 ─────────────────────────────────────────────────────────────────
import time  # 计时

from typing import Any, Dict  # 类型注解

# ─── 项目内部导入 ──────────────────────────────────────────────────────────────
from src.graph.state import AgentResult, AgentState, DataQuality, calculate_confidence_from_quality
from src.llm import get_minimax_client  # MiniMax API 客户端
from src.tools import get_akshare_client, search_news, search_web  # 搜索工具和 AKShare 客户端


# ══════════════════════════════════════════════════════════════════════════════
# 系统提示词
# ══════════════════════════════════════════════════════════════════════════════

SYSTEM_PROMPT = """你是一位财经情报专家，负责宏观和行业分析。

你的职责：
1. 宏观经济环境分析（利率、汇率、CPI、GDP 等）
2. 行业发展趋势和竞争格局追踪
3. 政策变化和监管动向评估
4. 重大事件和公告的信息提取
5. 地缘政治因素对市场的影响分析
6. 板块资金轮动和热点切换分析

输出要求：
- 评分：情报环境评分 0-100（仅描述环境好坏，不作为投资建议）
- 分析内容：详细的情报分析说明
- 关键发现：3-5 个重要情报发现

【评分标准】（评分越高宏观环境越好）
- 80-100: 情报环境极好
- 60-79: 情报环境较好
- 40-59: 情报环境中性
- 20-39: 情报环境较差
- 0-19: 情报环境极差

【重要】你只输出分析内容，不提供任何买卖建议。"""


# ══════════════════════════════════════════════════════════════════════════════
# 辅助函数
# ══════════════════════════════════════════════════════════════════════════════

def _format_intelligence_data(
    news_list: list,
    industry_news: list,
    sector_flow: Dict[str, Any],
    ts_code: str,
    stock_name: str,
    industry: str,
) -> str:
    """
    构建发给 LLM 的情报分析数据文本

    将新闻、行业动态、板块资金流格式化为易读的文本。

    Args:
        news_list: 新闻列表（search_news 返回）
        industry_news: 行业动态列表（search_web 返回）
        sector_flow: 板块资金流 DataFrame（AKShare 返回）
        ts_code: 股票代码
        stock_name: 股票名称
        industry: 所属行业

    Returns:
        格式化的情报数据文本
    """
    lines = []
    lines.append(f"=== {stock_name} ({ts_code}) 情报分析数据 ===")
    if industry:
        lines.append(f"所属行业: {industry}")
    lines.append("")

    # ── 1. 最新新闻 ─────────────────────────────────────────────────────
    if news_list:
        lines.append(f"【最新新闻】（共 {len(news_list)} 条）")
        for i, news in enumerate(news_list[:8], 1):  # 最多显示 8 条
            title = news.get("title", "")[:60]  # 标题截断 60 字符
            date = news.get("date", "")         # 日期
            snippet = news.get("snippet", "")[:100]  # 摘要截断 100 字符
            lines.append(f"{i}. {title}")
            if date:
                lines.append(f"   日期: {date}")
            if snippet:
                lines.append(f"   摘要: {snippet}...")
            lines.append("")
    else:
        lines.append("【最新新闻】未找到相关新闻")
        lines.append("")

    # ── 2. 行业动态与政策 ───────────────────────────────────────────────
    if industry_news:
        lines.append(f"【行业动态与政策】（共 {len(industry_news)} 条）")
        for news in industry_news[:5]:  # 最多显示 5 条
            title = news.get("title", "")[:60]
            lines.append(f"- {title}")
        lines.append("")

    # ── 3. 板块资金流向 ─────────────────────────────────────────────────
    if sector_flow and not sector_flow.empty:
        lines.append("【板块资金流向】（近5日）")
        for _, row in sector_flow.head(5).iterrows():
            # 尝试不同列名（AKShare 返回的列名可能不同）
            sector = row.get("板块名称", row.get("行业板块", ""))
            flow = row.get("今日主力净流入-净额", row.get("今日主力净流入", "N/A"))
            lines.append(f"- {sector}: {flow}")
        lines.append("")

    return "\n".join(lines)


# ══════════════════════════════════════════════════════════════════════════════
# Agent 创建函数
# ══════════════════════════════════════════════════════════════════════════════

def create_intelligence_officer(model: str = "MiniMax-Text-01") -> Dict[str, Any]:
    """
    创建情报官 Agent

    Args:
        model: 模型名称

    Returns:
        包含 gather_intelligence 函数的字典
    """

    def gather_intelligence(state: AgentState) -> AgentState:
        """
        搜集情报并分析

        LangGraph 节点函数：
        - 输入：AgentState（包含 query）
        - 输出：AgentState（包含 intelligence_result）

        分析流程：
            1. 搜索股票相关新闻
            2. 搜索行业动态和政策
            3. 获取板块资金流数据
            4. 获取行业信息
            5. 调用 LLM 生成分析结论
        """
        start_time = time.time()
        print(f"  ⏳ [情报官] 开始分析...")

        query = state.query
        if query is None:
            return state

        ts_code = query.ts_code           # 股票代码
        stock_name = query.stock_name or ts_code  # 股票名称

        # ── 1. 搜索相关新闻 ───────────────────────────────────────────────
        news_results = []
        try:
            # search_news 使用 DuckDuckGo 搜索
            news_results = search_news(f"{stock_name} {ts_code}", max_results=10)
        except Exception:
            pass  # 搜索失败不影响分析

        # ── 2. 搜索行业动态和政策 ──────────────────────────────────────────
        industry_news = []
        try:
            # search_web 使用 DuckDuckGo 搜索
            industry_news = search_web(f"{stock_name} 行业 动态 政策", max_results=5)
        except Exception:
            pass

        # ── 3. 获取板块资金流 ────────────────────────────────────────────
        sector_flow_data = {}  # 板块资金流 DataFrame
        akshare = get_akshare_client()
        try:
            # 获取所有板块的资金流排名
            sector_df = akshare.get_sector_fund_flow()

            # 获取当前股票所属行业
            industry_info = akshare.get_industry_info(ts_code)
            industry = industry_info.get("industry", "")

            if industry and not sector_df.empty:
                # 筛选相关板块的数据
                sector_flow_data = sector_df[sector_df.apply(
                    lambda x: industry in str(x.get("板块名称", "")), axis=1
                )]
            else:
                # 没有行业信息，返回全部板块
                sector_flow_data = sector_df
        except Exception:
            pass

        # ── 4. 获取行业信息 ───────────────────────────────────────────────
        industry_name = ""
        try:
            info = akshare.get_industry_info(ts_code)
            industry_name = info.get("industry", "")
        except Exception:
            pass

        # ── 5. 构建分析数据 ─────────────────────────────────────────────
        analysis_data = _format_intelligence_data(
            news_results, industry_news, sector_flow_data,
            ts_code, stock_name, industry_name
        )

        # ── 6. 构建 prompt ───────────────────────────────────────────────
        user_prompt = f"""{analysis_data}

请根据以上情报信息，进行宏观和行业分析。

输出格式（严格按此格式）：
评分: [0-100的数值]
分析内容: [详细的情报分析说明，3-5句话，重点关注政策影响和行业趋势]
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
        # 置信度基于获取到的新闻数量（越多越可信）
        news_count = len(news_results) + len(industry_news)
        base_quality = min(1.0, news_count / 10) if news_count > 0 else 0.3
        data_quality = DataQuality(
            quality_score=base_quality,
            completeness=min(1.0, news_count / 5),
            timeliness=1.0,  # 新闻的时效性总是好的
            consistency=1.0,
            details={"news_count": news_count, "industry": industry_name},
        )
        confidence = calculate_confidence_from_quality(data_quality)

        # ── 10. 构建 AgentResult ─────────────────────────────────────────
        result = AgentResult(
            agent_name="intelligence",       # Agent 名称
            score=score,                    # 情报环境评分
            confidence=confidence,           # 置信度
            data_quality=data_quality,       # 数据质量
            conclusion=conclusion or content[:200],
            recommendation="情报分析已完成，请参考评分和关键发现",
            key_findings=key_findings[:5],
            raw_data={
                "news_count": news_count,                       # 新闻数量
                "industry": industry_name,                      # 所属行业
                "sector_flow_rows": len(sector_flow_data) if sector_flow_data else 0,
            },
        )

        # ── 11. 更新状态 ────────────────────────────────────────────────
        elapsed = time.time() - start_time
        print(f"  ✅ [情报官] 完成 - 耗时: {elapsed:.1f}s")
        if result.conclusion:
            print(f"     结论: {result.conclusion}")

        state.intelligence_result = result
        existing_tasks = getattr(state, "completed_tasks", [])
        state.completed_tasks = list(existing_tasks) + ["intelligence"]

        return state

    return {"gather_intelligence": gather_intelligence}