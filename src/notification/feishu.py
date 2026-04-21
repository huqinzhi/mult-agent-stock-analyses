"""飞书 Webhook 通知器

通过飞书自定义机器人 Webhook 发送消息。
文档：https://open.feishu.cn/document/ukTMukTMukTM/ucTM5YjL3ETO24yNxkjN
"""

# ─── 标准库 ─────────────────────────────────────────────────────────────────
import logging  # 日志记录
from typing import Optional  # 可选类型注解

# ─── 第三方库 ─────────────────────────────────────────────────────────────────
import httpx  # HTTP 客户端库，用于发送 HTTP 请求

# 获取当前模块的日志记录器
logger = logging.getLogger(__name__)


class FeishuNotifier:
    """飞书 Webhook 通知器

    使用飞书自定义机器人 Webhook 推送消息。
    优点：配置简单，无需申请应用权限
    缺点：Webhook 是单向通信，无法获取消息接收状态

    消息类型支持：
    - text：文本消息
    - post：富文本消息
    - image：图片消息
    - interactive：卡片消息
    """

    def __init__(self, webhook_url: str):
        """初始化飞书通知器

        Args:
            webhook_url: 飞书自定义机器人的 Webhook 地址
                格式：https://open.feishu.cn/open-apis/bot/v2/hook/xxx
        """
        self.webhook_url = webhook_url  # 保存 Webhook 地址

    def send(self, content: str, title: Optional[str] = None) -> bool:
        """发送飞书消息

        通过 Webhook 发送文本消息到飞书群。

        Args:
            content: 消息内容（纯文本）
            title: 消息标题（可选，会加在内容前面）

        Returns:
            是否发送成功（True=成功，False=失败）

        注意：
        - 飞书 Webhook 消息有大小限制（最大 30KB）
        - 文本消息直接发送，不支持 Markdown 格式
        """
        try:
            # 构建飞书消息 payload
            # msg_type 指定消息类型为 text
            # content.text 是消息内容，如果提供了标题则拼接在前面
            payload = {
                "msg_type": "text",  # 消息类型：text（文本）
                "content": {
                    # 如果有标题则"标题\n内容"，否则直接内容
                    "text": f"{title}\n{content}" if title else content
                },
            }
            # 使用 httpx 发送 POST 请求
            # timeout=10 设置 10 秒超时
            with httpx.Client(timeout=10) as client:
                # POST 请求到飞书 Webhook 地址，JSON 格式
                response = client.post(self.webhook_url, json=payload)
                # 检查 HTTP 状态码
                response.raise_for_status()
                # 飞书 Webhook 成功返回 True（无明确返回内容）
                return True

        except Exception as e:
            # 捕获所有异常（网络错误、超时等）
            logger.error(f"飞书通知发送失败: {e}")
            return False
