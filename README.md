# 多智能体股票分析系统

基于 [LangGraph](https://langchain-ai.github.io/langgraph/) + [MiniMax](https://www.minimaxi.com/) + [AKShare](https://akshare.akfamily.xyz/) 的 A 股分析系统。

## 学习项目声明

本项目是一个 **多智能体协作（Multi-Agent） Supervisor 模式**的学习与研究项目，旨在探索：

- LangGraph 工作流编排
- 多 Agent 并行/串行协作机制
- Supervisor 模式下任务分发与结果汇总

**本项目不提供任何投资建议。** 所有分析结果仅供学习研究使用，不构成任何投资决策依据。投资有风险，决策需谨慎。

## 快速开始

```bash
# 安装依赖
pip install -r requirements.txt

# 配置环境变量（复制 .env.example 为 .env 并填写配置）

# 运行分析
python -m src.main --stock 000001.SZ --name 平安银行 --notify console
```

## 架构说明

```
Supervisor（协调者）
    ├── 量化分析师（25%）
    ├── 图表分析师（15%）
    ├── 情报官（10%）
    ├── 风险评估师（20%）
    ├── 基本面分析师（20%）
    └── 舆情监控师（10%）
```

6 个专业 Agent 并行分析，最终由 Supervisor 汇总生成报告。

## 免责声明

本项目所有输出内容（包括分析报告、评分、建议等）仅供参考学习，不构成任何投资建议。用户需自行承担投资决策的全部风险，本项目不对任何投资损失负责。
