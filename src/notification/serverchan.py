"""Server酱通知器（微信推送）"""

# ─── 标准库 ─────────────────────────────────────────────────────────────────
import logging  # 日志记录
from typing import Optional  # 可选类型注解

# ─── 第三方库 ─────────────────────────────────────────────────────────────────
import httpx  # HTTP 客户端库，用于发送 HTTP 请求

# 获取当前模块的日志记录器
logger = logging.getLogger(__name__)


class ServerchanNotifier:
    """Server酱（微信推送）通知器

    Server酱是一项微信消息推送服务，通过 SendKey 将消息推送到微信。
    文档: https://sct.ftqq.com/

    使用流程：
    1. 在 Server酱官网注册并获取 SendKey
    2. 绑定微信接收消息
    3. 通过 API 发送消息到微信
    """

    def __init__(self, sendkey: str, app_key: str = ""):
        """初始化 Server酱 通知器

        Args:
            sendkey: Server酱 SendKey（用于标识发送者）
            app_key: Server酱 AppKey（可选，用于接口升级）
        """
        self.sendkey = sendkey  # 保存 SendKey
        self.app_key = app_key  # 保存 AppKey
        # 构造 API 请求地址，格式：https://sctapi.ftqq.com/{sendkey}.send
        self.api_url = f"https://sctapi.ftqq.com/{sendkey}.send"

    def send(self, content: str, title: Optional[str] = None) -> bool:
        """发送 Server酱 消息到微信

        通过 HTTP POST 请求将消息推送到 Server酱 API，再由 Server酱转发到微信。

        Args:
            content: 消息正文内容（支持 Markdown）
            title: 消息标题，默认为"股票分析报告"

        Returns:
            是否发送成功（True=成功，False=失败）
        """
        # 如果没有指定标题，使用默认标题
        if title is None:
            title = "股票分析报告"

        try:
            # 构建请求 payload
            # Server酱 API 接收 title（标题）和 desp（正文）两个参数
            payload = {
                "title": title,   # 消息标题
                "desp": content,  # 消息正文，支持多行文本
            }
            # 如果配置了 app_key，添加到 payload 中（接口升级需要）
            if self.app_key:
                payload["appkey"] = self.app_key

            # 使用 httpx 发送 POST 请求
            # timeout=15 设置 15 秒超时，避免请求长时间阻塞
            with httpx.Client(timeout=15) as client:
                # POST 请求到 Server酱 API
                response = client.post(self.api_url, data=payload)
                # 检查 HTTP 状态码，如果非 2xx 则抛出异常
                response.raise_for_status()
                # 解析响应 JSON
                result = response.json()
                # Server酱返回 {"code": 0, "message": "success"} 表示成功
                # code != 0 表示发送失败
                return result.get("code", -1) == 0

        except Exception as e:
            # 捕获所有异常（网络错误、超时、JSON 解析错误等）
            logger.error(f"Server酱通知发送失败: {e}")
            return False
