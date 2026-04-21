"""
通知推送模块

支持多渠道通知发送：
- 飞书（FeishuNotifier）
- Server酱（ServerchanNotifier）- 微信推送
- 钉钉（DingtalkNotifier）
- 控制台（ConsoleNotifier）

使用示例：
    from src.notification import get_notification_hub

    hub = get_notification_hub()
    hub.send(content="报告内容", title="股票分析", channels=["serverchan"])
"""

from src.notification.notifier import NotificationHub, get_notification_hub

__all__ = ["NotificationHub", "get_notification_hub"]