"""
搜索工具模块（DuckDuckGo 联网搜索）

封装 DuckDuckGo 联网搜索功能，用于获取：
- 财经新闻（search_news）
- 网页搜索（search_web）
- 分析师评级（search_analyst_rating）
- 社交媒体情绪（search_social_sentiment）
- 公司公告（search_announcement）

使用 DuckDuckGo 无需 API Key，直接搜索。

搜索工具被以下 Agent 使用：
- intelligence_officer: 搜索宏观政策、行业动态
- sentiment_analyst: 搜索分析师评级、社交媒体讨论
"""

# ─── 标准库 ─────────────────────────────────────────────────────────────────
from datetime import datetime  # 日期时间（用于搜索结果的时间戳）
from typing import Any, Dict, List  # 类型注解

# ─── 第三方库 ─────────────────────────────────────────────────────────────────
from ddgs import DDGS  # DuckDuckGo 搜索库（pip install duckduckgo-search）


def search_news(keyword: str, max_results: int = 10) -> List[Dict[str, str]]:
    """
    搜索财经新闻

    通过 DuckDuckGo News 搜索新闻，返回标题、URL、日期、摘要。

    Args:
        keyword: 搜索关键词，如 "平安银行 000001"
        max_results: 最大返回结果数，默认 10 条

    Returns:
        新闻列表，每项包含：
        - title: 新闻标题
        - url: 新闻链接
        - date: 发布日期
        - snippet: 新闻摘要/正文

    使用示例：
        news = search_news("平安银行 000001", max_results=10)
        for item in news:
            print(f"{item['date']}: {item['title']}")
    """
    results = []
    try:
        # DDGS 是 DuckDuckGo 的同步封装，使用 with 语句管理连接
        with DDGS() as ddgs:
            # ddgs.news() 搜索新闻，返回 Generator
            search_results = ddgs.news(keyword, max_results=max_results)
            for item in search_results:
                results.append({
                    "title": item.get("title", ""),      # 新闻标题
                    "url": item.get("url", ""),          # 新闻链接
                    "date": item.get("date", ""),        # 发布日期
                    "snippet": item.get("body", ""),      # 新闻摘要
                })
    except Exception as e:
        # 搜索失败时返回空列表，不中断主流程
        # 网络问题、关键词问题等都可能导致失败
        pass
    return results


def search_web(keyword: str, max_results: int = 10) -> List[Dict[str, str]]:
    """
    网页搜索

    通过 DuckDuckGo 搜索网页，返回通用搜索结果。

    Args:
        keyword: 搜索关键词
        max_results: 最大返回结果数，默认 10 条

    Returns:
        网页列表，每项包含：
        - title: 网页标题
        - url: 网页链接
        - date: 日期（为空，网页搜索不返回日期）
        - snippet: 网页摘要
    """
    results = []
    try:
        with DDGS() as ddgs:
            # ddgs.text() 搜索网页，返回 Generator
            search_results = ddgs.text(keyword, max_results=max_results)
            for item in search_results:
                results.append({
                    "title": item.get("title", ""),
                    "url": item.get("href", ""),         # 网页链接（text 用 href）
                    "date": "",                          # 网页搜索不返回日期
                    "snippet": item.get("body", ""),
                })
    except Exception:
        pass
    return results


def search_analyst_rating(stock_name: str, max_results: int = 5) -> List[Dict[str, Any]]:
    """
    搜索分析师评级

    搜索券商研报、分析师评级、目标价调整等信息。

    Args:
        stock_name: 股票名称，如 "平安银行"
        max_results: 最大返回结果数，默认 5 条

    Returns:
        分析师评级列表，每项包含：
        - title: 研报标题
        - url: 研报链接
        - date: 日期
        - snippet: 研报摘要
        - type: "analyst_rating"（标记类型）

    使用示例：
        ratings = search_analyst_rating("平安银行")
        for r in ratings:
            print(f"{r['title']}: {r['snippet']}")
    """
    keyword = f"{stock_name} 分析师评级 研报"  # 构造搜索关键词
    results = []
    try:
        with DDGS() as ddgs:
            search_results = ddgs.text(keyword, max_results=max_results)
            for item in search_results:
                results.append({
                    "title": item.get("title", ""),
                    "url": item.get("href", ""),
                    "date": "",
                    "snippet": item.get("body", ""),
                    "type": "analyst_rating",  # 标记为分析师评级类型
                })
    except Exception:
        pass
    return results


def search_social_sentiment(stock_name: str, max_results: int = 20) -> List[Dict[str, str]]:
    """
    搜索社交媒体情绪（雪球、股吧等讨论）

    搜索社交媒体上关于股票的情绪和讨论，用于舆情分析。

    Args:
        stock_name: 股票名称，如 "平安银行"
        max_results: 最大返回结果数，默认 20 条（社交情绪需要更多样本）

    Returns:
        社交媒体讨论列表，每项包含：
        - title: 帖子标题
        - url: 帖子链接
        - date: 日期
        - snippet: 帖子内容摘要
        - type: "social_sentiment"（标记类型）

    情绪分析逻辑（见 sentiment_analyst.py）：
        - 看多关键词：看好、买入、推荐、利多、多头、上涨
        - 看空关键词：看空、卖出、减持、利空、空头、下跌、风险
    """
    keyword = f"{stock_name} 股吧 雪球 讨论"  # 构造搜索关键词
    results = []
    try:
        with DDGS() as ddgs:
            search_results = ddgs.text(keyword, max_results=max_results)
            for item in search_results:
                results.append({
                    "title": item.get("title", ""),
                    "url": item.get("href", ""),
                    "date": "",
                    "snippet": item.get("body", ""),
                    "type": "social_sentiment",  # 标记为社交情绪类型
                })
    except Exception:
        pass
    return results


def search_announcement(stock_name: str, max_results: int = 5) -> List[Dict[str, str]]:
    """
    搜索公司公告

    搜索股票相关的公告、业绩预告等信息。

    Args:
        stock_name: 股票名称，如 "平安银行"
        max_results: 最大返回结果数，默认 5 条

    Returns:
        公告列表，每项包含：
        - title: 公告标题
        - url: 公告链接
        - date: 日期
        - snippet: 公告摘要
        - type: "announcement"（标记类型）
    """
    keyword = f"{stock_name} 公告 业绩预告"  # 构造搜索关键词
    results = []
    try:
        with DDGS() as ddgs:
            search_results = ddgs.text(keyword, max_results=max_results)
            for item in search_results:
                results.append({
                    "title": item.get("title", ""),
                    "url": item.get("href", ""),
                    "date": "",
                    "snippet": item.get("body", ""),
                    "type": "announcement",  # 标记为公告类型
                })
    except Exception:
        pass
    return results