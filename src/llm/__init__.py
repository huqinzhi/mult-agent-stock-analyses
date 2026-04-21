"""
LLM 客户端模块

封装 MiniMax 大模型的同步/流式调用接口。

使用示例：
    from src.llm import get_minimax_client

    client = get_minimax_client()
    response = client.chat(messages)
    content = response["choices"][0]["message"]["content"]
"""

from src.llm.minimax_client import MiniMaxClient, get_minimax_client

__all__ = ["MiniMaxClient", "get_minimax_client"]