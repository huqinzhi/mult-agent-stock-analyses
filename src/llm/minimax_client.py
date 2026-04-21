"""
MiniMax API 客户端封装模块

提供与 MiniMax 大模型的交互接口：
- 同步聊天（chat）
- 流式聊天（chat_stream）
- 快捷方法（chat_with_system）

使用示例：
    from src.llm import get_minimax_client

    client = get_minimax_client()
    response = client.chat([
        {"role": "system", "content": "你是一个助手"},
        {"role": "user", "content": "你好"}
    ])
    content = response["choices"][0]["message"]["content"]
"""

# ─── 标准库 ───────────────────────────────────────────────────────────────────
import os  # 读取环境变量（MINIMAX_API_KEY 等）

from typing import Any, Dict, Generator, List  # 类型注解

# ─── 第三方库 ─────────────────────────────────────────────────────────────────
import httpx  # HTTP 客户端，用于发送请求到 MiniMax API

from dotenv import load_dotenv  # 加载 .env 环境变量文件

load_dotenv()  # 自动读取项目根目录的 .env 文件

from src import config  # 导入全局配置（API_KEY, BASE_URL, MODEL）


class MiniMaxClient:
    """
    MiniMax API 客户端

    封装与 MiniMax 大模型的 HTTP 请求，支持同步/流式调用。
    """

    def __init__(
        self,
        api_key: str = None,
        base_url: str = None,
        model: str = "MiniMax-Text-01",
        timeout: float = 120.0,
    ):
        """
        初始化 MiniMax 客户端

        Args:
            api_key: API 密钥，不传则从环境变量 MINIMAX_API_KEY 读取
            base_url: API 地址，不传则从环境变量 MINIMAX_BASE_URL 读取
            model: 模型名称，默认为 MiniMax-Text-01
            timeout: 请求超时时间（秒），默认 120 秒（LLM 生成较慢）
        """
        # 优先使用传入参数，其次使用环境变量，最后用默认值
        self.api_key = api_key or os.getenv("MINIMAX_API_KEY", "")
        self.base_url = base_url or os.getenv("MINIMAX_BASE_URL", "https://api.minimax.chat/v1")
        self.model = model
        self.timeout = timeout

        # 如果没有 API_KEY，抛出明确的错误（避免后续请求时困惑）
        if not self.api_key:
            raise ValueError("MiniMax API key 未设置，请设置 MINIMAX_API_KEY 环境变量或传入 api_key 参数")

    def chat(
        self,
        messages: List[Dict[str, str]],
        temperature: float = 0.7,
        max_tokens: int = 4096,
        **kwargs,
    ) -> Dict[str, Any]:
        """
        发送同步聊天请求

        Args:
            messages: 消息列表，格式为 [{"role": "system/user", "content": "..."}]
            temperature: 温度参数，控制随机性（0-1）
                - 0.7 适合一般对话
                - 0.3 适合确定性任务（如分析）
                - 0.9 适合创意写作
            max_tokens: 最大生成 token 数（控制回复长度）
            **kwargs: 其他 API 参数（如 top_p, stop 等）

        Returns:
            API 响应字典，包含 choices[0].message.content

        请求流程：
            1. 构建 URL: base_url + /text/chatcompletion_v2
            2. 构建 Header: Authorization: Bearer {api_key}
            3. 构建 Body: model, messages, temperature, max_tokens
            4. 发送 POST 请求
            5. 解析 JSON 响应
        """
        # 拼接完整的 API 端点
        url = f"{self.base_url}/text/chatcompletion_v2"

        # 构建 HTTP Header
        # Authorization 使用 Bearer Token 认证方式
        headers = {
            "Authorization": f"Bearer {self.api_key}",  # Bearer {API_KEY}
            "Content-Type": "application/json",          # JSON 格式请求体
        }

        # 构建请求体（payload）
        payload = {
            "model": self.model,                # 模型名称
            "messages": messages,               # 对话历史
            "temperature": temperature,         # 随机性控制
            "max_tokens": max_tokens,           # 最大生成长度
            **kwargs,                           # 允许传入额外参数（如 top_p）
        }

        # 发送 HTTP POST 请求
        # timeout=120 表示最多等待 120 秒（LLM 生成可能较慢）
        with httpx.Client(timeout=self.timeout) as client:
            response = client.post(url, json=payload, headers=headers)
            response.raise_for_status()  # 如果状态码 >= 400，抛出异常
            return response.json()       # 解析 JSON 响应

    def chat_stream(
        self,
        messages: List[Dict[str, str]],
        temperature: float = 0.7,
        max_tokens: int = 4096,
        **kwargs,
    ) -> Generator[str, None, None]:
        """
        发送流式聊天请求（Server-Sent Events）

        Args:
            messages: 消息列表
            temperature: 温度参数
            max_tokens: 最大 token 数
            **kwargs: 其他参数

        Yields:
            生成的文本片段（逐块返回，用于实时显示）

        与 chat() 的区别：
            - chat() 等待完整响应后一次性返回
            - chat_stream() 使用流式响应，边生成边返回

        返回格式示例：
            data: {"choices": [{"delta": {"content": "你好"}}]}
            data: {"choices": [{"delta": {"content": "，"}}]}
            ...
            data: [DONE]
        """
        url = f"{self.base_url}/text/chatcompletion_v2"
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "stream": True,  # 开启流式响应
            **kwargs,
        }

        # stream=True 使响应变为 SSE（Server-Sent Events）格式
        with httpx.Client(timeout=self.timeout) as client:
            with client.stream("POST", url, json=payload, headers=headers) as response:
                response.raise_for_status()
                # 逐行读取响应
                for line in response.iter_lines():
                    if line.startswith("data: "):
                        data = line[6:]  # 去掉 "data: " 前缀
                        if data == "[DONE]":  # 流式结束标记
                            break
                        import json
                        try:
                            # 解析 SSE 数据
                            chunk = json.loads(data)
                            # 提取增量内容（delta.content）
                            delta = chunk.get("choices", [{}])[0].get("delta", {})
                            if delta.get("content"):
                                yield delta["content"]  # 产出文本片段
                        except json.JSONDecodeError:
                            continue

    def chat_with_system(
        self,
        system_prompt: str,
        user_prompt: str,
        temperature: float = 0.7,
        max_tokens: int = 4096,
    ) -> str:
        """
        便捷方法：带系统提示的对话

        适用于简单的单轮对话场景。

        Args:
            system_prompt: 系统提示词（定义 AI 的角色/行为）
            user_prompt: 用户输入
            temperature: 温度参数
            max_tokens: 最大 token 数

        Returns:
            生成的文本内容（直接是字符串，不是字典）

        使用示例：
            client = get_minimax_client()
            content = client.chat_with_system(
                system_prompt="你是一个专业的股票分析师",
                user_prompt="分析一下平安银行的技术面"
            )
        """
        # 构建消息列表：系统提示 + 用户输入
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ]
        response = self.chat(messages, temperature, max_tokens)
        return response["choices"][0]["message"]["content"]


# ══════════════════════════════════════════════════════════════════════════════
# 全局单例
# ══════════════════════════════════════════════════════════════════════════════

_minimax_client: MiniMaxClient = None  # 模块级单例，初始为 None


def get_minimax_client() -> MiniMaxClient:
    """
    获取 MiniMax 客户端单例

    使用单例模式避免重复创建客户端（每次创建都需要重新建立 HTTP 连接）。

    线程安全说明：
        严格来说有轻微竞争，但首次调用后 _minimax_client 不为 None
        后续调用只读不写，实际使用中无问题。

    Returns:
        MiniMaxClient 实例
    """
    global _minimax_client  # 声明使用全局变量
    if _minimax_client is None:  # 首次调用时创建
        _minimax_client = MiniMaxClient(
            api_key=config.MINIMAX_API_KEY,      # 从全局配置读取
            base_url=config.MINIMAX_BASE_URL,
            model=config.MINIMAX_MODEL,
        )
    return _minimax_client