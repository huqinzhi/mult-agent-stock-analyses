"""
LangGraph 工作流构建器模块

构建多智能体股票分析工作流：
- Supervisor 作为入口节点，协调整个工作流
- 条件边通过 Send API 并行分发任务到 6 个子 Agent
- 各 Agent 完成后结果汇总回 Supervisor 生成最终报告

工作流程图：
    Supervisor（首次）→ 条件边判断 → routing_target="parallel" → Send API 并行分发
                                                                        ↓
                                              ┌──────────────────────────┤
                                              ↓                          ↓
                                         quantitative              chart
                                              ↓                          ↓
                                         risk                     fundamental
                                              ↓                          ↓
                                         intelligence              sentiment
                                              └──────────────────────────┤
                                                                        ↓
                                                              各 Agent 返回 Supervisor
                                                                        ↓
                                                              Supervisor（末次）→ END

使用示例：
    from src.graph.builder import build_stock_analysis_graph

    graph = build_stock_analysis_graph(weight_mode="auto")
    result = graph.invoke(initial_state)
"""

# ─── 引入 LangGraph 组件 ────────────────────────────────────────────────────
# MemorySaver: 检查点持久化（enable_checkpoints=True 时启用，可恢复中断的工作流）
# Send: 并行分发 API，允许同时触发多个节点
# END: 结束标记
# StateGraph: 状态图构建器
from langgraph.checkpoint.memory import MemorySaver
from langgraph.constants import Send
from langgraph.graph import END, StateGraph

# ─── 引入 6 个 Agent 的创建函数 ───────────────────────────────────────────────
from src.agents import (
    create_chart_analyst,     # 图表分析师：K线形态、支撑阻力位
    create_fundamental_analyst,  # 基本面分析师：财报、估值
    create_intelligence_officer,  # 情报官：宏观政策、行业动态
    create_quantitative_analyst,  # 量化分析师：技术指标、资金流向
    create_risk_analyst,       # 风险评估师：风险量化、止损位
    create_sentiment_analyst,  # 舆情监控师：情绪分析、分析师评级
    create_supervisor,        # 首席投资官：协调 + 报告生成
)
from src.graph.state import AgentState  # 工作流共享状态
from src import config                  # 全局配置（MINIMAX_MODEL, WEIGHT_MODE, AGENT_WEIGHTS）


def build_stock_analysis_graph(
    model: str = None,
    weight_mode: str = None,
    enable_checkpoints: bool = True,
) -> "CompiledGraph":
    """
    构建股票分析工作流图

    Args:
        model: 模型名称，默认从 config.MINIMAX_MODEL 读取
        weight_mode: 权重模式，"fixed" 或 "auto"，默认从 config.WEIGHT_MODE 读取
        enable_checkpoints: 是否启用检查点（断点恢复），默认 True

    Returns:
        编译后的 StateGraph，可调用 invoke() 或 stream() 执行

    工作流构建步骤：
        1. 读取配置（model, weight_mode）
        2. 创建所有 Agent（6 个子 Agent + Supervisor）
        3. 创建 StateGraph 并添加 7 个节点
        4. 设置入口点（supervisor）
        5. 添加条件边（Supervisor 的路由逻辑）
        6. 添加各 Agent 到 Supervisor 的边
        7. 编译工作流
    """
    # ─── 1. 读取配置 ─────────────────────────────────────────────────────────
    if model is None:
        model = config.MINIMAX_MODEL
    if weight_mode is None:
        weight_mode = config.WEIGHT_MODE

    # 从全局配置读取固定权重（仅 fixed 模式使用，auto 模式由 Supervisor 动态决定）
    agent_weights = config.AGENT_WEIGHTS

    # ─── 2. 创建所有 Agent ───────────────────────────────────────────────────
    # Supervisor 协调所有 Agent，决定何时分发任务、何时生成报告
    supervisor = create_supervisor(
        model=model,
        weight_mode=weight_mode,
        fixed_weights=agent_weights,
    )
    # 6 个子 Agent，各自独立分析一个维度
    quantitative = create_quantitative_analyst(model)   # 量化分析（技术指标）
    chart = create_chart_analyst(model)                  # 图表分析（形态）
    intelligence = create_intelligence_officer(model)    # 情报收集（政策/事件）
    risk = create_risk_analyst(model)                    # 风险评估（止损位）
    fundamental = create_fundamental_analyst(model)      # 基本面分析（财报/估值）
    sentiment = create_sentiment_analyst(model)           # 舆情分析（情绪）

    # ─── 3. 创建工作流图 ─────────────────────────────────────────────────────
    # StateGraph(AgentState): 所有节点共享 AgentState 作为输入/输出
    workflow = StateGraph(AgentState)

    # ─── 4. 添加节点 ────────────────────────────────────────────────────────
    # 节点名称必须唯一，值是函数（接收 state，返回 state）
    workflow.add_node("supervisor", supervisor["supervisor_node"])           # 协调者
    workflow.add_node("quantitative", quantitative["analyze"])               # 技术面分析
    workflow.add_node("chart", chart["analyze"])                              # 形态分析
    workflow.add_node("intelligence", intelligence["gather_intelligence"])    # 情报收集
    workflow.add_node("risk", risk["analyze_risk"])                           # 风险评估
    workflow.add_node("fundamental", fundamental["analyze_fundamental"])      # 基本面分析
    workflow.add_node("sentiment", sentiment["analyze_sentiment"])             # 舆情分析

    # ─── 5. 设置入口点 ─────────────────────────────────────────────────────
    # 工作流从 supervisor 节点开始
    workflow.set_entry_point("supervisor")

    # ─── 6. 定义并行分发逻辑 ─────────────────────────────────────────────────
    def parallel_dispatch(state: AgentState) -> list:
        """
        并行分发任务到 6 个子 Agent

        Args:
            state: AgentState 当前状态

        Returns:
            Send 对象列表，每个 Send 触发一个 Agent 节点
            Send("节点名", state) 表示把当前 state 发送给该节点并行执行

        为什么用 Send 而不是直接调用？
        - Send 是异步并行：6 个 Agent 同时启动，互不等待
        - 普通函数调用是串行：必须等一个完成才能执行下一个
        """
        return [
            Send("quantitative", state),    # 并行：技术指标分析
            Send("chart", state),            # 并行：K线形态分析
            Send("intelligence", state),     # 并行：政策/事件收集
            Send("risk", state),             # 并行：风险/止损计算
            Send("fundamental", state),     # 并行：财报/估值分析
            Send("sentiment", state),        # 并行：情绪/舆情分析
        ]

    # ─── 7. 定义 Supervisor 条件边路由逻辑 ───────────────────────────────────
    def supervisor_routing(state: AgentState):
        """
        Supervisor 的条件边判断函数

        这个函数决定 Supervisor 执行完后下一步去哪

        路由决策逻辑：
            1. 已有 final_report → 直接 END（报告生成完毕）
            2. 还有缺失结果 且 routing_target="parallel" → 并行分发任务
            3. 没有缺失结果 → 让 Supervisor 再执行一次（生成报告）
            4. 其他情况 → END

        为什么需要条件边？
        - 第一次 Supervisor 执行时，6 个 Agent 结果都没有
        - 需要分发任务给 6 个 Agent
        - 6 个 Agent 完成后，回到 Supervisor，此时所有结果都有了
        - Supervisor 再执行一次，生成最终报告

        Args:
            state: AgentState 当前状态

        Returns:
            "supervisor" = 回到 Supervisor 节点再执行
            [Send(...), ...] = 并行分发任务
            END = 结束工作流
        """
        # ── 检查是否有最终报告 ───────────────────────────────────────────────
        final_report = getattr(state, "final_report", None)
        if final_report:
            print(f"  [条件边] final_report 已存在，路由到 END")
            return END

        # ── 检查是否还有缺失的 Agent 结果 ──────────────────────────────────
        # 6 个 Agent 的结果字段名
        required_results = [
            "quantitative_result",   # 量化分析师
            "chart_result",          # 图表分析师
            "intelligence_result",   # 情报官
            "risk_result",           # 风险评估师
            "fundamental_result",    # 基本面分析师
            "sentiment_result",      # 舆情监控师
        ]
        # any(getattr(state, r, None) is None for r in required_results)
        # 如果任何一个结果为 None，has_missing = True
        has_missing = any(getattr(state, r, None) is None for r in required_results)

        # 获取当前路由目标
        routing = getattr(state, "routing_target", None)

        print(f"  [条件边] routing={routing}, has_missing={has_missing}, final_report={'有' if final_report else '无'}")

        # ── 情况1：有缺失结果 且 routing_target="parallel" → 并行分发 ──────────
        # 这是第一次 Supervisor 执行后的分支
        # Supervisor 设置了 routing_target="parallel"，现在要分发任务
        if has_missing and routing == "parallel":
            print(f"  [条件边] 有缺失结果且 routing='parallel'，分发任务")
            return parallel_dispatch(state)  # Send API 并行触发 6 个 Agent

        # ── 情况2：没有缺失结果 → 让 Supervisor 再跑一次生成报告 ─────────────
        # 所有 Agent 结果都齐了，Supervisor 需要汇总生成报告
        if not has_missing:
            print(f"  [条件边] 所有结果已齐全，路由到 supervisor")
            return "supervisor"

        # ── 情况3：默认 END ──────────────────────────────────────────────────
        print(f"  [条件边] 默认路由到 END")
        return END

    # ─── 8. 添加条件边 ─────────────────────────────────────────────────────
    # add_conditional_edges(source, routing_fn, path_map)
    # - source: 哪个节点的边需要条件判断（supervisor）
    # - routing_fn: 判断函数（supervisor_routing）
    # - path_map: 可能的返回值对应的节点名
    workflow.add_conditional_edges(
        "supervisor",
        supervisor_routing,
        # Supervisor 可能返回以下路径：
        # - "supervisor" → 再跑一次 Supervisor（生成报告）
        # - END → 结束工作流
        # - [Send("quantitative", state), ...] → 并行分发到 6 个 Agent
        # 注意：path_map 中不需要列出 Send 的目标，它们通过 parallel_dispatch 返回
        ["supervisor", "quantitative", "chart", "intelligence", "risk", "fundamental", "sentiment", END],
    )

    # ─── 9. 添加各 Agent 到 Supervisor 的边 ─────────────────────────────────
    # 每个 Agent 完成后，自动回到 Supervisor（触发 Supervisor 再执行）
    # 这是 LangGraph 的边：Agent 执行完后，状态会自动流向下一个节点
    workflow.add_edge("quantitative", "supervisor")    # 量化分析师完成 → 回到 Supervisor
    workflow.add_edge("chart", "supervisor")            # 图表分析师完成 → 回到 Supervisor
    workflow.add_edge("intelligence", "supervisor")    # 情报官完成 → 回到 Supervisor
    workflow.add_edge("risk", "supervisor")             # 风险评估师完成 → 回到 Supervisor
    workflow.add_edge("fundamental", "supervisor")     # 基本面分析师完成 → 回到 Supervisor
    workflow.add_edge("sentiment", "supervisor")        # 舆情监控师完成 → 回到 Supervisor

    # ─── 10. 编译工作流 ────────────────────────────────────────────────────
    # checkpointer 用于保存工作流状态（enable_checkpoints=True 时启用）
    # MemorySaver 是内存存储，重启后丢失；生产环境可换 PostgreSQL 等
    checkpointer = MemorySaver() if enable_checkpoints else None

    # compile() 返回编译后的可调用工作流
    return workflow.compile(checkpointer=checkpointer)


# ══════════════════════════════════════════════════════════════════════════════
# 流程图（文字版）
# ══════════════════════════════════════════════════════════════════════════════
"""
                    ┌─────────────────────────────────────────────────────────┐
                    │                    Supervisor 节点                     │
                    │  首次执行：检查 missing → 设置 routing_target="parallel" │
                    │  末次执行：所有结果齐 → 生成 final_report → END         │
                    └─────────────────────────┬───────────────────────────────┘
                                              │
                          ┌───────────────────┴───────────────────┐
                          │                                       │
                          ▼                                       ▼
              routing_target="parallel"                   final_report 存在
                          │                                       │
                          ▼                                       ▼
              ┌────────────────────────────────────┐           END
              │       parallel_phase (Send API)     │
              │                                    │
              │  ┌─────────┐ ┌─────────┐ ┌─────────┐│
              │  │Quantitat│ │  Chart  │ │Intellig ││
              │  └────┬────┘ └────┬────┘ └────┬────┘│
              │  ┌─────────┐ ┌─────────┐ ┌─────────┐│
              │  │   Risk  │ │Fundamen │ │Sentimen ││
              │  └────┬────┘ └────┬────┘ └────┬────┘│
              └───────┼──────────┼──────────┼──────┘
                      │          │          │
                      └──────────┴──────────┘
                               │
                               ▼
                    各 Agent 完成后返回 Supervisor
                               │
                               ▼
              ┌────────────────────────────────────┐
              │       Supervisor 再执行             │
              │  - 汇总 6 个结果                    │
              │  - 计算综合评分                     │
              │  - 生成最终报告                     │
              │  - routing_target=None             │
              └─────────────────┬──────────────────┘
                                │
                                ▼
                              END
"""