# src/compliance/mandatory_disclaimer.py
"""强制免责文本

所有输出必须附带完整免责，这是 P0 合规要求的最后一道防线。

设计背景：
- 根据监管要求，金融分析报告必须包含完整的法律免责
- DisclaimerFilter 过滤投资建议词是事前预防
- MandatoryDisclaimer 在报告末尾追加免责文本是事后保障
- 两者结合，确保报告既专业又合规

免责内容包括：
1. 明确声明不构成投资建议
2. 说明数据来源和局限性
3. 风险提示

使用方法：
    from src.compliance import MandatoryDisclaimer, DISCLAIMER_TEXT

    # 创建免责注入器实例
    injector = MandatoryDisclaimer()

    # 向分析报告注入免责文本
    full_report = injector.inject(analysis_content)

    # 获取纯免责文本
    disclaimer_only = injector.get_disclaimer_only()

    # 如果报告可能没有免责，可使用 inject_if_missing
    safe_report = injector.inject_if_missing(report)
"""

# ─── 免责文本 ────────────────────────────────────────────────────────────────
# 这是所有报告必须附带的完整免责文本
# 内容包括：投资建议免责声明、数据来源说明、风险提示
DISCLAIMER_TEXT = """
---
## 法律免责声明

**重要提示：**

1. 本分析报告仅供学习和研究参考，不构成任何投资建议或决策依据。
2. 本系统基于公开数据和 AI 模型进行分析，无法保证数据的准确性、完整性和及时性。
3. 股票投资具有风险，过去的业绩不代表未来的表现。
4. 投资者应根据自身风险承受能力自行判断，本系统不对任何投资损失承担责任。
5. 本系统不具备证券投资咨询资质，分析内容仅供参考。

**数据来源：**
- K线数据来源：AKShare（免费开源数据）
- 资讯数据来源：公开网络搜索
- 数据时效性：分析基于历史数据，无法预测未来走势

**风险提示：**
- 市场有风险，投资需谨慎
- 请勿将本分析结果作为实际投资依据
"""


class MandatoryDisclaimer:
    """强制免责注入器

    确保所有分析报告都附带完整免责文本。

    核心功能：
    1. inject() - 向内容追加免责文本
    2. get_disclaimer_only() - 获取纯免责文本
    3. inject_if_missing() - 如果内容没有免责才注入
    4. validate_has_disclaimer() - 验证内容是否包含完整免责
    """

    def __init__(self):
        """初始化免责注入器"""
        # 去除首尾空白，存储纯净的免责文本
        self._disclaimer = DISCLAIMER_TEXT.strip()

    def inject(self, content: str) -> str:
        """向内容注入免责文本

        在分析报告末尾追加完整的法律免责文本。

        Args:
            content: 分析报告内容（可能已包含其他内容）

        Returns:
            附带完整免责的报告，格式：原始内容 + 换行 + 免责文本

        示例：
            输入： "平安银行今日上涨 2%，技术面表现良好"
            输出： "平安银行今日上涨 2%，技术面表现良好\n\n---免责文本---"
        """
        # 处理空内容的边界情况
        if not content:
            content = ""  # 确保是空字符串而非 None

        # 格式：原始内容 + 两个换行 + 免责文本
        return f"{content.strip()}\n\n{self._disclaimer}"

    def get_disclaimer_only(self) -> str:
        """获取纯免责文本

        用于需要单独展示免责文本的场景。

        Returns:
            免责文本（不含前后空行）
        """
        return self._disclaimer

    def inject_if_missing(self, content: str) -> str:
        """如果内容中还没有免责，则注入

        用于处理可能已经包含免责的报告，避免重复注入。

        Args:
            content: 分析报告内容

        Returns:
            附带免责的报告（如果原本没有免责）

        判断逻辑：
        - 检查 self._disclaimer 是否在 content 中
        - 如果在，说明已有免责，直接返回原内容
        - 如果不在，调用 inject() 注入免责
        """
        # 如果免责文本已存在于内容中，直接返回原内容
        if self._disclaimer in content:
            return content
        # 否则注入免责
        return self.inject(content)

    def validate_has_disclaimer(self, content: str) -> bool:
        """验证内容是否包含完整免责

        用于在发布前检查报告是否符合合规要求。

        Args:
            content: 待验证内容

        Returns:
            True 如果包含完整免责文本的所有关键部分

        检查的关键部分：
        1. "本分析报告仅供学习和研究参考"
        2. "不构成任何投资建议"
        3. "不具备证券投资咨询资质"
        4. "市场有风险，投资需谨慎"

        只要缺少任何一个关键部分，就返回 False。
        """
        # 定义必须包含的关键免责条款
        required_parts = [
            "本分析报告仅供学习和研究参考",  # 明确用途
            "不构成任何投资建议",             # 核心免责
            "不具备证券投资咨询资质",          # 资质声明
            "市场有风险，投资需谨慎",          # 风险提示
        ]

        # 检查每个关键部分是否都存在
        for part in required_parts:
            if part not in content:
                # 缺少某个关键部分，返回 False
                return False
        # 所有关键部分都存在，返回 True
        return True


# ─── 全局默认实例 ────────────────────────────────────────────────────────────
# 提供一个预创建的单例，避免每次调用都创建新实例
_default_injector: MandatoryDisclaimer = None


def get_default_injector() -> MandatoryDisclaimer:
    """获取默认免责注入器

    提供一个预创建的全局单例实例。

    Returns:
        MandatoryDisclaimer 实例
    """
    global _default_injector  # 声明使用全局变量
    if _default_injector is None:  # 如果尚未创建
        _default_injector = MandatoryDisclaimer()  # 创建新实例
    return _default_injector  # 返回单例
