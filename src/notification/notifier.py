"""
通知分发中心模块

管理多渠道通知发送，支持：
- 飞书（FeishuNotifier）：通过飞书 Webhook 推送消息
- Server酱（ServerchanNotifier）：通过 Server酱 推送到微信
- 钉钉（DingtalkNotifier）：通过钉钉 Webhook 推送消息
- 控制台（ConsoleNotifier）：输出到终端，始终可用

设计思路：
- NotificationHub 是通知分发中心，类似于一个多路分发器
- 根据配置的渠道，将同一份消息发送给多个接收端
- 支持指定发送到特定渠道，也支持发送到所有已配置渠道

使用示例：
    from src.notification import get_notification_hub

    # 获取通知中心单例
    hub = get_notification_hub()

    # 发送消息到所有已配置渠道
    hub.send(content="报告内容", title="股票分析")

    # 只发送到特定渠道
    hub.send(content="报告内容", channels=["serverchan", "feishu"])
"""

# ─── 标准库 ─────────────────────────────────────────────────────────────────
import logging  # 日志记录
from typing import Any, Dict, List, Optional  # 类型注解

# ─── 项目内部导入 ──────────────────────────────────────────────────────────────
from src import config  # 全局配置（包含各渠道的 Webhook URL 等）
from src.notification.console import ConsoleNotifier  # 控制台通知器
from src.notification.dingtalk import DingtalkNotifier  # 钉钉通知器
from src.notification.feishu import FeishuNotifier  # 飞书通知器
from src.notification.serverchan import ServerchanNotifier  # Server酱通知器

# 获取当前模块的日志记录器
logger = logging.getLogger(__name__)


class NotificationHub:
    """通知分发中心 - 管理多渠道通知发送

    核心职责：
    1. 初始化所有已配置的通知渠道
    2. 提供统一的 send 接口发送消息到指定渠道
    3. 返回各渠道的发送结果，供调用方参考

    设计模式：单例模式 + 工厂模式
    - 各渠道通知器在初始化时创建，类似工厂
    - 通过 get_notification_hub() 获取单例
    """

    def __init__(self):
        """初始化通知中心，自动检测并初始化已配置的通知渠道

        初始化流程：
        1. 创建一个空的 notifiers 字典
        2. 调用 _init_notifiers() 根据配置创建各渠道通知器
        """
        self._notifiers: Dict[str, Any] = {}  # 存储各渠道通知器实例
        self._init_notifiers()  # 根据配置初始化已启用的渠道

    def _init_notifiers(self):
        """初始化所有已配置的通知渠道

        初始化逻辑：
        - 检查 config 中的配置项是否已填写
        - 如果配置了（不为空），则创建对应的通知器实例
        - 控制台通知器始终创建，因为它是默认输出方式

        渠道优先级：
        1. 飞书 - 需要 FEISHU_WEBHOOK 配置
        2. Server酱 - 需要 SERVERCHAN_KEY 配置
        3. 钉钉 - 需要 DINGTALK_WEBHOOK 配置
        4. 控制台 - 始终可用
        """
        # ── 飞书渠道 ─────────────────────────────────────────────────────
        # 如果配置了飞书 Webhook，创建飞书通知器
        if config.FEISHU_WEBHOOK:
            self._notifiers["feishu"] = FeishuNotifier(config.FEISHU_WEBHOOK)

        # ── Server酱（微信推送）渠道 ─────────────────────────────────────
        # 如果配置了 Server酱 SendKey，创建 Server酱 通知器
        if config.SERVERCHAN_KEY:
            self._notifiers["serverchan"] = ServerchanNotifier(
                config.SERVERCHAN_KEY,  # SendKey
                app_key=config.SERVERCHAN_APP_KEY,  # AppKey（可选）
            )

        # ── 钉钉渠道 ─────────────────────────────────────────────────────
        # 如果配置了钉钉 Webhook，创建钉钉通知器
        if config.DINGTALK_WEBHOOK:
            self._notifiers["dingtalk"] = DingtalkNotifier(config.DINGTALK_WEBHOOK)

        # ── 控制台渠道 ─────────────────────────────────────────────────────
        # 控制台通知器始终创建，作为默认输出方式
        # 即使其他渠道都失败了，日志仍会输出到控制台
        self._notifiers["console"] = ConsoleNotifier()

    def send(
        self,
        content: str,
        title: Optional[str] = None,
        channels: Optional[List[str]] = None,
    ) -> Dict[str, bool]:
        """发送通知到指定渠道

        消息发送流程：
        1. 确定目标渠道列表（传入的 channels 或所有可用渠道）
        2. 遍历每个渠道，调用对应通知器的 send 方法
        3. 记录每个渠道的发送结果
        4. 返回所有渠道的发送结果汇总

        Args:
            content: 通知内容（消息正文）
            title: 通知标题（如"股票分析报告"）
            channels: 目标渠道列表，None 表示发送到所有可用渠道
                可选值：["feishu", "serverchan", "dingtalk", "console"]

        Returns:
            各渠道发送结果字典，格式：{渠道名: 是否成功}
            例如：{"feishu": True, "serverchan": False, "console": True}
        """
        # 如果未指定渠道，发送到所有已初始化的渠道
        if channels is None:
            channels = list(self._notifiers.keys())

        results = {}  # 存储各渠道发送结果

        # 遍历目标渠道列表
        for channel in channels:
            # 获取渠道对应的通知器实例
            notifier = self._notifiers.get(channel)
            if notifier is None:
                # 渠道不存在，记录警告并标记为失败
                logger.warning(f"未找到通知渠道: {channel}")
                results[channel] = False
                continue

            try:
                # 调用通知器的 send 方法发送消息
                result = notifier.send(content, title=title)
                results[channel] = result  # 记录发送结果
            except Exception as e:
                # 发送过程中出现异常，记录错误并标记为失败
                logger.error(f"通知渠道 {channel} 发送失败: {e}")
                results[channel] = False

        return results

    def list_channels(self) -> List[str]:
        """列出所有可用的通知渠道

        用于查询当前已配置和初始化的渠道列表。

        Returns:
            渠道名称列表，例如：["feishu", "serverchan", "console"]
        """
        return list(self._notifiers.keys())


# ─── 全局单例 ────────────────────────────────────────────────────────────────
# 使用全局变量确保 NotificationHub 在整个程序生命周期内只有一个实例
_hub: Optional[NotificationHub] = None


def get_notification_hub() -> NotificationHub:
    """获取通知中心单例

    使用延迟初始化模式：
    - 首次调用时创建 NotificationHub 实例
    - 后续调用直接返回已创建的实例

    Returns:
        NotificationHub 实例
    """
    global _hub  # 声明使用全局变量
    if _hub is None:  # 如果尚未创建实例
        _hub = NotificationHub()  # 创建新实例
    return _hub  # 返回单例实例
