"""
系统入口模块 / CLI 入口

提供命令行界面，支持：
- 单股分析（默认）
- 批量分析（V2 预留）
- 定时调度（V2 预留）
- 股票池管理（stock list/add/remove/enable/disable）

使用示例：
    # 单股分析（V1 唯一支持的模式）
    python -m src.main --stock 000001.SZ --name 平安银行 --notify console

    # 股票池管理
    python -m src.main stock list
    python -m src.main stock add --code 000001.SZ --name 平安银行 --tags 银行

工作流程：
    1. 解析命令行参数
    2. 构建 LangGraph 工作流（build_stock_analysis_graph）
    3. 构建初始状态（AgentState + StockQuery）
    4. 流式执行工作流（graph.stream），实时打印 Agent 进度
    5. 分析完成后，通过 NotificationHub 推送报告到指定渠道
"""

import argparse  # 命令行参数解析
import logging    # 日志记录
import time       # 计时（统计分析耗时）

from src.batch.batch_manager import BatchAnalysisManager          # 批量分析管理器（V2）
from src.config.stock_pool import get_stock_pool                   # 股票池单例
from src.graph.builder import build_stock_analysis_graph           # 工作流构建器
from src.graph.state import AgentState, StockQuery                 # 状态定义
from src.notification.notifier import get_notification_hub         # 通知分发中心
from src.scheduler.stock_scheduler import start_scheduler           # 定时调度器（V2）
from src import config                                             # 全局配置


# 设置日志格式：时间 - 级别 - 消息，仅显示 WARNING 及以上
logging.basicConfig(level=logging.WARNING, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)


# ══════════════════════════════════════════════════════════════════════════════
# 股票池管理命令（stock 子命令）
# 这些函数处理 "python -m src.main stock list/add/remove/enable/disable"
# ══════════════════════════════════════════════════════════════════════════════

def cmd_stock_list(args):
    """股票池列表命令 - 查看所有已添加的股票"""
    pool = get_stock_pool()
    stocks = pool.list_stocks()

    if not stocks:
        print("股票池为空，请使用 'stock add' 添加股票")
        return

    # 格式化输出：显示序号、代码、名称、状态、标签
    print(f"\n股票池（共 {len(stocks)} 只）：")
    print("-" * 60)
    for s in stocks:
        status = "启用" if s.get("enabled", True) else "禁用"
        tags = ", ".join(s.get("tags", [])) or "-"
        print(f"  {s['name']} ({s['ts_code']}) | {status} | 标签: {tags}")
    print("-" * 60)


def cmd_stock_add(args):
    """添加股票命令 - 将股票添加到股票池（供批量分析和飞书命令匹配使用）"""
    pool = get_stock_pool()
    # args.tags 是列表，stock add --tags 银行 保险 会传入 ["银行", "保险"]
    tags = args.tags or []
    success = pool.add_stock(args.code, args.name, tags)
    if success:
        print(f"已添加: {args.name} ({args.code})")
    else:
        print(f"添加失败: {args.code} 已存在")


def cmd_stock_remove(args):
    """移除股票命令 - 从股票池中移除股票"""
    pool = get_stock_pool()
    success = pool.remove_stock(args.code)
    if success:
        print(f"已移除: {args.code}")
    else:
        print(f"移除失败: {args.code} 不存在")


def cmd_stock_enable(args):
    """启用股票命令 - 启用股票以便在调度时分析"""
    pool = get_stock_pool()
    success = pool.enable_stock(args.code)
    print(f"启用 {args.code}: {'成功' if success else '失败'}")


def cmd_stock_disable(args):
    """禁用股票命令 - 禁用股票以便在调度时跳过"""
    pool = get_stock_pool()
    success = pool.disable_stock(args.code)
    print(f"禁用 {args.code}: {'成功' if success else '失败'}")


# ══════════════════════════════════════════════════════════════════════════════
# 主入口函数
# ══════════════════════════════════════════════════════════════════════════════

def main():
    """
    主入口函数 - 解析命令行参数并执行相应操作

    参数解析流程：
        1. 创建主 parser
        2. 添加全局参数（--stock, --name, --notify 等）
        3. 添加 stock 子命令（list/add/remove/enable/disable）
        4. 解析后根据 cmd 执行对应逻辑
    """
    # ─── 1. 创建命令行解析器 ───────────────────────────────────────────────────
    parser = argparse.ArgumentParser(description="多智能体股票分析系统")

    # 添加子命令解析器，允许使用 subparsers.add_parser 管理子命令
    subparsers = parser.add_subparsers(dest="cmd", help="子命令")

    # ─── 2. 股票池管理子命令 ───────────────────────────────────────────────────
    stock_parser = subparsers.add_parser("stock", help="股票池管理")
    stock_subparsers = stock_parser.add_subparsers(dest="stock_cmd")

    # stock list：列出所有股票
    stock_subparsers.add_parser("list", help="查看股票列表")

    # stock add：添加股票到股票池
    add_parser = stock_subparsers.add_parser("add", help="添加股票")
    add_parser.add_argument("--code", required=True, help="股票代码（如 000001.SZ）")
    add_parser.add_argument("--name", required=True, help="股票名称")
    add_parser.add_argument("--tags", nargs="*", help="标签列表")

    # stock remove：移除股票
    remove_parser = stock_subparsers.add_parser("remove", help="移除股票")
    remove_parser.add_argument("--code", required=True, help="股票代码")

    # stock enable/disable：启用/禁用股票
    enable_parser = stock_subparsers.add_parser("enable", help="启用股票")
    enable_parser.add_argument("--code", required=True, help="股票代码")

    disable_parser = stock_subparsers.add_parser("disable", help="禁用股票")
    disable_parser.add_argument("--code", required=True, help="股票代码")

    # ─── 3. 分析参数（单股/批量/调度）───────────────────────────────────────────
    parser.add_argument("--stock", type=str, help="股票代码（如 000001.SZ）")
    parser.add_argument("--name", type=str, help="股票名称")
    parser.add_argument("--notify", type=str, default="console",
                        help="通知渠道：console/serverchan/feishu/dingtalk")
    parser.add_argument("--weight-mode", type=str, choices=["fixed", "auto"],
                        default=config.WEIGHT_MODE,
                        help="权重模式：fixed=固定权重(默认), auto=Supervisor动态分配")
    parser.add_argument("--schedule", action="store_true", help="启动定时调度模式（V2）")
    parser.add_argument("--batch", action="store_true", help="批量分析模式（V2 预留）")
    parser.add_argument("--top-n", type=int, default=None, help="批量分析时保留的前几名数量（V2）")
    parser.add_argument("--top-n-disable", action="store_true", help="关闭批量分析前N名筛选（V2）")

    # ─── 4. 解析参数 ─────────────────────────────────────────────────────────
    args = parser.parse_args()

    # ─── 5. 处理 stock 子命令 ─────────────────────────────────────────────────
    # 如果用户输入 "python -m src.main stock list"，args.cmd == "stock"
    # args.stock_cmd == "list"，执行 cmd_stock_list
    if args.cmd == "stock":
        if args.stock_cmd == "list":
            cmd_stock_list(args)
        elif args.stock_cmd == "add":
            cmd_stock_add(args)
        elif args.stock_cmd == "remove":
            cmd_stock_remove(args)
        elif args.stock_cmd == "enable":
            cmd_stock_enable(args)
        elif args.stock_cmd == "disable":
            cmd_stock_disable(args)
        else:
            stock_parser.print_help()
        return

    # ─── 6. 定时调度模式 ─────────────────────────────────────────────────────
    if args.schedule:
        logger.info("启动定时调度模式")
        # notify_channels=None 表示使用配置中的默认渠道
        notify_channels = [args.notify] if args.notify != "console" else None
        start_scheduler(notify_channels=notify_channels)
        return

    # ─── 7. 批量分析模式（V1 暂不开放）──────────────────────────────────────────
    if args.batch:
        logger.warning("批量分析功能 V1 版本暂不开放，敬请期待 V2")
        print("\n" + "=" * 60)
        print("⚠️  批量分析功能 V1 版本暂不开放")
        print("   当前版本仅支持单个股票分析")
        print("   批量分析功能正在开发中，将在 V2 版本开放")
        print("=" * 60 + "\n")
        return

    # ─── 8. 单股分析模式（默认）────────────────────────────────────────────────
    # 从参数获取股票代码和名称，默认值是平安银行
    ts_code = args.stock or "000001.SZ"
    name = args.name or ts_code

    print(f"\n{'='*60}")
    print(f"开始分析: {name} ({ts_code}) [权重模式: {args.weight_mode}]")
    print(f"{'='*60}\n")

    # ─── 9. 构建 LangGraph 工作流 ──────────────────────────────────────────────
    # build_stock_analysis_graph 创建编译好的工作流图
    # enable_checkpoints=False 禁用断点恢复（简化流程）
    graph = build_stock_analysis_graph(weight_mode=args.weight_mode, enable_checkpoints=False)

    # ─── 10. 构建初始状态 ─────────────────────────────────────────────────────
    # StockQuery 包含股票代码、名称、日期范围（默认近90日）
    # AgentState 是整个工作流的共享状态
    query = StockQuery(
        ts_code=ts_code,
        stock_name=name,
        query_type="comprehensive",
    )
    state = AgentState(
        query=query,
        messages=[],        # LangGraph 的消息列表（用于 add_messages）
        completed_tasks=[], # 记录哪些 Agent 已完成
    )

    # 配置字典，用于 LangGraph 的 thread_id（类似会话ID）
    config_dict = {"configurable": {"thread_id": f"stock_analysis_{ts_code}"}}

    print("📊 [Supervisor] 协调 6 个 Agent 并行分析中...\n")

    # ─── 11. 流式执行工作流 ────────────────────────────────────────────────────
    # graph.stream(state) 会逐个返回事件，每个事件 = {node_name: node_state}
    # 我们监听每个 Agent 的完成状态，实时打印进度
    final_report = None
    agent_completed = set()  # 跟踪已完成的 Agent，避免重复输出
    supervisor_done = False
    start_time = time.time()  # 记录开始时间，用于计算总耗时

    for event in graph.stream(state, config=config_dict):
        """
        event 格式：{"supervisor": AgentState} 或 {"quantitative": AgentState} 等
        每次迭代可能是：
        - supervisor 节点执行（设置 routing_target 或生成报告）
        - 某个 Agent 节点执行（写入自己的结果）
        """
        for node_name, node_state in event.items():
            # 从 event 中提取信息（兼容 AgentState 对象和 dict）
            if isinstance(node_state, dict):
                # Send API 返回的是字典，用 .get() 获取值
                final_report_val = node_state.get("final_report")
                routing_target = node_state.get("routing_target")
                completed_tasks = node_state.get("completed_tasks", [])
            else:
                # AgentState 对象，用 getattr 获取
                final_report_val = getattr(node_state, "final_report", None)
                routing_target = getattr(node_state, "routing_target", None)
                completed_tasks = getattr(node_state, "completed_tasks", [])

            # ── 处理 6 个 Agent 节点 ──────────────────────────────────────────
            if node_name in ["quantitative", "chart", "intelligence", "risk", "fundamental", "sentiment"]:
                # 把结果写入 state（因为 graph.stream 是生成器，state 不会自动更新）
                result = node_state.get(f"{node_name}_result") if isinstance(node_state, dict) else getattr(node_state, f"{node_name}_result", None)
                if result:
                    setattr(state, f"{node_name}_result", result)

                # 更新已完成任务列表
                if completed_tasks:
                    for task in completed_tasks:
                        if task not in state.completed_tasks:
                            state.completed_tasks.append(task)

                # 打印 Agent 完成状态
                agent_names = {
                    "quantitative": "量化分析师",
                    "chart": "图表分析师",
                    "intelligence": "情报官",
                    "risk": "风险评估师",
                    "fundamental": "基本面分析师",
                    "sentiment": "舆情监控师",
                }

                result = getattr(state, f"{node_name}_result", None)
                is_completed = node_name in completed_tasks

                if result and is_completed:
                    if node_name not in agent_completed:
                        agent_completed.add(node_name)
                        score = getattr(result, 'score', None)
                        score_str = f"{score:.0f}" if score else "N/A"
                        print(f"  ✅ [{agent_names.get(node_name, node_name)}] 完成 - 评分: {score_str}/100")
                else:
                    if node_name not in agent_completed:
                        print(f"  🔄 [{agent_names.get(node_name, node_name)}] 分析中...")

            # ── 处理 Supervisor 节点 ────────────────────────────────────────────
            elif node_name == "supervisor":
                if final_report_val:
                    # 报告已生成（第二次执行完成）
                    final_report = final_report_val
                    print(f"\n✅ [Supervisor] 分析完成！报告长度: {len(final_report)}")
                    supervisor_done = True
                elif routing_target == "parallel":
                    # 正在分发任务到 6 个 Agent
                    print(f"📤 [Supervisor] 正在分发任务到 6 个 Agent...")

    # ─── 12. 备用逻辑：stream 结束后检查报告 ──────────────────────────────────
    # 如果 stream 结束但没拿到 final_report，尝试手动生成
    if final_report is None:
        state_final_report = getattr(state, "final_report", None)
        if state_final_report:
            final_report = state_final_report
        else:
            # 检查是否所有结果都已就绪（理论上 stream 结束后都有了）
            required_results = [
                ("quantitative", "quantitative_result"),
                ("chart", "chart_result"),
                ("intelligence", "intelligence_result"),
                ("risk", "risk_result"),
                ("fundamental", "fundamental_result"),
                ("sentiment", "sentiment_result"),
            ]
            all_have_results = all(getattr(state, r, None) is not None for _, r in required_results)
            if all_have_results:
                # 手动调用 Supervisor 生成报告
                from src.agents.supervisor import create_supervisor
                sup = create_supervisor(model=config.MINIMAX_MODEL, weight_mode=args.weight_mode)
                state = sup["supervisor_node"](state)
                if getattr(state, "final_report", None):
                    final_report = state.final_report

    # 兜底：如果还是没有报告
    if final_report is None:
        final_report = "分析失败，未生成报告"

    # ─── 13. 发送通知 ─────────────────────────────────────────────────────────
    elapsed = time.time() - start_time  # 计算总耗时

    if args.notify != "console":
        # 非控制台渠道：飞书/Server酱/钉钉
        hub = get_notification_hub()
        results = hub.send(
            content=final_report,
            title=f"{name} 分析报告",
            channels=[args.notify],
        )
        logger.info(f"通知发送结果: {results}")
    else:
        # 控制台输出：直接打印报告
        print("\n" + "=" * 60)
        print("📋 最终分析报告：")
        print("=" * 60)
        print(final_report)
        print("=" * 60)

    print(f"\n⏱️ 本次分析总耗时: {elapsed:.1f}秒")


if __name__ == "__main__":
    main()