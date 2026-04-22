"""
意图识别模块

根据用户输入识别意图类型，并提取相关实体（股票代码、名称等）。

意图类型：
- STOCK_ANALYSIS: 股票分析（指定股票）
- STOCK_SCREENING: 股票筛选（哪些股票...）
- STOCK_COMPARISON: 股票对比（对比...）
- INDUSTRY_ANALYSIS: 行业分析
- MACRO_ANALYSIS: 宏观分析
- RISK_ASSESSMENT: 风险评估
- CONSULTATION: 通用咨询
"""

import re
from typing import Tuple, Dict, Any, List

from src.graph.state import IntentType


# 意图关键词映射
INTENT_KEYWORDS = {
    IntentType.STOCK_ANALYSIS: [
        "分析", "看看", "怎么样", "好不好", "走势",
        "看一下", "查一下", "看看这只", "看看这支",
    ],
    IntentType.STOCK_SCREENING: [
        "哪些", "筛选", "找出", "哪些值得", "有什么好",
        "有什么推荐", "推荐一些", "值得关注", "哪个值得",
    ],
    IntentType.STOCK_COMPARISON: [
        "对比", "比较", "哪个好", "和", "vs", "versus",
        "差别", "区别", "差异", "哪一个更好",
    ],
    IntentType.INDUSTRY_ANALYSIS: [
        "行业", "板块", "产业",
        "行业分析", "板块分析", "产业分析",
    ],
    IntentType.MACRO_ANALYSIS: [
        "宏观", "经济", "政策", "央行", "利率",
        "宏观经济", "经济形势", "政策影响",
    ],
    IntentType.RISK_ASSESSMENT: [
        "风险", "止损", "风险评估", "风险分析",
        "有什么风险", "风险多大",
    ],
}

# 股票代码正则（6位数字，可选 .SZ/.SH 后缀）
STOCK_CODE_PATTERN = re.compile(r'\b(\d{6})(?:\.(SZ|SH))?\b')


def recognize_intent(user_input: str) -> Tuple[IntentType, Dict[str, Any]]:
    """
    识别用户意图

    Args:
        user_input: 用户输入文本

    Returns:
        (意图类型, 意图详情)
        意图详情包含：
        - stock_codes: 股票代码列表
        - stock_names: 股票名称列表
        - matched_keyword: 匹配的关键词
    """
    user_input_lower = user_input.lower().strip()

    if not user_input_lower:
        return IntentType.CONSULTATION, {
            "stock_codes": [],
            "stock_names": [],
            "matched_keyword": None,
        }

    # 提取股票代码
    stock_codes = extract_stock_codes(user_input)

    # 提取股票名称（简化实现）
    stock_names = extract_stock_names(user_input)

    # 意图匹配
    for intent_type, keywords in INTENT_KEYWORDS.items():
        for keyword in keywords:
            if keyword in user_input_lower:
                return intent_type, {
                    "stock_codes": stock_codes,
                    "stock_names": stock_names,
                    "matched_keyword": keyword,
                }

    # 默认返回股票分析（如果识别到股票代码）
    if stock_codes:
        return IntentType.STOCK_ANALYSIS, {
            "stock_codes": stock_codes,
            "stock_names": stock_names,
            "matched_keyword": None,
        }

    # 无法识别意图，返回通用咨询
    return IntentType.CONSULTATION, {
        "stock_codes": stock_codes,
        "stock_names": stock_names,
        "matched_keyword": None,
    }


def extract_stock_codes(text: str) -> List[str]:
    """
    从文本中提取股票代码

    Args:
        text: 原始文本

    Returns:
        股票代码列表（如 ["000001", "600036"]）

    示例：
        "000001" -> ["000001.SZ"]
        "600036.SH" -> ["600036.SH"]
        "帮我看看000001和平安银行" -> ["000001.SZ"]
    """
    matches = STOCK_CODE_PATTERN.findall(text)
    codes = []

    for number, suffix in matches:
        if suffix:
            # 已有后缀
            codes.append(f"{number}.{suffix}")
        else:
            # 自动判断后缀
            # 深圳: 000xxx / 300xxx / 001xxx
            # 上海: 600xxx / 601xxx / 688xxx / 900xxx
            if number.startswith(("000", "001", "002", "003", "300")):
                codes.append(f"{number}.SZ")
            elif number.startswith(("6", "9")):
                codes.append(f"{number}.SH")
            else:
                # 默认深圳
                codes.append(f"{number}.SZ")

    return codes


def extract_stock_names(text: str) -> List[str]:
    """
    从文本中提取股票名称

    这是一个简化实现，实际应该调用股票池或 AKShare 匹配。

    Args:
        text: 原始文本

    Returns:
        股票名称列表
    """
    # 常见银行股名称（硬编码示例）
    KNOWN_BANKS = {
        "平安银行": "000001.SZ",
        "招商银行": "600036.SH",
        "工商银行": "601398.SH",
        "建设银行": "601939.SH",
        "中国银行": "601988.SH",
        "农业银行": "601288.SH",
        "交通银行": "601328.SH",
        "兴业银行": "601166.SH",
    }

    names = []
    for name in KNOWN_BANKS.keys():
        if name in text:
            names.append(name)

    return names


def is_stock_query(user_input: str) -> bool:
    """
    判断是否为股票查询

    Args:
        user_input: 用户输入

    Returns:
        True 如果是股票查询
    """
    # 检查是否包含股票代码
    codes = extract_stock_codes(user_input)
    if codes:
        return True

    # 检查是否包含已知股票名称
    names = extract_stock_names(user_input)
    if names:
        return True

    return False
