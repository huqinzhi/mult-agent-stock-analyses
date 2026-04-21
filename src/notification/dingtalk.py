"""钉钉 Webhook 通知器

通过钉钉自定义机器人 Webhook 发送消息。
文档：https://developers.dingtalk.com/document/app/custom-robot-access
"""

# ─── 标准库 ─────────────────────────────────────────────────────────────────
import logging  # 日志记录
from typing import Optional  # 可选类型注解

# ─── 第三方库 ─────────────────────────────────────────────────────────────────
import httpx  # HTTP 客户端库，用于发送 HTTP 请求

# 获取当前模块的日志记录器
logger = logging.getLogger(__name__)


class DingtalkNotifier:
    """钉钉 Webhook 通知器

    使用钉钉自定义机器人 Webhook 推送消息。
    优点：支持 Markdown 格式，消息展示更丰富
    缺点：Webhook 是单向通信，无法获取消息接收状态

    消息类型支持：
    - text：文本消息
    - link：链接消息
    - markdown：Markdown 格式消息
    - actionCard：卡片消息
    """

    def __init__(self, webhook_url: str):
        """初始化钉钉通知器

        Args:
            webhook_url: 钉钉自定义机器人的 Webhook 地址
                格式：https://oapi.dingtalk.com/robot/send?access_token=xxx
        """
        self.webhook_url = webhook_url  # 保存 Webhook 地址

    def send(self, content: str, title: Optional[str] = None) -> bool:
        """发送钉钉消息

        通过 Webhook 发送文本消息到钉钉群。

        Args:
            content: 消息内容（纯文本）
            title: 消息标题（钉钉 text 类型不支持独立标题，放入内容中）

        Returns:
            是否发送成功（True=成功，False=失败）

        注意：
        - 钉钉 text 类型不支持标题，因此将标题拼接到内容最前面
        - Markdown 类型支持标题格式，但这里使用简单的 text 类型
        """
        try:
            # 构建钉钉消息 payload
            # msgtype 指定消息类型为 text
            # text.content 是消息内容，如果提供了标题则拼接在前面
            payload = {
                "msgtype": "text",  # 消息类型：text（文本）
                "text": {
                    # 如果有标题则"标题\n内容"，否则直接内容
                    "content": f"{title}\n{content}" if title else content
                },
            }
            # 使用 httpx 发送 POST 请求
            # timeout=10 设置 10 秒超时
            with httpx.Client(timeout=10) as client:
                # POST 请求到钉钉 Webhook 地址，JSON 格式
                response = client.post(self.webhook_url, json=payload)
                # 检查 HTTP 状态码
                response.raise_for_status()
                # 解析响应 JSON
                result = response.json()
                # 钉钉返回 errcode=0 表示成功
                return result.get("errcode", -1) == 0

        except Exception as e:
            # 捕获所有异常（网络错误、超时等）
            logger.error(f"钉钉通知发送失败: {e}")
            return False
