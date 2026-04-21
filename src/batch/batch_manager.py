"""
批量分析管理器模块

V1 版本说明：
- 当前 V1 版本暂不开放批量分析功能
- 批量分析接口已预留，将在 V2 版本开放

V2 预留功能（暂未启用）：
- 多股票并发分析，带并发控制
- 当股票数量超过阈值时，支持：
  - 路径2（批量全量）：直接分析全部股票
  - 路径3（批量精选）：先进行初筛，再分析 top_n*2 只候选股票
- 路径判断逻辑：
  - 股票数 <= top_n 阈值：不需要初筛，直接全量分析
  - top_n_enabled = True：路径3（初筛 + 详细分析）
  - top_n_enabled = False：路径2（批量全量）
"""

import logging
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, Dict, List, Optional

from src import config
from src.agents import create_prescreening_agent
from src.graph.builder import build_stock_analysis_graph
from src.graph.state import AgentState, StockQuery
from src.notification.notifier import get_notification_hub

logger = logging.getLogger(__name__)


class BatchAnalysisManager:
    """批量分析管理器

    V1 版本说明：
    - 当前版本暂不开放批量分析功能
    - 此类为 V2 预留接口，已实现完整功能逻辑

    V2 将支持三条执行路径：
    1. 单股分析：无 batch 参数，直接调用 analyze_single
    2. 批量全量：batch + top_n_disable=True，跳过初筛
    3. 批量精选：batch + top_n_disable=False，初筛后 top_n 分析
    """

    def __init__(self, max_concurrency: int = 3):
        """初始化

        Args:
            max_concurrency: 最大并发数
        """
        self.max_concurrency = max_concurrency
        self.results: List[Dict[str, Any]] = []

    def analyze_batch(
        self,
        stock_list: List[dict],
        notify_channels: List[str] = None,
        top_n: Optional[int] = None,
        top_n_enabled: Optional[bool] = None,
    ) -> List[Dict]:
        """批量分析（支持三条执行路径）

        Args:
            stock_list: 股票列表，每项包含 ts_code 和 name
            notify_channels: 通知渠道列表
            top_n: 保留前几名，None 表示使用配置默认值
            top_n_enabled: 是否启用前N名筛选，None 表示使用配置默认值

        Returns:
            分析结果列表
        """
        if not stock_list:
            logger.warning("股票列表为空")
            return []

        # 解析配置
        if top_n_enabled is None:
            top_n_enabled = config.BATCH_TOP_N_ENABLED
        if top_n is None:
            top_n = config.BATCH_TOP_N_COUNT

        # ─────────────────────────────────────────────────────────
        # 路径判断
        # ─────────────────────────────────────────────────────────
        use_prescreening = False
        candidates = stock_list

        if len(stock_list) <= top_n:
            # 股票数 <= 阈值，不需要初筛，直接全量分析
            logger.info(f"股票数量({len(stock_list)}) <= 阈值({top_n})，跳过初筛")
            use_prescreening = False
            candidates = stock_list
        elif top_n_enabled:
            # 路径3：初筛 + 详细分析
            logger.info(f"股票数量({len(stock_list)}) > 阈值({top_n})，启动初筛")
            use_prescreening = True
            candidates = self._run_prescreening(stock_list, top_n * 2)
        else:
            # 路径2：批量全量（跳过初筛）
            logger.info(f"top_n_enabled=False，使用批量全量路径")
            use_prescreening = False
            candidates = stock_list

        logger.info(
            f"执行路径：{'初筛+' if use_prescreening else ''}批量分析，"
            f"候选股票数: {len(candidates)}"
        )

        # ─────────────────────────────────────────────────────────
        # 详细分析
        # ─────────────────────────────────────────────────────────
        graph = build_stock_analysis_graph()

        results = []
        with ThreadPoolExecutor(max_workers=self.max_concurrency) as executor:
            futures = {
                executor.submit(
                    self._analyze_single,
                    stock,
                    graph,
                    notify_channels,
                ): stock
                for stock in candidates
            }

            for future in as_completed(futures):
                stock = futures[future]
                try:
                    result = future.result()
                    results.append(result)
                    logger.info(f"{stock['name']} 分析完成")
                except Exception as e:
                    logger.error(f"{stock['name']} 分析失败: {e}")
                    results.append({
                        "ts_code": stock["ts_code"],
                        "name": stock["name"],
                        "success": False,
                        "error": str(e),
                        "score": 0.0,
                        "report": None,
                    })

        self.results = results

        # 排序：按综合评分降序
        results_with_score = [r for r in results if r.get("success") and r.get("score", 0) > 0]
        results_with_score.sort(key=lambda x: x.get("score", 0), reverse=True)

        # ─────────────────────────────────────────────────────────
        # 输出筛选（路径3：批量精选）
        # ─────────────────────────────────────────────────────────
        if use_prescreening and len(results_with_score) > top_n:
            logger.info(f"精选路径，仅输出评分前{top_n}名")
            return results_with_score[:top_n]

        # 返回全部结果（已排序）
        return results_with_score if results_with_score else results

    def _run_prescreening(self, stock_list: List[dict], target_count: int) -> List[dict]:
        """执行初筛

        Args:
            stock_list: 候选股票列表
            target_count: 目标候选数量（top_n * 2）

        Returns:
            筛选后的候选股票列表
        """
        logger.info(f"开始初筛，输入 {len(stock_list)} 只股票，目标筛选 {target_count} 只")

        try:
            # 构建初筛 Agent
            prescreening_agent = create_prescreening_agent()

            # 初始化初筛状态
            state = AgentState(
                stock_list=stock_list,
                prescreening_target=target_count,
            )

            # 执行初筛节点
            prescreening_fn = prescreening_agent["prescreening"]
            state = prescreening_fn(state)

            # 获取候选股票
            candidates = getattr(state, "candidates", stock_list)
            prescreening_reason = getattr(state, "prescreening_reason", "")

            logger.info(f"初筛完成，候选股票 {len(candidates)} 只: {prescreening_reason}")

            # 返回候选股票列表
            return candidates

        except Exception as e:
            logger.error(f"初筛执行失败: {e}，使用原始股票列表")
            return stock_list

    def _analyze_single(
        self,
        stock: dict,
        graph,
        notify_channels: List[str],
    ) -> Dict[str, Any]:
        """分析单个股票

        Args:
            stock: 股票信息（包含 ts_code 和 name）
            graph: LangGraph 工作流
            notify_channels: 通知渠道

        Returns:
            分析结果，包含 ts_code/name/success/score/report
        """
        ts_code = stock["ts_code"]
        name = stock["name"]

        try:
            query = StockQuery(
                ts_code=ts_code,
                stock_name=name,
                query_type="comprehensive",
            )
            state = AgentState(
                query=query,
                messages=[],
                completed_tasks=[],
            )

            # 执行分析
            result = graph.invoke(state)
            final_report = result.get("final_report", "无报告")

            # 从报告中提取综合评分
            score = self._extract_score_from_report(final_report)

            # 发送通知（仅发送完整报告，不做筛选）
            if notify_channels:
                hub = get_notification_hub()
                hub.send(
                    content=final_report,
                    title=f"{name} 分析报告",
                    channels=notify_channels,
                )

            return {
                "ts_code": ts_code,
                "name": name,
                "success": True,
                "score": score,
                "report": final_report,
                "prescreening_reason": stock.get("reason", ""),
            }
        except Exception as e:
            logger.error(f"分析股票 {ts_code} 时出错: {e}")
            raise

    def _extract_score_from_report(self, report: str) -> float:
        """从分析报告中提取综合评分

        Args:
            report: 分析报告文本

        Returns:
            综合评分（0-100），如果无法提取则返回 0.0
        """
        if not report:
            return 0.0

        # 尝试匹配 "综合评分: XX/100" 或 "综合评分: XX" 等格式
        patterns = [
            r"综合评分[：:]\s*(\d+(?:\.\d+)?)\s*/\s*100",
            r"综合评分\s*[-:]\s*(\d+(?:\.\d+)?)",
            r"\*\*(?:综合评分|评分)\*\*[：:]\s*(\d+(?:\.\d+)?)",
            r"评分[:\s]+(\d+(?:\.\d+)?)\s*/\s*100",
        ]

        for pattern in patterns:
            match = re.search(pattern, report)
            if match:
                try:
                    return float(match.group(1))
                except (ValueError, IndexError):
                    continue

        # 无法提取评分
        logger.warning("无法从报告中提取综合评分")
        return 0.0
