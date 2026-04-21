# src/compliance/data_source_tracer.py
"""数据溯源追踪器

标注数据来源、置信度、数据时效，确保分析结果可追溯。

设计背景：
- 合规要求：金融分析报告需要说明数据来源
- 质量控制：通过置信度追踪，可以评估分析结果的可靠性
- 问题排查：当分析结果有问题时，可以追溯数据源头

数据来源类型：
1. akshare - AKShare 库获取的数据（K线、财务数据等）
2. search - DuckDuckGo 搜索获取的数据（新闻、舆情等）
3. llm - MiniMax 大模型生成的内容

使用方法：
    from src.compliance import DataSourceTracer

    # 创建溯源追踪器
    tracer = DataSourceTracer()

    # 添加数据来源条目
    tracer.add_entry("akshare", "stock_zh_a_hist", "K线数据", 0.85, 0.90)
    tracer.add_search_entry("news", "新闻数据", 0.70)
    tracer.add_llm_entry("MiniMax-Text-01", "市场分析结论", 0.80)

    # 获取格式化后的溯源信息
    tracing_info = tracer.format_tracing_info()
    summary = tracer.get_summary()
"""

# ─── 标准库 ─────────────────────────────────────────────────────────────────
from datetime import datetime  # 日期时间，用于记录数据获取时间
from typing import Any, Dict, List, Optional  # 类型注解


class DataSourceEntry:
    """数据来源条目

    记录单个数据来源的详细信息，包括：
    - 来源类型（akshare/search/llm）
    - 具体数据源名称
    - 数据描述
    - 置信度（0-1）
    - 获取时间
    - 数据质量分数（可选）
    """

    def __init__(
        self,
        source_type: str,       # 来源类型
        source_name: str,        # 具体数据源名称
        data_description: str,   # 数据描述
        confidence: float,       # 置信度 0-1
        timestamp: datetime,     # 数据获取时间
        quality_score: Optional[float] = None,  # 数据质量分数 0-1
    ):
        """初始化数据来源条目

        Args:
            source_type: 来源类型 ("akshare", "search", "llm")
            source_name: 具体数据源名称，如 "stock_zh_a_hist"
            data_description: 数据描述，如 "平安银行K线数据"
            confidence: 置信度 0-1，1=完全可信
            timestamp: 数据获取时间
            quality_score: 数据质量分数 0-1（可选）
        """
        self.source_type = source_type        # 保存来源类型
        self.source_name = source_name         # 保存数据源名称
        self.data_description = data_description  # 保存数据描述
        self.confidence = confidence          # 保存置信度
        self.timestamp = timestamp           # 保存时间戳
        self.quality_score = quality_score   # 保存质量分数（可为 None）

    def to_dict(self) -> Dict[str, Any]:
        """将条目转换为字典

        Returns:
            包含所有字段的字典，用于序列化
        """
        return {
            "source_type": self.source_type,  # 来源类型
            "source_name": self.source_name,   # 数据源名称
            "data_description": self.data_description,  # 数据描述
            "confidence": self.confidence,     # 置信度
            # 时间戳转换为 ISO 格式字符串，便于序列化
            "timestamp": self.timestamp.isoformat() if self.timestamp else None,
            "quality_score": self.quality_score,  # 质量分数
        }

    def __repr__(self) -> str:
        """返回条目的字符串表示

        用于调试和日志输出，格式：[TYPE] name (confidence%)
        """
        return (
            f"DataSourceEntry(type={self.source_type}, "
            f"name={self.source_name}, "
            f"confidence={self.confidence:.0%})"
        )


class DataSourceTracer:
    """数据溯源追踪器

    追踪所有数据来源、置信度和数据时效。

    核心功能：
    1. add_entry() - 添加通用数据来源条目
    2. add_akshare_entry() - 添加 AKShare 数据来源
    3. add_search_entry() - 添加搜索数据来源
    4. add_llm_entry() - 添加 LLM 生成内容来源
    5. format_tracing_info() - 格式化溯源信息为报告文本
    6. get_summary() - 获取溯源摘要统计

    数据流：
    Agent 获取数据 → tracer.add_entry() 记录 → Supervisor 生成报告时调用 format_tracing_info()
    """

    def __init__(self):
        """初始化溯源追踪器"""
        self.entries: List[DataSourceEntry] = []  # 存储所有数据来源条目

    def add_entry(
        self,
        source_type: str,
        source_name: str,
        data_description: str,
        confidence: float,
        quality_score: Optional[float] = None,
    ):
        """添加数据来源条目（通用方法）

        Args:
            source_type: 来源类型 ("akshare", "search", "llm")
            source_name: 具体数据源名称
            data_description: 数据描述
            confidence: 置信度 0-1
            quality_score: 数据质量分数 0-1（可选）
        """
        # 创建数据来源条目，包含当前时间戳
        entry = DataSourceEntry(
            source_type=source_type,
            source_name=source_name,
            data_description=data_description,
            confidence=confidence,
            timestamp=datetime.now(),  # 自动添加获取时间
            quality_score=quality_score,
        )
        self.entries.append(entry)  # 添加到条目列表

    def add_akshare_entry(
        self,
        source_name: str,
        data_description: str,
        confidence: float = 0.85,
        quality_score: Optional[float] = None,
    ):
        """添加 AKShare 数据来源条目

        AKShare 是本项目的主要数据来源，提供 K线、财务、板块等数据。
        默认置信度 0.85（较高，因为是正规数据源）。

        Args:
            source_name: AKShare 函数名，如 "stock_zh_a_hist"
            data_description: 数据描述，如 "平安银行日K线数据"
            confidence: 置信度，默认 0.85
            quality_score: 数据质量分数（可选）
        """
        self.add_entry(
            source_type="akshare",
            source_name=source_name,
            data_description=data_description,
            confidence=confidence,
            quality_score=quality_score,
        )

    def add_search_entry(
        self,
        source_name: str,
        data_description: str,
        confidence: float = 0.70,
    ):
        """添加搜索数据来源条目

        搜索数据包括新闻、舆情、分析师评级等。
        默认置信度 0.70（中等，因为搜索结果质量参差不齐）。

        Args:
            source_name: 搜索源名称，如 "news", "social_sentiment"
            data_description: 数据描述，如 "平安银行相关新闻"
            confidence: 置信度，默认 0.70
        """
        self.add_entry(
            source_type="search",
            source_name=source_name,
            data_description=data_description,
            confidence=confidence,
        )

    def add_llm_entry(
        self,
        model_name: str,
        data_description: str,
        confidence: float = 0.80,
    ):
        """添加 LLM 数据来源条目

        LLM 生成内容包括分析结论、市场观点等。
        默认置信度 0.80（中等偏上，因为大模型有幻觉风险）。

        Args:
            model_name: 模型名称，如 "MiniMax-Text-01"
            data_description: 数据描述，如 "市场走势分析结论"
            confidence: 置信度，默认 0.80
        """
        self.add_entry(
            source_type="llm",
            source_name=model_name,
            data_description=data_description,
            confidence=confidence,
        )

    def format_tracing_info(self) -> str:
        """格式化溯源信息为报告文本（简洁版）

        用于在分析报告中展示数据来源和置信度。

        Returns:
            格式化的溯源信息字符串

        示例输出：
            **数据来源与置信度：**
            1. `[AKSHARE]` stock_zh_a_hist - 置信度: 85%
            2. `[SEARCH]` news - 置信度: 70%
        """
        # 如果没有任何条目，返回空提示
        if not self.entries:
            return "\n\n**数据来源**：无记录"

        lines = ["\n\n**数据来源与置信度：**"]  # 标题行
        for i, entry in enumerate(self.entries, 1):
            confidence_pct = entry.confidence * 100  # 转换为百分比
            # 如果有质量分数，添加质量信息
            quality_str = f" (数据质量: {entry.quality_score:.0%})" if entry.quality_score else ""
            # 来源类型大写显示，如 [AKSHARE]
            type_label = entry.source_type.upper()
            lines.append(
                f"{i}. `[{type_label}]` {entry.source_name} - "
                f"置信度: {confidence_pct:.0f}%{quality_str}"
            )

        return "\n".join(lines)

    def format_tracing_info_full(self) -> str:
        """格式化完整溯源信息（包含时间和详情）

        用于需要详细展示每个数据来源的场景。

        Returns:
            格式化的完整溯源信息字符串

        示例输出：
            **数据来源详情：**
            1. `[AKSHARE]` **stock_zh_a_hist**
               - 描述: 平安银行日K线数据
               - 置信度: 85%
               - 获取时间: 2024-04-21 10:30:00
        """
        # 如果没有任何条目，返回空提示
        if not self.entries:
            return "\n\n**数据来源**：无记录"

        lines = ["\n\n**数据来源详情：**"]  # 标题行
        for i, entry in enumerate(self.entries, 1):
            confidence_pct = entry.confidence * 100  # 转换为百分比
            # 如果有质量分数，添加质量信息
            quality_str = f", 数据质量: {entry.quality_score:.0%}" if entry.quality_score else ""
            # 格式化时间戳
            time_str = entry.timestamp.strftime("%Y-%m-%d %H:%M:%S") if entry.timestamp else "未知"
            lines.append(
                f"{i}. `[{entry.source_type.upper()}]` **{entry.source_name}**\n"
                f"   - 描述: {entry.data_description}\n"
                f"   - 置信度: {confidence_pct:.0f}%{quality_str}\n"
                f"   - 获取时间: {time_str}"
            )

        return "\n".join(lines)

    def get_summary(self) -> Dict[str, Any]:
        """获取溯源摘要统计

        用于汇总整体数据来源情况。

        Returns:
            溯源摘要字典，包含：
            - total_sources: 总来源数量
            - avg_confidence: 平均置信度
            - source_types: 来源类型列表
            - sources_by_type: 各类型来源数量
        """
        # 如果没有任何条目，返回空摘要
        if not self.entries:
            return {
                "total_sources": 0,      # 总来源数
                "avg_confidence": 0,      # 平均置信度
                "source_types": [],       # 来源类型列表
                "sources_by_type": {},    # 各类型数量
            }

        # 计算总置信度
        total_confidence = sum(e.confidence for e in self.entries)
        # 获取所有来源类型（去重）
        source_types = list(set(e.source_type for e in self.entries))

        return {
            "total_sources": len(self.entries),  # 总来源数量
            "avg_confidence": total_confidence / len(self.entries),  # 平均置信度
            "source_types": sorted(source_types),  # 来源类型列表（排序）
            # 各类型来源数量统计
            "sources_by_type": {
                stype: sum(1 for e in self.entries if e.source_type == stype)
                for stype in source_types
            },
        }

    def get_low_confidence_sources(self, threshold: float = 0.6) -> List[DataSourceEntry]:
        """获取低置信度数据源

        用于识别需要关注的数据来源。

        Args:
            threshold: 置信度阈值，默认 0.6（低于 60% 认为是低置信度）

        Returns:
            低置信度条目列表
        """
        # 过滤出置信度低于阈值的条目
        return [e for e in self.entries if e.confidence < threshold]

    def clear(self):
        """清空所有溯源记录

        用于开始新的分析任务前重置状态。
        """
        self.entries = []

    def to_dict(self) -> Dict[str, Any]:
        """导出为字典（用于序列化）

        Returns:
            包含所有条目和摘要的字典
        """
        return {
            "entries": [e.to_dict() for e in self.entries],  # 所有条目
            "summary": self.get_summary(),  # 摘要统计
        }
