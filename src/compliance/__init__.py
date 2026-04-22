# src/compliance/__init__.py
"""合规与免责模块

P0 风险控制核心模块

V2 变更：
- DisclaimerFilter 已放宽约束，不再过滤投资建议
- MandatoryDisclaimer 简化免责文本
- DataSourceTracer 保持不变

使用方法：
    from src.compliance import (
        get_disclaimer_filter,
        MandatoryDisclaimer,
        inject_disclaimer,
        DataSourceTracer,
    )

    # 过滤（V2 不再做过滤）
    disclaimer_filter = get_disclaimer_filter()
    filtered = disclaimer_filter.filter(content)

    # 注入免责
    report = inject_disclaimer(analysis_content)

    # 追踪数据来源
    tracer = DataSourceTracer()
    tracer.add_entry("akshare", "stock_zh_a_hist", "K线数据", 0.85)
"""

from .disclaimer_filter import (
    DisclaimerFilter,
    get_disclaimer_filter,
)
from .mandatory_disclaimer import (
    MandatoryDisclaimer,
    MANDATORY_DISCLAIMER,
    get_default_injector,
    inject_disclaimer,
)
from .data_source_tracer import (
    DataSourceTracer,
    DataSourceEntry,
)

__all__ = [
    # DisclaimerFilter (V2 放宽版)
    "DisclaimerFilter",
    "get_disclaimer_filter",
    # MandatoryDisclaimer (V2 简化版)
    "MandatoryDisclaimer",
    "MANDATORY_DISCLAIMER",
    "get_default_injector",
    "inject_disclaimer",
    # DataSourceTracer
    "DataSourceTracer",
    "DataSourceEntry",
]
