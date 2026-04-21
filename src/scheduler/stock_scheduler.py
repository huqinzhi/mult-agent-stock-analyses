"""定时调度器

V1 版本说明：
- 当前 V1 版本暂不开放定时调度批量分析功能
- 调度器接口已预留，将在 V2 版本开放
- V2 将支持交易日定时执行批量股票分析任务

V1 版本的替代方案：
- 使用 cron 或其他调度工具定时调用单股分析命令
- 示例: python -m src.main --stock 000001.SZ --name 平安银行 --notify console
"""
import logging
from datetime import datetime

from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.cron import CronTrigger

from src.batch.batch_manager import BatchAnalysisManager
from src.config.stock_pool import get_stock_pool

logger = logging.getLogger(__name__)


def run_daily_analysis(notify_channels=None):
    """每日定时分析任务

    V1 版本说明：
    - 此功能依赖 BatchAnalysisManager，V1 版本暂不开放
    - V2 将支持多股票批量定时分析

    Args:
        notify_channels: 通知渠道列表
    """
    logger.warning("V1 版本暂不开放定时批量分析功能，请在 V2 版本使用")
    print("\n" + "=" * 60)
    print("⚠️  定时调度批量分析功能 V1 版本暂不开放")
    print("   当前版本仅支持单个股票分析")
    print("   如需定时分析，请使用外部调度工具（如 cron）调用单股分析")
    print("   示例: python -m src.main --stock 000001.SZ --name 平安银行 --notify console")
    print("=" * 60 + "\n")

    # V1: 暂时不执行任何分析
    # stock_pool = get_stock_pool()
    # stock_list = stock_pool.get_enabled_stocks()
    #
    # if not stock_list:
    #     logger.warning("股票池为空，跳过今日分析")
    #     return
    #
    # logger.info(f"开始执行每日分析，共 {len(stock_list)} 只股票")
    #
    # manager = BatchAnalysisManager(max_concurrency=3)
    # results = manager.analyze_batch(stock_list, notify_channels=notify_channels)
    #
    # success_count = sum(1 for r in results if r.get("success", False))
    # logger.info(f"每日分析完成: {success_count}/{len(stock_list)} 成功")


def start_scheduler(
    notify_channels=None,
    time_str: str = "10:00",
):
    """启动调度器

    V1 版本说明：
    - 调度器功能已预留，但定时批量分析暂不开放
    - V2 将支持每个交易日定时分析股票池中所有股票

    Args:
        notify_channels: 通知渠道列表
        time_str: 执行时间，格式 "HH:MM"
    """
    logger.warning("V1 版本暂不开放定时调度功能，请在 V2 版本使用")
    print("\n" + "=" * 60)
    print("⚠️  定时调度功能 V1 版本暂不开放")
    print("   当前版本仅支持单个股票分析")
    print("   定时调度功能正在开发中，将在 V2 版本开放")
    print("=" * 60 + "\n")

    # V1: 暂时不启动调度器
    # scheduler = BlockingScheduler()
    #
    # # 解析时间
    # try:
    #     hour, minute = time_str.split(":")
    #     hour = int(hour)
    #     minute = int(minute)
    # except (ValueError, AttributeError):
    #     logger.error(f"无效的时间格式: {time_str}，使用默认 10:00")
    #     hour, minute = 10, 0
    #
    # # 交易日（周一到周五）定时执行
    # trigger = CronTrigger(day_of_week="mon-fri", hour=hour, minute=minute)
    #
    # scheduler.add_job(
    #     run_daily_analysis,
    #     trigger=trigger,
    #     args=[notify_channels],
    #     id="daily_stock_analysis",
    #     name="每日股票分析",
    #     replace_existing=True,
    # )
    #
    # logger.info(f"调度器已启动，执行时间: {time_str}（每个交易日）")
    # scheduler.start()

    # 解析时间
    try:
        hour, minute = time_str.split(":")
        hour = int(hour)
        minute = int(minute)
    except (ValueError, AttributeError):
        logger.error(f"无效的时间格式: {time_str}，使用默认 10:00")
        hour, minute = 10, 0

    # 交易日（周一到周五）定时执行
    trigger = CronTrigger(day_of_week="mon-fri", hour=hour, minute=minute)

    scheduler.add_job(
        run_daily_analysis,
        trigger=trigger,
        args=[notify_channels],
        id="daily_stock_analysis",
        name="每日股票分析",
        replace_existing=True,
    )

    logger.info(f"调度器已启动，执行时间: {time_str}（每个交易日）")
    scheduler.start()