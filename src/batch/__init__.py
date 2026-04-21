"""
批量分析模块

支持多股票并发分析，带并发控制。

使用示例：
    from src.batch.batch_manager import BatchAnalysisManager

    manager = BatchAnalysisManager(max_concurrency=3)
    results = manager.analyze_batch(stock_list, notify_channels=["serverchan"])
"""

from src.batch.batch_manager import BatchAnalysisManager

__all__ = ["BatchAnalysisManager"]