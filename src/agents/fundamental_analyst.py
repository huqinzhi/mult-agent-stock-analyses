"""
基本面分析师 Agent 模块

负责财务报表解读、估值模型分析和行业对比。

分析流程：
    1. 获取财务指标数据（AKShare）
    2. 获取实时估值数据（市盈率、市净率等）
    3. 解析关键财务指标（ROE、ROA、毛利率、净利率等）
    4. 调用 LLM 生成基本面分析结论
    5. 写入 state.fundamental_result

Agent 结果：
    - score: 基本面评分（0-100）
    - conclusion: 基本面分析结论
    - key_findings: 财务发现
    - raw_data: 财务指标和估值数据
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

SYSTEM_PROMPT = """你是一位资深的基本面分析师，负责价值投资分析。

你的职责：
1. 财务报表解读（资产负债表、利润表、现金流量表）
2. 估值模型构建（DCF 现金流折现、DDM 股息折现模型等）
3. 行业对比分析（与行业平均、竞争对手关键指标对比）
4. 盈利能力评估（ROE、ROA，毛利率、净利率趋势）
5. 成长性分析（营收/利润增速、复合增长率）

输出要求：
- 评分：基本面评分 0-100（仅描述基本面好坏，不作为投资建议）
- 分析内容：详细的基本面分析说明
- 关键发现：3-5 个重要财务发现

【评分标准】（评分越高基本面越好）
- 80-100: 基本面极强
- 60-79: 基本面较好
- 40-59: 基本面中性
- 20-39: 基本面较差
- 0-19: 基本面极差

【重要】你只输出分析内容，不提供任何买卖建议。"""


# ══════════════════════════════════════════════════════════════════════════════
# 辅助函数
# ══════════════════════════════════════════════════════════════════════════════

def _parse_financial_indicators(df: pd.DataFrame) -> Dict[str, Any]:
    """
    解析财务指标数据

    从财务指标 DataFrame 中提取关键指标：
    - 盈利能力：ROE（净资产收益率）、ROA（资产收益率）、毛利率、净利率
    - 财务结构：资产负债率、流动比率、速动比率
    - 每股指标：EPS（每股收益）、BPS（每股净资产）
    - 成长性：营收增速、净利润增速

    Args:
        df: 财务指标 DataFrame

    Returns:
        关键财务指标字典
    """
    if df is None or df.empty:
        return {}

    indicators = {}

    # ── 列名映射 ─────────────────────────────────────────────────────────
    # AKShare 返回的中文列名可能有多种写法，尝试多种可能
    col_mappings = {
        "roe": ["roe", "净资产收益率", "return_on_equity"],           # 净资产收益率
        "roa": ["roa", "资产收益率", "return_on_assets"],             # 资产收益率
        "gross_margin": ["gross_margin", "毛利率", "毛利润率"],       # 毛利率
        "net_margin": ["net_margin", "净利润率", "net_profit_margin"],  # 净利润率
        "debt_ratio": ["debt_ratio", "资产负债率"],                  # 资产负债率
        "current_ratio": ["current_ratio", "流动比率"],             # 流动比率
        "quick_ratio": ["quick_ratio", "速动比率"],                  # 速动比率
        "eps": ["eps", "每股收益", "基本每股收益"],                   # 每股收益
        "bvps": ["bvps", "每股净资产"],                               # 每股净资产
        "pe_ratio": ["pe", "市盈率"],                                  # 市盈率
        "pb_ratio": ["pb", "市净率"],                                  # 市净率
    }

    # ── 遍历映射，尝试找到匹配的列 ────────────────────────────────────────
    for key, possible_cols in col_mappings.items():
        for col in possible_cols:
            if col in df.columns:
                try:
                    val = df[col].iloc[-1]  # 取最新一期数据
                    if pd.notna(val):  # 确保不是空值
                        indicators[key] = float(val)
                        break  # 找到一个有效值就跳出
                except (ValueError, TypeError):
                    pass  # 解析失败，尝试下一个列名

    # ── 营收增速 ─────────────────────────────────────────────────────────
    # 营收增速 = (本期营收 - 上期营收) / 上期营收 * 100%
    if "营业总收入" in df.columns or "营业收入" in df.columns:
        rev_col = "营业总收入" if "营业总收入" in df.columns else "营业收入"
        try:
            revenues = df[rev_col].dropna()  # 去除空值
            if len(revenues) >= 2:  # 至少需要两期数据
                growth = (revenues.iloc[-1] - revenues.iloc[-2]) / revenues.iloc[-2] * 100
                indicators["revenue_growth"] = round(float(growth), 2)
        except Exception:
            pass

    # ── 净利润增速 ───────────────────────────────────────────────────────
    if "净利润" in df.columns:
        try:
            profits = df["净利润"].dropna()
            if len(profits) >= 2:
                growth = (profits.iloc[-1] - profits.iloc[-2]) / abs(profits.iloc[-2]) * 100
                indicators["profit_growth"] = round(float(growth), 2)
        except Exception:
            pass

    return indicators


def _get_stock_spot_data(ts_code: str) -> Dict[str, Any]:
    """
    获取个股实时数据（含估值）

    从 AKShare 获取实时行情数据：
    - PE（市盈率）：市值/净利润，衡量估值高低
    - PB（市净率）：市值/净资产，衡量资产价值
    - 总市值、流通市值

    Args:
        ts_code: 股票代码（如 "000001.SZ"）

    Returns:
        实时估值数据字典
    """
    try:
        import akshare as ak
        # stock_zh_a_spot_em 返回所有 A 股的实时行情
        df = ak.stock_zh_a_spot_em()
        # 筛选当前股票
        stock_row = df[df["代码"] == ts_code.split(".")[0]]  # 去掉 .SZ/.SH
        if not stock_row.empty:
            row = stock_row.iloc[0]
            return {
                "pe": float(row.get("市盈率-动态", 0)) if pd.notna(row.get("市盈率-动态", 0)) else None,
                "pb": float(row.get("市净率", 0)) if pd.notna(row.get("市净率", 0)) else None,
                "market_cap": float(row.get("总市值", 0)) if pd.notna(row.get("总市值", 0)) else None,
                "float_market_cap": float(row.get("流通市值", 0)) if pd.notna(row.get("流通市值", 0)) else None,
            }
    except Exception:
        pass
    return {}


def _format_fundamental_data(
    fina_df: pd.DataFrame,
    spot_data: Dict[str, Any],
    indicators: Dict[str, Any],
    ts_code: str,
    stock_name: str,
) -> str:
    """
    构建发给 LLM 的基本面分析数据文本

    Args:
        fina_df: 财务指标 DataFrame
        spot_data: 实时估值数据
        indicators: 解析后的财务指标
        ts_code: 股票代码
        stock_name: 股票名称

    Returns:
        格式化的基本面数据文本
    """
    lines = []
    lines.append(f"=== {stock_name} ({ts_code}) 基本面分析数据 ===\n")

    # ── 1. 估值指标 ─────────────────────────────────────────────────────
    if spot_data:
        lines.append(f"【估值指标】（最新）")
        if spot_data.get("pe"):
            lines.append(f"市盈率(动态): {spot_data['pe']:.2f}")
        if spot_data.get("pb"):
            lines.append(f"市净率: {spot_data['pb']:.2f}")
        if spot_data.get("market_cap"):
            cap = spot_data["market_cap"] / 100000000  # 转换为亿元
            lines.append(f"总市值: {cap:.2f} 亿元")
        if spot_data.get("float_market_cap"):
            float_cap = spot_data["float_market_cap"] / 100000000
            lines.append(f"流通市值: {float_cap:.2f} 亿元")
        lines.append("")

    # ── 2. 财务指标 ─────────────────────────────────────────────────────
    if indicators:
        lines.append(f"【财务指标】")
        key_metrics = ["roe", "roa", "gross_margin", "net_margin", "debt_ratio", "eps", "bvps"]
        for key in key_metrics:
            if key in indicators:
                label_map = {
                    "roe": "净资产收益率(ROE)",
                    "roa": "资产收益率(ROA)",
                    "gross_margin": "毛利率",
                    "net_margin": "净利润率",
                    "debt_ratio": "资产负债率",
                    "eps": "每股收益",
                    "bvps": "每股净资产",
                }
                val = indicators[key]
                # 比率类指标加 % 后缀
                suffix = "%" if key in ["gross_margin", "net_margin", "debt_ratio"] else ""
                lines.append(f"{label_map.get(key, key)}: {val:.2f}{suffix}")
        if indicators.get("revenue_growth"):
            lines.append(f"营收增速: {indicators['revenue_growth']:.1f}%")
        if indicators.get("profit_growth"):
            lines.append(f"净利润增速: {indicators['profit_growth']:.1f}%")
        lines.append("")

    # ── 3. 财务数据摘要 ─────────────────────────────────────────────────
    if fina_df is not None and not fina_df.empty:
        lines.append(f"【财务数据摘要】（最新 {min(4, len(fina_df))} 期）")
        # 收集需要显示的列
        cols_to_show = []
        for col in ["报告日期", "营业收入", "净利润", "净资产收益率", "资产负债率"]:
            if col in fina_df.columns:
                cols_to_show.append(col)

        # 显示最新几期数据
        for _, row in fina_df.head(4).iterrows():
            date = row.get("报告日期", "")
            line_parts = [str(date)]
            for col in cols_to_show[1:]:  # 跳过报告日期列
                val = row.get(col, "N/A")
                if pd.notna(val):
                    try:
                        line_parts.append(f"{float(val):.2f}")
                    except (ValueError, TypeError):
                        line_parts.append(str(val)[:10])
                else:
                    line_parts.append("N/A")
            lines.append(" | ".join(line_parts))
        lines.append("")

    return "\n".join(lines)


# ══════════════════════════════════════════════════════════════════════════════
# Agent 创建函数
# ══════════════════════════════════════════════════════════════════════════════

def create_fundamental_analyst(model: str = "MiniMax-Text-01") -> Dict[str, Any]:
    """
    创建基本面分析师 Agent

    Args:
        model: 模型名称

    Returns:
        包含 analyze_fundamental 函数的字典
    """

    def analyze_fundamental(state: AgentState) -> AgentState:
        """
        执行基本面分析

        LangGraph 节点函数：
        - 输入：AgentState（包含 query）
        - 输出：AgentState（包含 fundamental_result）
        """
        start_time = time.time()
        print(f"  ⏳ [基本面分析师] 开始分析...")

        query = state.query
        if query is None:
            return state

        ts_code = query.ts_code
        stock_name = query.stock_name or ts_code
        start_date = query.start_date
        end_date = query.end_date

        # ── 1. 获取财务指标数据 ───────────────────────────────────────────
        akshare = get_akshare_client()
        fina_df = None
        try:
            # 获取财务指标（年报/季报数据，可能为空或失败）
            fina_df = akshare.get_fina_indicator(ts_code, start_date, end_date)
        except Exception:
            pass  # 财务数据可能不可用，继续分析

        # ── 2. 解析财务指标 ──────────────────────────────────────────────
        indicators = _parse_financial_indicators(fina_df)

        # ── 3. 获取实时估值数据 ──────────────────────────────────────────
        spot_data = _get_stock_spot_data(ts_code)

        # ── 4. 构建分析数据 ─────────────────────────────────────────────
        analysis_data = _format_fundamental_data(
            fina_df, spot_data, indicators, ts_code, stock_name
        )

        # ── 5. 构建 prompt ───────────────────────────────────────────────
        user_prompt = f"""{analysis_data}

请根据以上基本面数据，进行财务分析和估值评估。

输出格式（严格按此格式）：
评分: [0-100的数值]
分析内容: [详细的基本面分析说明，3-5句话，重点关注盈利能力和估值水平]
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
        # 财务数据有延迟（季报、年报发布有时滞），所以置信度较低
        data_freshness = 0.5  # 财务数据可能有延迟
        data_completeness = min(1.0, len(indicators) / 5) if indicators else 0.2  # 指标完整性
        data_quality = DataQuality(
            quality_score=data_freshness * data_completeness,  # 综合分数
            completeness=data_completeness,                    # 完整性
            timeliness=data_freshness,                        # 时效性（财务数据有延迟）
            consistency=0.8,                                  # 一致性
            details={"indicators_count": len(indicators), "has_fina_df": fina_df is not None},
        )
        # 财务数据基础置信度较低（0.6）
        confidence = calculate_confidence_from_quality(data_quality, base_confidence=0.6)

        # ── 9. 构建 AgentResult ─────────────────────────────────────────
        result = AgentResult(
            agent_name="fundamental",       # Agent 名称
            score=score,                   # 基本面评分
            confidence=confidence,          # 置信度
            data_quality=data_quality,     # 数据质量
            conclusion=conclusion or content[:200],
            recommendation="基本面分析已完成，请参考评分和关键发现",
            key_findings=key_findings[:5],
            raw_data={
                "indicators": indicators,                      # 财务指标
                "spot_data": spot_data,                        # 实时估值
                "fina_rows": len(fina_df) if fina_df is not None and not fina_df.empty else 0,
            },
        )

        # ── 10. 更新状态 ──────────────────────────────────────────────────
        elapsed = time.time() - start_time
        print(f"  ✅ [基本面分析师] 完成 - 耗时: {elapsed:.1f}s")
        if result.conclusion:
            print(f"     结论: {result.conclusion}")

        state.fundamental_result = result
        existing_tasks = getattr(state, "completed_tasks", [])
        state.completed_tasks = list(existing_tasks) + ["fundamental"]

        return state

    return {"analyze_fundamental": analyze_fundamental}