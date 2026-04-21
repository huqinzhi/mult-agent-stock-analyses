"""
AKShare 数据工具封装模块

封装 AKShare 库，提供 A 股数据获取接口，支持：
- K线数据（历史行情）
- 资金流向（主力/超大单/大单/中单/小单）
- 北向资金（沪深港通）
- 板块资金流
- 财务指标
- 龙虎榜
- 融资融券

数据源优先级：curl直连 > 东方财富(akshare) > 腾讯

缓存机制：使用 @cached 装饰器缓存数据，避免重复请求。
缓存时间：K线 5 分钟，资金流 10 分钟，财务指标 1 小时。

使用示例：
    from src.tools import get_akshare_client

    akshare = get_akshare_client()
    df = akshare.get_historical_kline("000001.SZ", "20240101", "20240420")
"""

# ─── 标准库 ─────────────────────────────────────────────────────────────────
import json        # JSON 解析（用于 curl 获取 K线数据）
import os          # 文件路径操作
import subprocess  # 子进程调用（用于 curl 请求）

from datetime import datetime, timedelta  # 日期时间处理

from typing import Any, Dict, List, Optional, Tuple  # 类型注解

# ─── 第三方库 ─────────────────────────────────────────────────────────────────
import pandas as pd  # 数据处理（DataFrame）

# ─── 项目内部导入 ──────────────────────────────────────────────────────────────
import akshare as ak  # AKShare 库（A股数据获取）

from src.cache import cached, get_data_cache  # 缓存装饰器和缓存管理器


# ══════════════════════════════════════════════════════════════════════════════
# 数据质量评估
# ══════════════════════════════════════════════════════════════════════════════

class DataQualityMetrics:
    """
    数据质量指标评估工具

    用于评估数据源的可靠性，计算质量分数（0-1）。

    评估维度：
    - completeness（完整性）：数据缺失程度
    - timeliness（时效性）：数据的新鲜程度
    - consistency（一致性）：数据逻辑一致性
    """

    @staticmethod
    def assess_kline_quality(df: pd.DataFrame) -> Tuple[float, Dict[str, Any]]:
        """
        评估 K线数据质量

        检查项目：
        1. 列完整性：是否包含 open/high/low/close/volume
        2. 数据完整性：空值比例
        3. 数据一致性：收盘价是否在高低价之间
        4. 时效性：最新数据距今天数

        Args:
            df: K线 DataFrame

        Returns:
            (质量分数, 详细信息字典)
            - 质量分数：0-1，1 = 完美
            - 详细信息：包含 missing_columns、null_ratio 等
        """
        if df is None or df.empty:
            return 0.0, {"error": "数据为空"}

        details = {}
        score = 1.0  # 初始分数为 1.0，每发现一个问题扣分

        # ── 1. 检查列完整性 ───────────────────────────────────────────────
        required_cols = ["open", "high", "low", "close", "volume"]
        missing_cols = [c for c in required_cols if c not in df.columns]
        if missing_cols:
            score -= 0.3  # 缺少关键列，扣 0.3 分
            details["missing_columns"] = missing_cols

        # ── 2. 检查数据完整性（空值比例）────────────────────────────────────
        null_ratio = df[required_cols].isnull().sum().sum() / (len(df) * len(required_cols))
        if null_ratio > 0:
            score -= null_ratio * 0.3  # 空值越多扣分越多
            details["null_ratio"] = null_ratio

        # ── 3. 检查数据一致性（收盘价是否在高低价之间）────────────────────────
        if all(c in df.columns for c in ["high", "low", "close"]):
            # 找出收盘价 > 最高价 或 收盘价 < 最低价 的行
            invalid_close = ((df["close"] > df["high"]) | (df["close"] < df["low"])).sum()
            if invalid_close > 0:
                score -= min(0.2, invalid_close / len(df) * 0.5)
                details["invalid_close_ratio"] = invalid_close / len(df)

        # ── 4. 检查时效性（最新数据距今天数）────────────────────────────────
        date_col = "trade_date" if "trade_date" in df.columns else "date"
        if date_col in df.columns:
            try:
                latest_date = pd.to_datetime(df[date_col]).max()
                days_old = (datetime.now() - latest_date).days
                if days_old > 5:
                    score -= min(0.2, days_old / 30 * 0.2)  # 数据越老扣分越多
                    details["days_old"] = days_old
            except Exception:
                pass

        # 分数限制在 0-1 之间
        score = max(0.0, min(1.0, score))
        details["score"] = score
        return score, details

    @staticmethod
    def assess_money_flow_quality(df: pd.DataFrame) -> Tuple[float, Dict[str, Any]]:
        """
        评估资金流向数据质量

        Args:
            df: 资金流向 DataFrame

        Returns:
            (质量分数, 详细信息字典)
        """
        if df is None or df.empty:
            return 0.0, {"error": "数据为空"}

        details = {}
        score = 1.0

        if len(df) == 0:
            return 0.0, {"error": "无数据行"}

        # ── 检查资金流列是否存在 ─────────────────────────────────────────
        money_cols = ["close", "volume", "amount"]  # 收盘价、成交量、成交额
        for col in money_cols:
            if col not in df.columns:
                score -= 0.15
                details[f"missing_{col}"] = True

        # ── 检查空值 ─────────────────────────────────────────────────────
        null_ratio = df[money_cols].isnull().sum().sum() / (len(df) * len(money_cols))
        if null_ratio > 0:
            score -= null_ratio * 0.2
            details["null_ratio"] = null_ratio

        score = max(0.0, min(1.0, score))
        details["score"] = score
        return score, details

    @staticmethod
    def assess_general_quality(df: pd.DataFrame) -> Tuple[float, Dict[str, Any]]:
        """
        通用数据质量评估

        Args:
            df: 任意 DataFrame

        Returns:
            (质量分数, 详细信息字典)
        """
        if df is None or df.empty:
            return 0.0, {"error": "数据为空"}

        score = 1.0
        details = {}

        # 计算空值比例
        null_ratio = df.isnull().sum().sum() / (df.shape[0] * df.shape[1])
        if null_ratio > 0:
            score -= null_ratio * 0.3
            details["null_ratio"] = null_ratio

        score = max(0.0, min(1.0, score))
        details["score"] = score
        return score, details


# ══════════════════════════════════════════════════════════════════════════════
# 辅助函数
# ══════════════════════════════════════════════════════════════════════════════

def _fetch_kline_via_curl(
    ts_code: str,
    start_date: str,
    end_date: str,
    adjust: str = "qfq",
) -> Optional[pd.DataFrame]:
    """
    通过 curl 获取 K线数据（使用腾讯 API，绕过系统代理）

    在 AKShare 默认请求失败时尝试此方法：
    - 使用腾讯历史K线 API
    - 通过 --noproxy "*" 绕过系统代理（适用于某些网络环境）
    - 返回格式：["日期","开盘","收盘","最高","最低","成交量"]

    Args:
        ts_code: 股票代码（如 "600036.SH"）
        start_date: 开始日期（如 "20240101" 或 "2024-01-01"）
        end_date: 结束日期（如 "20240420" 或 "2024-04-20"）
        adjust: 复权类型（qfq=前复权/hfq=后复权/nofq=不复权）

    Returns:
        K线 DataFrame 或 None（获取失败时）
    """
    # 解析股票代码（"600036.SH" → market="sh", symbol="600036"）
    symbol = ts_code.split(".")[0]
    market = "sh" if ts_code.endswith(".SH") else "sz"
    qfq = "qfq" if adjust == "qfq" else ""

    # ── 日期格式转换：YYYYMMDD → YYYY-MM-DD ─────────────────────────────────
    def _normalize_date(d: str) -> str:
        if len(d) == 8 and d.isdigit():
            return f"{d[:4]}-{d[4:6]}-{d[6:8]}"
        return d  # 已经是 YYYY-MM-DD 格式则直接返回

    start_date = _normalize_date(start_date)
    end_date = _normalize_date(end_date)

    # ── 构建腾讯 API URL ────────────────────────────────────────────────────
    # 腾讯历史K线 API：https://web.ifzq.gtimg.cn/appstock/app/fqkline/get
    # 参数格式：_var=kline_dayqfq&param=sh600036,day,2024-01-01,2024-04-20,100,qfq
    url = f"https://web.ifzq.gtimg.cn/appstock/app/fqkline/get"
    params = f"_var=kline_day{qfq}&param={market}{symbol},day,{start_date},{end_date},100,{qfq}&r=0.1"

    # ── 构建 curl 命令 ─────────────────────────────────────────────────────
    # -s: 静默模式
    # --noproxy "*": 绕过系统代理（关键！某些网络需要这个）
    # -L: follow redirect
    # --connect-timeout 10: 连接超时 10 秒
    # -m 30: 最大等待时间 30 秒
    cmd = [
        "curl", "-s", "--noproxy", "*", "-L",
        "--connect-timeout", "10", "-m", "30",
        f"{url}?{params}",
    ]

    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=40)
        if result.returncode != 0 or not result.stdout:
            return None

        # ── 解析 JSON ─────────────────────────────────────────────────────────
        # 腾讯返回格式：var xxx = {...}
        text = result.stdout
        json_start = text.find("={")  # 找到 "={" 的位置
        if json_start == -1:
            return None
        json_str = text[json_start + 1:]  # 去掉 "var xxx =" 前缀

        data = json.loads(json_str)

        # 腾讯返回数据嵌套：data["sh600036"]["qfqday"] 或 data["sh600036"]["day"]
        klines = data.get("data", {}).get(f"{market}{symbol}", {}).get("qfqday", [])
        if not klines:
            # 尝试不含复权的数据
            klines = data.get("data", {}).get(f"{market}{symbol}", {}).get("day", [])

        if not klines:
            return None

        # ── 解析 K线数据 ─────────────────────────────────────────────────────
        # 腾讯返回格式：["日期","开盘","收盘","最高","最低","成交量"]
        records = []
        for item in klines:
            if isinstance(item, list) and len(item) >= 6:
                try:
                    records.append({
                        "trade_date": item[0],   # 日期
                        "open": float(item[1]),  # 开盘价
                        "close": float(item[2]), # 收盘价
                        "high": float(item[3]),  # 最高价
                        "low": float(item[4]),    # 最低价
                        "volume": float(item[5]), # 成交量
                    })
                except (ValueError, TypeError):
                    continue  # 跳过解析失败的行

        if records:
            df = pd.DataFrame(records)
            return df
    except Exception:
        pass

    return None


# ══════════════════════════════════════════════════════════════════════════════
# AKShare 客户端
# ══════════════════════════════════════════════════════════════════════════════

class AKShareClient:
    """
    AKShare 封装客户端

    提供统一的数据获取接口，支持：
    - 多数据源 fallback（curl直连 → 东方财富 → 腾讯）
    - 数据缓存（减少重复请求）
    - 数据质量评估

    使用示例：
        client = AKShareClient()
        df = client.get_historical_kline("000001.SZ", "20240101", "20240420")
        df, quality, details = client.get_historical_kline_with_quality(...)
    """

    def __init__(self, use_cache: bool = True):
        """
        初始化 AKShare 客户端

        Args:
            use_cache: 是否启用缓存（默认 True）
        """
        self.use_cache = use_cache

    @cached(max_age_seconds=300, key_prefix="akshare_kline_")  # K线缓存 5 分钟
    def get_historical_kline(
        self,
        ts_code: str,
        start_date: str,
        end_date: str,
        period: str = "daily",
        adjust: str = "qfq",
    ) -> pd.DataFrame:
        """
        获取 A股历史 K线数据（多数据源 fallback）

        数据源优先级：
        1. curl 直连腾讯 API（绕过系统代理）
        2. 东方财富（akshare 默认）
        3. 腾讯（akshare）

        Args:
            ts_code: 股票代码（如 "000001.SZ"）
            start_date: 开始日期（如 "20240101"）
            end_date: 结束日期（如 "20240420"）
            period: 周期（daily/weekly/monthly）
            adjust: 复权类型（qfq=前复权/hfq=后复权/nofq=不复权）

        Returns:
            K线 DataFrame，包含 open/high/low/close/volume 列

        Raises:
            RuntimeError: 所有数据源都失败时抛出
        """
        symbol = ts_code.split(".")[0]  # 去掉 .SZ/.SH
        errors = []

        # ── 数据源0: curl 直连（绕过系统代理）──────────────────────────────
        try:
            df = _fetch_kline_via_curl(ts_code, start_date, end_date, adjust)
            if df is not None and not df.empty:
                return df
        except Exception as e:
            errors.append(f"curl直连: {e}")

        # ── 数据源1: 东方财富（akshare 默认）───────────────────────────────
        try:
            df = ak.stock_zh_a_hist(
                symbol=symbol,
                period=period,
                start_date=start_date,
                end_date=end_date,
                adjust=adjust,
            )
            if df is not None and not df.empty:
                return df
        except Exception as e:
            errors.append(f"东方财富: {e}")

        # ── 数据源2: 腾讯（akshare）────────────────────────────────────────
        try:
            df = ak.stock_zh_a_hist_min_em(
                symbol=symbol,
                start_date=start_date,
                end_date=end_date,
                period="daily",
                adjust=adjust,
            )
            if df is not None and not df.empty:
                # 如果返回的是中文列名，转换为英文
                if "open" not in df.columns and "开盘" in df.columns:
                    df = df.rename(columns={
                        "开盘": "open", "最高": "high", "最低": "low",
                        "收盘": "close", "成交量": "volume", "日期": "date"
                    })
                return df
        except Exception as e:
            errors.append(f"腾讯: {e}")

        # 所有数据源都失败
        raise RuntimeError(f"获取K线数据失败: {ts_code}，已尝试所有数据源。错误: {'; '.join(errors)}")

    def get_historical_kline_with_quality(
        self,
        ts_code: str,
        start_date: str,
        end_date: str,
        **kwargs,
    ) -> Tuple[pd.DataFrame, float, Dict[str, Any]]:
        """
        获取 K线数据并附带质量指标

        这是 get_historical_kline 的增强版，同时返回数据质量评估。

        Args:
            ts_code: 股票代码
            start_date: 开始日期
            end_date: 结束日期
            **kwargs: 其他参数（传递给 get_historical_kline）

        Returns:
            (DataFrame, quality_score, quality_details)
            - DataFrame: K线数据
            - quality_score: 质量分数（0-1）
            - quality_details: 详细质量信息
        """
        df = self.get_historical_kline(ts_code, start_date, end_date, **kwargs)
        quality_score, quality_details = DataQualityMetrics.assess_kline_quality(df)
        return df, quality_score, quality_details

    @cached(max_age_seconds=300, key_prefix="akshare_quote_")  # 实时行情缓存 5 分钟
    def get_realtime_quote(self, ts_code: str) -> pd.DataFrame:
        """
        获取实时行情

        Args:
            ts_code: 股票代码

        Returns:
            实时行情 DataFrame

        Raises:
            RuntimeError: 获取失败时抛出
        """
        try:
            df = ak.stock_zh_a_spot_em()  # 获取所有 A 股实时行情
            return df[df["代码"] == ts_code.split(".")[0]]  # 筛选当前股票
        except Exception as e:
            raise RuntimeError(f"获取实时行情失败: {ts_code}, {e}")

    @cached(max_age_seconds=600, key_prefix="akshare_moneyflow_")  # 资金流缓存 10 分钟
    def get_money_flow(self, ts_code: str) -> pd.DataFrame:
        """
        获取资金流向数据（主力/超大单/大单/中单/小单）

        Args:
            ts_code: 股票代码

        Returns:
            资金流向 DataFrame

        Raises:
            RuntimeError: 获取失败时抛出
        """
        try:
            # stock_individual_fund_flow 需要传入纯数字代码和市场
            market = "sh" if ts_code.endswith(".SH") else "sz"
            df = ak.stock_individual_fund_flow(stock=ts_code.split(".")[0], market=market)
            return df
        except Exception as e:
            raise RuntimeError(f"获取资金流向失败: {ts_code}, {e}")

    @cached(max_age_seconds=600, key_prefix="akshare_north_")  # 北向资金缓存 10 分钟
    def get_north_money_flow(self, ts_code: str = None) -> pd.DataFrame:
        """
        获取北向资金数据

        Args:
            ts_code: 股票代码，不传则返回整体北向资金

        Returns:
            北向资金 DataFrame

        Raises:
            RuntimeError: 获取失败时抛出
        """
        try:
            if ts_code:
                # 单只股票的北向资金持股明细
                df = ak.stock_hsgt_north_hold_stock_em(symbol=ts_code.split(".")[0])
            else:
                # 整体北向资金流
                df = ak.stock_hsgt_global_money_flow_em()
            return df
        except Exception as e:
            raise RuntimeError(f"获取北向资金失败: {e}")

    @cached(max_age_seconds=600, key_prefix="akshare_sector_")  # 板块资金流缓存 10 分钟
    def get_sector_fund_flow(self) -> pd.DataFrame:
        """
        获取板块资金流向

        Returns:
            板块资金流 DataFrame，包含各行业板块的资金流入/流出

        Raises:
            RuntimeError: 获取失败时抛出
        """
        try:
            df = ak.stock_sector_fund_flow_rank(indicator="今日")
            return df
        except Exception as e:
            raise RuntimeError(f"获取板块资金流向失败: {e}")

    @cached(max_age_seconds=300, key_prefix="akshare_margin_")  # 融资融券缓存 5 分钟
    def get_margin_detail(
        self,
        ts_code: str,
        start_date: str,
        end_date: str,
    ) -> pd.DataFrame:
        """
        获取融资融券明细

        Args:
            ts_code: 股票代码
            start_date: 开始日期
            end_date: 结束日期

        Returns:
            融资融券明细 DataFrame

        Raises:
            RuntimeError: 获取失败时抛出
        """
        try:
            df = ak.stock_margin_detail(start_date=start_date, end_date=end_date)
            if ts_code:
                df = df[df["股票代码"] == ts_code.split(".")[0]]
            return df
        except Exception as e:
            raise RuntimeError(f"获取融资融券明细失败: {e}")

    @cached(max_age_seconds=3600, key_prefix="akshare_lhb_")  # 龙虎榜缓存 1 小时
    def get_lhb_detail(
        self,
        start_date: str,
        end_date: str,
    ) -> pd.DataFrame:
        """
        获取龙虎榜明细

        龙虎榜：每日涨幅/跌幅超过一定幅度的股票交易数据汇总。

        Args:
            start_date: 开始日期
            end_date: 结束日期

        Returns:
            龙虎榜明细 DataFrame

        Raises:
            RuntimeError: 获取失败时抛出
        """
        try:
            df = ak.stock_lhb_detail(start_date=start_date, end_date=end_date)
            return df
        except Exception as e:
            raise RuntimeError(f"获取龙虎榜明细失败: {e}")

    def get_stock_info(self, ts_code: str) -> Dict[str, Any]:
        """
        获取股票基本信息

        Args:
            ts_code: 股票代码

        Returns:
            股票信息字典，包含 code 和 name
        """
        try:
            df = ak.stock_info_a_code_name()  # 获取所有股票代码和名称
            info = df[df["code"] == ts_code.split(".")[0]]
            if info.empty:
                return {"code": ts_code, "name": "未知"}
            return {
                "code": info.iloc[0]["code"],
                "name": info.iloc[0]["name"],
            }
        except Exception:
            return {"code": ts_code, "name": "未知"}

    def get_industry_info(self, ts_code: str) -> Dict[str, str]:
        """
        获取所属行业信息

        Args:
            ts_code: 股票代码

        Returns:
            行业信息字典，包含 industry 和 code
        """
        try:
            # 获取行业板块列表
            df_board = ak.stock_board_industry_name_em()
            # 获取个股所属行业
            stock_board = ak.stock_board_industry_cons_em(symbol=ts_code.split(".")[0])
            if not stock_board.empty:
                return {
                    "industry": stock_board.iloc[0].get("板块名称", "未知"),
                    "code": ts_code,
                }
        except Exception:
            pass
        return {"industry": "未知", "code": ts_code}

    @cached(max_age_seconds=300, key_prefix="akshare_dailybasic_")  # 每日指标缓存 5 分钟
    def get_daily_basic(self, date: str) -> pd.DataFrame:
        """
        获取每日指标（PE、PB、市值等）

        Args:
            date: 日期（YYYYMMDD）

        Returns:
            每日指标 DataFrame

        Raises:
            RuntimeError: 获取失败时抛出
        """
        try:
            df = ak.stock_zh_a_daily(symbol="sh000001", start_date=date, end_date=date, adjust="qfq")
            return df
        except Exception as e:
            raise RuntimeError(f"获取每日指标失败: {e}")

    @cached(max_age_seconds=3600, key_prefix="akshare_finaindicator_")  # 财务指标缓存 1 小时
    def get_fina_indicator(
        self,
        ts_code: str,
        start_date: str,
        end_date: str,
    ) -> pd.DataFrame:
        """
        获取财务指标

        Args:
            ts_code: 股票代码
            start_date: 开始日期
            end_date: 结束日期

        Returns:
            财务指标 DataFrame

        Raises:
            RuntimeError: 获取失败时抛出
        """
        try:
            df = ak.stock_financial_analysis_indicator(
                symbol=ts_code,
                start_year=start_date[:4],  # 提取年份
                end_year=end_date[:4],
            )
            return df
        except Exception as e:
            raise RuntimeError(f"获取财务指标失败: {e}")

    def get_bak_basic(self, date: str) -> pd.DataFrame:
        """
        获取 bak 数据（行业对比用）

        Args:
            date: 日期

        Returns:
            bak 数据 DataFrame
        """
        try:
            df = ak.stock_zh_a_spot_em()
            return df
        except Exception as e:
            raise RuntimeError(f"获取 bak 数据失败: {e}")


# ══════════════════════════════════════════════════════════════════════════════
# 全局单例
# ══════════════════════════════════════════════════════════════════════════════

_akshare_client: Optional[AKShareClient] = None  # 模块级单例


def get_akshare_client() -> AKShareClient:
    """
    获取 AKShare 客户端单例

    使用单例模式避免重复创建客户端。

    Returns:
        AKShareClient 实例
    """
    global _akshare_client
    if _akshare_client is None:
        _akshare_client = AKShareClient()  # 首次调用时创建
    return _akshare_client