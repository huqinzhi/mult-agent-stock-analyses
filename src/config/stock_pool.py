"""股票池配置管理

支持 JSON 文件持久化 + CLI 管理，用于 V2 批量分析和定时调度功能。

设计背景：
- V1 只支持单股分析，股票代码通过命令行参数传入
- V2 需要批量分析和定时调度，需要一个股票池来管理多个股票
- 股票池存储在 JSON 文件中，支持增删改查操作

股票池数据结构：
{
    "version": "1.0",
    "updated_at": "2024-04-21T10:00:00",
    "stocks": [
        {
            "ts_code": "000001.SZ",
            "name": "平安银行",
            "tags": ["银行", "蓝筹"],
            "enabled": true,
            "added_at": "2024-04-21"
        }
    ]
}

使用示例：
    from src.config import get_stock_pool

    # 获取股票池单例
    pool = get_stock_pool()

    # 列出所有股票
    stocks = pool.list_stocks()

    # 添加股票
    pool.add_stock("000001.SZ", "平安银行", tags=["银行"])

    # 启用/禁用股票
    pool.enable_stock("000001.SZ")
    pool.disable_stock("600036.SH")

    # 获取已启用的股票（供调度器使用）
    enabled_stocks = pool.get_enabled_stocks()
"""

# ─── 标准库 ─────────────────────────────────────────────────────────────────
import json  # JSON 文件读写
import logging  # 日志记录
import os  # 操作系统（用于路径处理）
from datetime import datetime  # 日期时间（用于记录更新时间）
from typing import List, Optional  # 类型注解

# 获取当前模块的日志记录器
logger = logging.getLogger(__name__)


class StockPool:
    """股票池管理器

    核心功能：
    1. 从 JSON 文件加载股票池配置
    2. 支持添加、删除、启用、禁用股票
    3. 保存配置到 JSON 文件
    4. 提供 CLI 友好的接口

    持久化：所有变更自动保存到 JSON 文件
    单例：通过 get_stock_pool() 获取实例
    """

    def __init__(self, config_path: str = None):
        """初始化股票池

        Args:
            config_path: 配置文件路径，None 表示使用默认路径
                默认路径：{当前工作目录}/stocks.json
        """
        # 保存配置文件路径
        self.config_path = config_path or self._default_config_path()
        # 加载股票池数据
        self._data = self._load()

    def _default_config_path(self) -> str:
        """获取默认配置文件路径

        Returns:
            默认路径：{当前工作目录}/stocks.json
        """
        return os.path.join(os.getcwd(), "stocks.json")

    def _load(self) -> dict:
        """从 JSON 文件加载股票池配置

        Returns:
            股票池数据字典

        错误处理：
        - 如果文件不存在，返回空配置
        - 如果 JSON 解析失败或 IO 错误，记录错误并返回空配置
        """
        # 检查文件是否存在
        if not os.path.exists(self.config_path):
            # 不存在则创建空配置
            return self._empty_config()

        try:
            # 打开文件并读取 JSON 数据
            with open(self.config_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError) as e:
            # JSON 解析错误或 IO 错误
            logger.error(f"加载股票池配置失败: {e}，将使用空配置")
            return self._empty_config()

    def _empty_config(self) -> dict:
        """返回空配置结构

        Returns:
            默认的空股票池配置
        """
        return {
            "version": "1.0",  # 配置版本
            "updated_at": datetime.now().isoformat(),  # 更新时间
            "stocks": [],  # 股票列表（初始为空）
        }

    def save(self):
        """保存配置到 JSON 文件

        每次添加、删除、启用/禁用股票后自动调用。
        """
        # 更新保存时间
        self._data["updated_at"] = datetime.now().isoformat()
        try:
            # 写入 JSON 文件
            # ensure_ascii=False: 保留中文字符
            # indent=2: 格式化输出，便于阅读
            with open(self.config_path, "w", encoding="utf-8") as f:
                json.dump(self._data, f, ensure_ascii=False, indent=2)
            logger.info(f"股票池已保存到 {self.config_path}")
        except IOError as e:
            logger.error(f"保存股票池配置失败: {e}")

    def list_stocks(self, enabled_only: bool = False) -> List[dict]:
        """列出股票

        Args:
            enabled_only: 是否仅返回已启用的股票
                - False: 返回所有股票
                - True: 只返回 enabled=True 的股票

        Returns:
            股票列表，每项为包含股票信息的字典
        """
        stocks = self._data.get("stocks", [])  # 获取股票列表
        if enabled_only:
            # 过滤出已启用的股票
            return [s for s in stocks if s.get("enabled", True)]
        return stocks

    def add_stock(self, ts_code: str, name: str, tags: List[str] = None) -> bool:
        """添加股票到股票池

        Args:
            ts_code: 股票代码，格式："000001.SZ" 或 "600036.SH"
            name: 股票名称，如："平安银行"
            tags: 标签列表，如：["银行", "蓝筹"]（可选）

        Returns:
            是否成功
                - True: 添加成功
                - False: 添加失败（股票已存在）

        注意：
        - 如果股票已存在，不会重复添加，返回 False
        - 添加后自动保存到文件
        """
        stocks = self._data.get("stocks", [])  # 获取股票列表

        # ── 检查是否已存在 ───────────────────────────────────────────────
        for stock in stocks:
            if stock["ts_code"] == ts_code:
                # 股票已存在，记录警告并返回失败
                logger.warning(f"股票 {ts_code} 已存在于股票池")
                return False

        # ── 创建股票条目 ────────────────────────────────────────────────
        stock = {
            "ts_code": ts_code,           # 股票代码
            "name": name,                  # 股票名称
            "tags": tags or [],           # 标签（默认为空列表）
            "enabled": True,               # 默认启用
            "added_at": datetime.now().strftime("%Y-%m-%d"),  # 添加日期
        }
        stocks.append(stock)  # 添加到列表
        self._data["stocks"] = stocks  # 更新数据
        self.save()  # 保存到文件
        logger.info(f"已添加股票: {name} ({ts_code})")
        return True

    def remove_stock(self, ts_code: str) -> bool:
        """从股票池移除股票

        Args:
            ts_code: 股票代码

        Returns:
            是否成功
                - True: 移除成功
                - False: 移除失败（股票不存在）

        注意：
        - 如果股票不存在，不会报错，只返回 False
        - 移除后自动保存到文件
        """
        stocks = self._data.get("stocks", [])  # 获取股票列表
        original_len = len(stocks)  # 记录原始数量

        # 过滤掉要删除的股票（列表推导式）
        stocks = [s for s in stocks if s["ts_code"] != ts_code]

        # 检查是否真的删除了（数量变化）
        if len(stocks) == original_len:
            logger.warning(f"股票 {ts_code} 不存在于股票池")
            return False

        self._data["stocks"] = stocks  # 更新数据
        self.save()  # 保存到文件
        logger.info(f"已移除股票: {ts_code}")
        return True

    def enable_stock(self, ts_code: str) -> bool:
        """启用股票

        启用后的股票会参与定时调度和批量分析。

        Args:
            ts_code: 股票代码

        Returns:
            是否成功
        """
        return self._set_enabled(ts_code, True)

    def disable_stock(self, ts_code: str) -> bool:
        """禁用股票（定时调度时跳过）

        禁用的股票不会参与定时调度和批量分析，但会保留在股票池中。

        Args:
            ts_code: 股票代码

        Returns:
            是否成功
        """
        return self._set_enabled(ts_code, False)

    def _set_enabled(self, ts_code: str, enabled: bool) -> bool:
        """设置股票启用状态

        Args:
            ts_code: 股票代码
            enabled: 是否启用（True=启用，False=禁用）

        Returns:
            是否成功
        """
        stocks = self._data.get("stocks", [])  # 获取股票列表

        # 遍历查找目标股票
        for stock in stocks:
            if stock["ts_code"] == ts_code:
                # 找到股票，更新启用状态
                stock["enabled"] = enabled
                self.save()  # 保存到文件
                status = "启用" if enabled else "禁用"
                logger.info(f"股票 {ts_code} 已{status}")
                return True

        # 股票不存在
        logger.warning(f"股票 {ts_code} 不存在于股票池")
        return False

    def get_enabled_stocks(self) -> List[dict]:
        """获取所有已启用的股票（供调度器使用）

        Returns:
            已启用股票列表
        """
        return self.list_stocks(enabled_only=True)


# ─── 全局单例 ────────────────────────────────────────────────────────────────
_stock_pool: Optional[StockPool] = None  # 全局单例


def get_stock_pool() -> StockPool:
    """获取股票池单例

    延迟初始化：首次调用时创建实例。

    Returns:
        StockPool 单例实例
    """
    global _stock_pool  # 声明使用全局变量
    if _stock_pool is None:  # 如果尚未创建
        _stock_pool = StockPool()  # 创建新实例
    return _stock_pool  # 返回单例
