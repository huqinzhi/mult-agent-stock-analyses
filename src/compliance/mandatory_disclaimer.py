"""
强制免责文本（V2 简化版）

所有输出必须附带完整免责，这是 P0 合规要求的最后一道防线。

V2 变更：
- 简化免责文本，突出核心免责条款
- 移除过于详细的数据来源说明
- 保持核心的法律免责要素
"""

# ─── 免责文本 ──────────────────────────────────────────────────────────────
MANDATORY_DISCLAIMER = """
【免责声明】
本报告仅供学习研究参考，不构成任何投资建议。

1. 本报告基于公开数据分析，观点和结论仅供参考，不构成任何买卖决策的依据。
2. 股票投资风险极高，过去业绩不代表未来表现。
3. 请务必独立判断，谨慎投资，如有损失概不负责。
4. 投资者应根据自身风险承受能力做出投资决策。

市场有风险，投资需谨慎。
"""


class MandatoryDisclaimer:
    """强制免责注入器"""

    def __init__(self):
        """初始化免责注入器"""
        self._disclaimer = MANDATORY_DISCLAIMER.strip()

    def inject(self, content: str) -> str:
        """向内容注入免责文本"""
        if not content:
            content = ""
        return f"{content.strip()}\n\n{MANDATORY_DISCLAIMER}"

    def get_disclaimer_only(self) -> str:
        """获取纯免责文本"""
        return self._disclaimer

    def inject_if_missing(self, content: str) -> str:
        """如果内容中还没有免责，则注入"""
        if self._disclaimer in content:
            return content
        return self.inject(content)


# ─── 全局默认实例 ────────────────────────────────────────────────────────────
_default_injector: MandatoryDisclaimer = None


def get_default_injector() -> MandatoryDisclaimer:
    """获取默认免责注入器"""
    global _default_injector
    if _default_injector is None:
        _default_injector = MandatoryDisclaimer()
    return _default_injector


def inject_disclaimer(report: str) -> str:
    """
    在报告末尾注入免责文本

    Args:
        report: 原始报告

    Returns:
        附带免责文本的报告
    """
    injector = get_default_injector()
    return injector.inject(report)
