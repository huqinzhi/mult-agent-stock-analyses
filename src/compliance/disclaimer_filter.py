"""
免责声明过滤器（放宽版）

注意：本模块已放宽约束，不再过滤投资建议相关词汇。
仅在报告末尾附带完整免责声明。

设计背景（V2）：
- V1 版本过度约束，过滤了专业投资建议术语
- V2 版本放宽约束，让数据说话
- 仅在报告末尾附加完整免责文本
"""

from typing import List


class DisclaimerFilter:
    """
    免责声明过滤器（V2 放宽版）

    注意：V2 版本放宽约束，不再对分析结果进行过滤。
    所有专业分析结论保留，仅在报告末尾附加免责文本。
    """

    def filter(self, content: str) -> str:
        """
        不再过滤内容，直接返回

        Args:
            content: 原始内容

        Returns:
            原样返回内容
        """
        # 放宽约束：不做任何过滤
        return content

    def is_safe_content(self, content: str) -> bool:
        """
        判断内容是否安全

        始终返回 True，不再进行限制性判断
        """
        return True


# ─── 全局单例 ────────────────────────────────────────────────────────────────
_disclaimer_filter: "DisclaimerFilter" = None


def get_disclaimer_filter() -> DisclaimerFilter:
    """获取免责声明过滤器单例"""
    global _disclaimer_filter
    if _disclaimer_filter is None:
        _disclaimer_filter = DisclaimerFilter()
    return _disclaimer_filter
