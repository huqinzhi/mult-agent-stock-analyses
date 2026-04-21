"""控制台通知器

将消息输出到终端控制台，作为默认的通知方式。
始终可用，不依赖任何外部服务。
"""

# ─── 标准库 ─────────────────────────────────────────────────────────────────
import logging  # 日志记录
from typing import Optional  # 可选类型注解

# 获取当前模块的日志记录器
logger = logging.getLogger(__name__)


class ConsoleNotifier:
    """控制台通知器（始终可用）

    将消息输出到终端的控制台。
    作为默认通知方式，当其他渠道都失败时，消息仍会输出到控制台。

    特点：
    - 无需配置，任何环境都可使用
    - 始终返回 True（不会失败）
    - 通过 Python logging 模块输出，支持日志格式化
    """

    def send(self, content: str, title: Optional[str] = None) -> bool:
        """输出到控制台

        Args:
            content: 通知内容
            title: 通知标题（会单独一行输出）

        Returns:
            是否成功（始终返回 True）
        """
        # 如果有标题，先输出标题行
        if title:
            logger.info(f"【{title}】")  # 输出格式：【标题】
        # 输出内容
        logger.info(content)
        # 控制台通知不会失败，始终返回 True
        return True
