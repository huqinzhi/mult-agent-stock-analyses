"""
时间工具模块（北京时间）

提供北京时间获取、交易日判断、节假日查询等功能。

使用场景：
- 判断是否为交易日（排除周末和法定节假日）
- 判断是否在交易时间内（9:30-11:30 / 13:00-15:00）
- 获取最近交易日、计算交易日差等

注意：
- A 股交易时间：周一至周五 9:30-11:30 / 13:00-15:00
- 法定节假日调休需要手动维护（当前预置了 2024-2026 年的节假日）
"""

# ─── 标准库 ─────────────────────────────────────────────────────────────────
from datetime import datetime, timedelta  # 日期时间操作
from typing import List, Optional, Set    # 类型注解

# ─── 第三方库 ─────────────────────────────────────────────────────────────────
import pandas as pd  # 数据处理（此模块未使用，可能是预留）
import pytz          # 时区处理


# ══════════════════════════════════════════════════════════════════════════════
# 中国法定节假日（2024-2026年）
# ══════════════════════════════════════════════════════════════════════════════
# 预置节假日的好处：无需联网查询，快速判断
# 缺点：需要手动更新（建议每年更新一次）

# 2024 年节假日
_CHINA_HOLIDAYS_2024 = {
    datetime(2024, 1, 1),  # 元旦
    datetime(2024, 2, 10), datetime(2024, 2, 11), datetime(2024, 2, 12),  # 春节
    datetime(2024, 2, 13), datetime(2024, 2, 14), datetime(2024, 2, 15), datetime(2024, 2, 16), datetime(2024, 2, 17),
    datetime(2024, 4, 4), datetime(2024, 4, 5), datetime(2024, 4, 6),  # 清明
    datetime(2024, 5, 1), datetime(2024, 5, 2), datetime(2024, 5, 3),  # 劳动节
    datetime(2024, 6, 10),  # 端午节
    datetime(2024, 9, 15), datetime(2024, 9, 16), datetime(2024, 9, 17),  # 中秋节
    datetime(2024, 10, 1), datetime(2024, 10, 2), datetime(2024, 10, 3), datetime(2024, 10, 4),
    datetime(2024, 10, 5), datetime(2024, 10, 6), datetime(2024, 10, 7),  # 国庆节
}

# 2025 年节假日
_CHINA_HOLIDAYS_2025 = {
    datetime(2025, 1, 1),  # 元旦
    datetime(2025, 1, 28), datetime(2025, 1, 29), datetime(2025, 1, 30),  # 春节
    datetime(2025, 1, 31), datetime(2025, 2, 1), datetime(2025, 2, 2), datetime(2025, 2, 3), datetime(2025, 2, 4),
    datetime(2025, 4, 4), datetime(2025, 4, 5), datetime(2025, 4, 6),  # 清明
    datetime(2025, 5, 1), datetime(2025, 5, 2), datetime(2025, 5, 3),  # 劳动节
    datetime(2025, 5, 31),  # 端午节
    datetime(2025, 10, 1), datetime(2025, 10, 2), datetime(2025, 10, 3),  # 国庆节
    datetime(2025, 10, 4), datetime(2025, 10, 5), datetime(2025, 10, 6), datetime(2025, 10, 7),
    datetime(2025, 10, 8),
}

# 2026 年节假日
_CHINA_HOLIDAYS_2026 = {
    datetime(2026, 1, 1), datetime(2026, 1, 2), datetime(2026, 1, 3),  # 元旦
    datetime(2026, 2, 16), datetime(2026, 2, 17), datetime(2026, 2, 18),  # 春节
    datetime(2026, 2, 19), datetime(2026, 2, 20), datetime(2026, 2, 21), datetime(2026, 2, 22), datetime(2026, 2, 23),
    datetime(2026, 4, 3), datetime(2026, 4, 4), datetime(2026, 4, 5),  # 清明
    datetime(2026, 5, 1), datetime(2026, 5, 2), datetime(2026, 5, 3),  # 劳动节
    datetime(2026, 6, 19), datetime(2026, 6, 20), datetime(2026, 6, 21),  # 端午节
    datetime(2026, 10, 1), datetime(2026, 10, 2), datetime(2026, 10, 3),  # 国庆节
    datetime(2026, 10, 4), datetime(2026, 10, 5), datetime(2026, 10, 6), datetime(2026, 10, 7), datetime(2026, 10, 8),
}


def get_china_holidays(year: int) -> Set[datetime]:
    """
    获取指定年份的中国法定节假日集合

    Args:
        year: 年份（2024 / 2025 / 2026）

    Returns:
        日期集合（datetime 对象）

    使用示例：
        holidays = get_china_holidays(2024)
        if datetime(2024, 10, 1) in holidays:
            print("国庆节是节假日")
    """
    if year == 2024:
        return _CHINA_HOLIDAYS_2024
    elif year == 2025:
        return _CHINA_HOLIDAYS_2025
    elif year == 2026:
        return _CHINA_HOLIDAYS_2026
    else:
        return set()  # 其他年份返回空集合


def get_current_time() -> datetime:
    """
    获取当前北京时间

    使用 Asia/Shanghai 时区，确保时间是北京时间而非 UTC。

    Returns:
        datetime 对象（北京时间）

    使用示例：
        now = get_current_time()
        print(f"现在是 {now}")
    """
    tz = pytz.timezone("Asia/Shanghai")  # 北京时区
    return datetime.now(tz)


def get_current_date_str() -> str:
    """
    获取当前日期字符串

    Returns:
        日期字符串，格式 YYYYMMDD，如 "20240421"

    使用示例：
        today = get_current_date_str()  # "20240421"
    """
    return get_current_time().strftime("%Y%m%d")


def get_trading_date_str(days_offset: int = 0) -> str:
    """
    获取最近交易日字符串

    用于计算 N 个交易日前/后的日期。

    Args:
        days_offset: 向后偏移天数
            - 0 = 今天
            - -1 = 昨天
            - 1 = 明天
            - -5 = 5 个交易日前

    Returns:
        交易日字符串（YYYYMMDD）

    使用示例：
        yesterday = get_trading_date_str(-1)   # 昨天的交易日
        next_week = get_trading_date_str(5)   # 5 个交易日后的日期
    """
    today = get_current_time()
    target_date = today + timedelta(days=days_offset)

    # 循环查找最近的交易日（向前或向后最多 10 天）
    for _ in range(10):
        if is_trading_day(target_date):
            return target_date.strftime("%Y%m%d")
        # 向后偏移时用 +1，向前偏移时用 -1
        target_date += timedelta(days=-1 if days_offset <= 0 else 1)

    # 兜底：返回今天的日期字符串
    return today.strftime("%Y%m%d")


def is_trading_day(check_date: datetime = None) -> bool:
    """
    判断指定日期是否为交易日

    交易日的判断条件：
    1. 不是周末（周六、周日）
    2. 不是法定节假日
    3. 如果是今天，时间需要 >= 15:00（收盘后）或直接返回 True（盘中也是交易日）

    Args:
        check_date: 待检查的日期，None 表示今天

    Returns:
        True = 是交易日，False = 不是交易日

    使用示例：
        if is_trading_day():
            print("今天可以交易")
        if is_trading_day(datetime(2024, 10, 1)):
            print("国庆节不是交易日")
    """
    if check_date is None:
        check_date = get_current_time()

    # 去除时间部分，只保留日期
    check_date = check_date.replace(hour=0, minute=0, second=0, microsecond=0)

    # ── 检查1：周末 ─────────────────────────────────────────────────────
    # weekday(): Monday=0, Saturday=5, Sunday=6
    if check_date.weekday() >= 5:
        return False  # 周六周日不是交易日

    # ── 检查2：法定节假日 ───────────────────────────────────────────────
    year = check_date.year
    holidays = get_china_holidays(year)
    if check_date in holidays:
        return False  # 法定节假日不是交易日

    # ── 检查3：今天的时间（可选）────────────────────────────────────────
    # 如果是今天且未到 15:00，理论上还不算收盘，
    # 但为了简化，这里直接返回 True（盘中也是交易日）
    today = get_current_time().replace(hour=0, minute=0, second=0, microsecond=0)
    if check_date == today:
        # 盘中时间也视为交易日
        pass

    return True


def is_trading_time() -> bool:
    """
    判断当前是否为交易时间

    A 股交易时间：
    - 上午：9:30 - 11:30
    - 下午：13:00 - 15:00

    Returns:
        True = 在交易时间内，False = 不在交易时间内

    使用示例：
        if is_trading_time():
            print("现在正在交易")
    """
    now = get_current_time()

    # 先检查是否是交易日
    if not is_trading_day(now):
        return False

    hour = now.hour
    minute = now.minute

    # ── 上午交易时间：9:30 - 11:30 ──────────────────────────────────────
    # 条件：hour == 9 and minute >= 30，或者 hour > 9 and hour < 11
    morning_start = (hour == 9 and minute >= 30) or (hour > 9 and hour < 11)
    # 条件：hour == 11 and minute <= 30
    morning_end = hour == 11 and minute <= 30

    # ── 下午交易时间：13:00 - 15:00 ──────────────────────────────────────
    # 条件：hour >= 13 and hour < 15
    afternoon_start = hour >= 13 and hour < 15

    return morning_start or morning_end or afternoon_start


def get_trading_days(start_date: str, end_date: str) -> List[str]:
    """
    获取两个日期之间的所有交易日

    用于计算时间段内的交易日数量，或生成交易日列表。

    Args:
        start_date: 开始日期（YYYYMMDD），如 "20240101"
        end_date: 结束日期（YYYYMMDD），如 "20240420"

    Returns:
        交易日列表，每项为 YYYYMMDD 字符串

    使用示例：
        days = get_trading_days("20240101", "20240420")
        print(f"共有 {len(days)} 个交易日")
    """
    start = datetime.strptime(start_date, "%Y%m%d")  # 解析开始日期
    end = datetime.strptime(end_date, "%Y%m%d")    # 解析结束日期

    trading_days = []
    current = start

    # 遍历日期区间，收集所有交易日
    while current <= end:
        if is_trading_day(current):
            trading_days.append(current.strftime("%Y%m%d"))
        current += timedelta(days=1)  # 下一天

    return trading_days


def get_next_trading_day(from_date: datetime = None) -> str:
    """
    获取指定日期之后的下一个交易日

    用于计算下一个交易日（如用于定时任务的调度）。

    Args:
        from_date: 参考日期，None 表示今天

    Returns:
        下一个交易日的字符串（YYYYMMDD）

    使用示例：
        next_day = get_next_trading_day()  # 下一个交易日
        next_mon = get_next_trading_day(datetime(2024, 10, 4))  # 国庆后第一个交易日
    """
    if from_date is None:
        from_date = get_current_time()

    next_day = from_date + timedelta(days=1)  # 从明天开始找

    # 最多向前/后找 15 天
    for _ in range(15):
        if is_trading_day(next_day):
            return next_day.strftime("%Y%m%d")
        next_day += timedelta(days=1)

    # 兜底返回
    return next_day.strftime("%Y%m%d")