# src/compliance/__init__.py
"""合规与免责模块

P0 风险控制核心模块

提供：
- DisclaimerFilter: 过滤投资建议词
- MandatoryDisclaimer: 强制免责文本注入
- DataSourceTracer: 数据溯源追踪

使用方法：
    from src.compliance import (
        get_disclaimer_filter,
        MandatoryDisclaimer,
        DataSourceTracer,
    )

    # 过滤投资建议
    disclaimer_filter = get_disclaimer_filter()
    filtered = disclaimer_filter.filter(content)

    # 注入免责
    injector = MandatoryDisclaimer()
    report = injector.inject(analysis_content)

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
    DISCLAIMER_TEXT,
    get_default_injector,
)
from .data_source_tracer import (
    DataSourceTracer,
    DataSourceEntry,
)

__all__ = [
    # DisclaimerFilter
    "DisclaimerFilter",
    "get_disclaimer_filter",
    # MandatoryDisclaimer
    "MandatoryDisclaimer",
    "DISCLAIMER_TEXT",
    "get_default_injector",
    # DataSourceTracer
    "DataSourceTracer",
    "DataSourceEntry",
]
