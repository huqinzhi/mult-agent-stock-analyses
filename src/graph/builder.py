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
from src.graph.state import AgentState, IntentType  # 工作流共享状态
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
    def react_routing(state: AgentState):
        """
        ReAct 模式的路由逻辑

        决策流程：
        1. 如果 done=True → END
        2. 如果有 pending_tasks → 分发任务
        3. 如果没有 pending_tasks 且没有 final_report → Supervisor 思考下一步
        4. 如果没有 pending_tasks 且有 final_report → END

        Args:
            state: AgentState 当前状态

        Returns:
            "supervisor" = 回到 Supervisor 节点再执行
            [Send(...), ...] = 并行分发任务
            END = 结束工作流
        """
        # 检查是否完成
        if getattr(state, "done", False):
            return END

        if getattr(state, "final_report", None):
            return END

        # 获取待执行任务
        pending_tasks = getattr(state, "pending_tasks", [])
        current_iteration = getattr(state, "current_iteration", 0)
        max_iterations = getattr(state, "max_iterations", 10)

        # 检查迭代上限
        if current_iteration >= max_iterations:
            # 强制结束，生成报告
            return "supervisor"

        # 如果有待执行任务，分发它们
        if pending_tasks:
            # 根据任务类型分发到对应的 Agent
            return dispatch_tasks(state)

        # 没有待执行任务，让 Supervisor 思考下一步
        return "supervisor"

    def dispatch_tasks(state: AgentState):
        """根据任务列表分发任务"""
        pending_tasks = getattr(state, "pending_tasks", [])
        sends = []

        for task in pending_tasks:
            agent_type = task.get("agent_type") if isinstance(task, dict) else task.agent_type
            sends.append(Send(agent_type, state))

        return sends

    # ─── 8. 添加条件边 ─────────────────────────────────────────────────────
    # add_conditional_edges(source, routing_fn, path_map)
    # - source: 哪个节点的边需要条件判断（supervisor）
    # - routing_fn: 判断函数（supervisor_routing）
    # - path_map: 可能的返回值对应的节点名
    workflow.add_conditional_edges(
        "supervisor",
        react_routing,  # 改为 react_routing
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

# ── 意图到 Agent 的映射 ──────────────────────────────────────────

INTENT_AGENT_MAPPING = {
    IntentType.STOCK_ANALYSIS: {
        "required": ["quantitative", "chart", "fundamental", "risk", "sentiment"],
        "optional": ["intelligence", "news"],
        "execution_mode": "parallel",
    },
    IntentType.STOCK_SCREENING: {
        "required": ["screener", "comparer"],
        "optional": ["fundamental", "risk"],
        "execution_mode": "sequential",
    },
    IntentType.STOCK_COMPARISON: {
        "required": ["comparer", "fundamental", "risk"],
        "optional": ["chart", "sentiment"],
        "execution_mode": "parallel_per_stock",
    },
    IntentType.INDUSTRY_ANALYSIS: {
        "required": ["industry", "macro"],
        "optional": ["fundamental", "risk"],
        "execution_mode": "sequential",
    },
    IntentType.MACRO_ANALYSIS: {
        "required": ["macro", "intelligence"],
        "optional": [],
        "execution_mode": "parallel",
    },
    IntentType.RISK_ASSESSMENT: {
        "required": ["risk", "quantitative"],
        "optional": ["fundamental", "sentiment"],
        "execution_mode": "sequential",
    },
    IntentType.CONSULTATION: {
        "required": ["supervisor"],
        "optional": [],
        "execution_mode": "sequential",
    },
}