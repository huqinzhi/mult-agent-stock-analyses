# src/compliance/disclaimer_filter.py
"""免责声明过滤器

核心功能：过滤所有投资建议，替换为中性分析描述
解决 P0 风险：不提供具体买卖建议

设计背景：
- 根据监管要求，金融分析报告不能包含具体的买卖建议
- 需要将"强烈买入"、"务必卖出"等煽动性词汇替换为中性描述
- 同时保留专业的投资建议术语（如"建议买入"、"止损位"等）

过滤原则：
1. 过滤极度危险的煽动性词汇（强烈、务必、无脑等）
2. 保留专业的投资建议术语
3. 将情绪化的表述替换为客观分析描述

使用方法：
    from src.compliance import get_disclaimer_filter

    disclaimer_filter = get_disclaimer_filter()
    filtered_content = disclaimer_filter.filter(raw_content)
"""

# ─── 标准库 ─────────────────────────────────────────────────────────────────
import re  # 正则表达式，用于模式匹配和替换
from typing import Dict, List, Optional  # 类型注解


class DisclaimerFilter:
    """免责声明过滤器

    过滤投资建议词，替换为中性分析描述

    核心工作流程：
    1. 初始化时编译所有正则表达式模式
    2. filter() 方法遍历所有模式，对匹配内容进行替换
    3. 支持提取原始建议、验证内容安全性等辅助功能
    """

    # 投资建议词 → 中性描述映射
    # 注意：保留专业的投资建议术语（建议买入、止损位等），只过滤高风险煽动性词汇
    # 格式：{正则表达式或关键词: 替换后的中性描述}
    RECOMMENDATION_REPLACEMENTS: Dict[str, str] = {
        # ══ 极度危险的煽动性买入词汇 - 这些需要过滤 ══════════════════════════
        # 这些词汇具有强烈的煽动性，会诱导投资者盲目操作
        # "强烈买入" → "建议谨慎买入"（保留"建议"，去掉"强烈"）
        r"强烈买入": "建议谨慎买入",      # 强烈 → 谨慎
        r"强烈建议买入": "建议谨慎买入",  # 强烈建议 → 建议谨慎
        r"极度买入": "建议谨慎买入",       # 极度 → 谨慎
        r"务必买入": "建议谨慎买入",       # 务必 → 建议谨慎
        r"建议立即买入": "建议谨慎买入",   # 立即 → 谨慎
        r"建议重仓买入": "建议控制仓位",   # 重仓 → 控制仓位
        r"满仓杀入": "建议控制仓位",       # 满仓杀入 → 控制仓位
        r"全仓杀入": "建议控制仓位",       # 全仓杀入 → 控制仓位
        r"重仓杀入": "建议控制仓位",       # 重仓杀入 → 控制仓位
        r"无脑买入": "建议理性分析",       # 无脑 → 理性分析
        r"盲目买入": "建议理性分析",       # 盲目 → 理性分析

        # ══ 预测性绝对词汇 - 过滤 ═══════════════════════════════════════════
        # 这些词汇暗示 100% 确定的结果，但股市没有 100% 确定的事情
        r"一定涨": "有上涨潜力",          # "一定"太绝对 → "有潜力"
        r"必然涨停": "有涨停可能",        # "必然"太绝对 → "有可能"
        r"必涨": "有上涨可能",            # "必"太绝对 → "有可能"
        r"保证赚钱": "有盈利可能",        # "保证"太绝对 → "有可能"

        # ══ 极度危险的煽动性卖出词汇 - 这些需要过滤 ══════════════════════════
        r"强烈卖出": "建议谨慎卖出",       # 强烈 → 谨慎
        r"强烈建议卖出": "建议谨慎卖出",   # 强烈建议 → 建议谨慎
        r"务必卖出": "建议谨慎卖出",       # 务必 → 建议谨慎
        r"建议立即卖出": "建议谨慎卖出",   # 立即 → 谨慎
        r"建议清仓": "建议逐步减仓",       # 清仓 → 逐步减仓（保留减仓操作建议）

        # ══ 风险相关词汇 - 保留专业术语，过滤过度煽动表达 ════════════════════
        # 这些词汇本身是客观的风险提示，但过度使用会煽动情绪
        # 所以保留专业术语，只替换过度夸张的表达
        r"高风险": "波动性较高",          # "高风险"暗示不要投 → "波动性较高"中性描述
        r"风险较高": "波动性较高",         # 同上
        r"低风险": "波动性较低",          # "低风险"暗示可以放心投 → "波动性较低"中性描述
        r"风险较低": "波动性较低",         # 同上
        r"风险提示": "注意事项",          # "风险提示"过于严肃 → "注意事项"较温和
        r"风险较大": "波动性较大",         # "风险较大"暗示危险 → "波动性较大"客观描述
        r"风险较小": "波动性较小",         # "风险较小"暗示安全 → "波动性较小"客观描述

        # ══ 操作建议类 - 保留专业术语，只过滤不当描述 ════════════════════════
        r"追涨杀跌": "关注价格突破和回落", # "追涨杀跌"是负面词汇 → 客观描述
    }

    def __init__(self):
        """初始化过滤器

        初始化时不会立即编译正则表达式，延迟到首次使用时编译
        """
        self._patterns: Optional[List[tuple]] = None  # 存储编译后的正则模式

    def _get_patterns(self) -> List[tuple]:
        """获取编译后的正则模式（延迟编译）

        为什么要延迟编译？
        - 正则表达式编译有性能开销
        - 如果过滤器创建后不使用，就不需要编译
        - 首次调用 filter 时才进行编译

        Returns:
            编译后的模式列表，格式：[(pattern, replacement), ...]
        """
        # 如果尚未编译，执行编译
        if self._patterns is None:
            self._patterns = [
                # 遍历所有替换规则，编译成正则表达式对象
                (re.compile(pattern), replacement)
                for pattern, replacement in self.RECOMMENDATION_REPLACEMENTS.items()
            ]
        return self._patterns

    def filter(self, content: str) -> str:
        """过滤投资建议词

        遍历所有预定义的模式，将匹配的内容替换为中性描述。

        Args:
            content: 原始分析内容（可能包含投资建议词）

        Returns:
            过滤后的中性分析内容（不含煽动性投资建议）

        工作流程：
        1. 空内容直接返回
        2. 遍历所有编译后的正则模式
        3. 对每个模式执行替换
        4. 返回替换后的内容
        """
        if not content:  # 空内容直接返回
            return content

        filtered = content  # 从原始内容开始

        # 遍历所有正则模式，执行替换
        for pattern, replacement in self._get_patterns():
            # re.sub() 替换所有匹配的内容
            filtered = pattern.sub(replacement, filtered)

        return filtered

    def extract_raw_recommendation(self, content: str) -> str:
        """提取原始建议（用于日志记录）

        在过滤前分析原始内容中的建议倾向，用于审计和分析。

        Args:
            content: 原始分析内容

        Returns:
            原始建议描述，如"强烈买入建议"、"观望/中性建议"等

        检测优先级：
        1. 强烈买入/强烈建议 → 强烈买入建议
        2. 强烈卖出/强烈看空 → 强烈卖出建议
        3. 买入/增持/建仓 → 买入/增持建议
        4. 卖出/减持/清仓 → 卖出/减持建议
        5. 观望/等待/中性 → 观望/中性建议
        6. 持有/继续持有 → 持有建议
        7. 包含"建议"但不满足上述 → 一般性建议
        8. 无匹配 → 未识别
        """
        if not content:  # 空内容返回"未识别"
            return "未识别"

        # 按优先级检测（使用 if-elif 链确保按优先级匹配）
        if "强烈买入" in content or "强烈建议" in content:
            return "强烈买入建议"
        elif "强烈卖出" in content or "强烈看空" in content:
            return "强烈卖出建议"
        elif "买入" in content or "增持" in content or "建仓" in content:
            return "买入/增持建议"
        elif "卖出" in content or "减持" in content or "清仓" in content:
            return "卖出/减持建议"
        elif "观望" in content or "等待" in content or "中性" in content:
            return "观望/中性建议"
        elif "持有" in content or "继续持有" in content:
            return "持有建议"
        elif "建议" in content:
            return "一般性建议"
        else:
            return "未识别"

    def is_safe_content(self, content: str) -> bool:
        """检查内容是否安全（不包含危险的投资建议）

        用于在发布前验证内容是否已经过适当过滤。

        Args:
            content: 待检查内容

        Returns:
            True 如果内容安全（不包含危险的投资建议）
            False 如果内容仍包含需要过滤的投资建议词

        检测逻辑：
        1. 检查是否包含危险关键词（买入、卖出等）
        2. 如果包含，进一步检查是否是已知的原始建议词
        3. 如果是原始建议词（未被替换），返回 False
        """
        if not content:  # 空内容默认安全
            return True

        # 定义危险关键词列表
        danger_keywords = [
            "买入", "卖出", "建仓", "清仓", "加仓", "减仓",
            "增持", "减持", "抄底", "逃顶", "追涨", "杀跌",
            "强烈买入", "强烈卖出", "建议买入", "建议卖出",
        ]

        # 遍历所有危险关键词
        for keyword in danger_keywords:
            if keyword in content:
                # 找到了关键词，需要进一步检查
                # 检查是否是替换后的中性词（中性词是安全的）
                for original, replacement in self.RECOMMENDATION_REPLACEMENTS.items():
                    # 如果关键词出现在原始建议词中
                    if keyword in original:
                        # 用正则检查原文是否匹配
                        if re.search(original, content):
                            # 匹配到原始建议词，说明未被替换，不安全
                            return False
                        break  # 找到了对应的替换规则，跳出内层循环

        return True  # 没有检测到危险的原始建议词，内容安全


# ─── 全局单例 ────────────────────────────────────────────────────────────────
_disclaimer_filter: Optional[DisclaimerFilter] = None  # 全局单例


def get_disclaimer_filter() -> DisclaimerFilter:
    """获取免责声明过滤器单例

    使用延迟初始化模式，确保只在首次使用时创建实例。

    Returns:
        DisclaimerFilter 单例实例
    """
    global _disclaimer_filter  # 声明使用全局变量
    if _disclaimer_filter is None:  # 如果尚未创建
        _disclaimer_filter = DisclaimerFilter()  # 创建新实例
    return _disclaimer_filter  # 返回单例
