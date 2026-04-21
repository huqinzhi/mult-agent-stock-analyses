# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## 项目概述

多智能体股票分析系统：基于 LangGraph + MiniMax + AKShare 的 A 股分析系统。
**核心约束**: P0 风险控制 - 完整免责系统。

**当前版本**: V1（仅支持单股分析）
- V1: 仅支持单个股票分析
- V2: 将开放批量分析和定时调度功能

## 常用命令

```bash
# 依赖安装
pip install -r requirements.txt

# 单股分析（V1 唯一支持的模式）
python -m src.main --stock 000001.SZ --name 平安银行 --notify console

# V2 批量分析（V1 暂不开放）
# python -m src.main --batch --notify serverchan

# V2 定时调度（V1 暂不开放）
# python -m src.main --schedule --notify serverchan

# 股票池管理（V2 批量分析预留）
python -m src.main stock list
python -m src.main stock add --code 000001.SZ --name 平安银行 --tags 银行
python -m src.main stock remove --code 600036.SH
python -m src.main stock enable --code 000001.SZ
python -m src.main stock disable --code 600036.SH

# 权重模式切换
python -m src.main --stock 000001.SZ --weight-mode auto  # 自动权重
python -m src.main --stock 000001.SZ --weight-mode fixed # 固定权重
```

## 环境变量配置

`.env` 文件需要配置：
- `MINIMAX_API_KEY`（必须）
- `SERVERCHAN_KEY`（微信推送，SendKey）
- `SERVERCHAN_APP_KEY`（微信推送，AppKey）
- `FEISHU_WEBHOOK`（飞书推送）
- `DINGTALK_WEBHOOK`（钉钉推送）
- `WEIGHT_MODE`（fixed/auto，默认 fixed）

## 核心配置

**固定权重**（`config.AGENT_WEIGHTS`）：
```python
AGENT_WEIGHTS = {
    "quantitative": 0.25,   # 量化分析师
    "chart": 0.15,          # 图表分析师
    "intelligence": 0.10,   # 情报官
    "risk": 0.20,           # 风险评估师
    "fundamental": 0.20,    # 基本面分析师
    "sentiment": 0.10,      # 舆情监控师
}
```
- Fixed 模式直接使用上述权重
- Auto 模式由 Supervisor 根据 `data_quality.quality_score` 和 `confidence` 动态分配

## 架构概览

```
src/
├── main.py              # CLI 入口（stock 子命令、单股/批量/调度）
├── config.py            # 全局配置（权重、API、通知渠道）
├── llm/minimax_client.py   # MiniMax API 封装
├── tools/                   # AKShare + 搜索 + 时间工具
├── graph/
│   ├── state.py            # AgentState、AgentResult、StockQuery
│   └── builder.py           # build_stock_analysis_graph（6 Agent 并行）
├── agents/
│   ├── supervisor.py       # 首席投资官（协调 + 报告生成）
│   ├── quantitative_analyst.py（25%）
│   ├── chart_analyst.py（15%）
│   ├── intelligence_officer.py（10%）
│   ├── risk_analyst.py（20%）
│   ├── fundamental_analyst.py（20%）
│   └── sentiment_analyst.py（10%）
├── compliance/             # P0 合规免责
├── notification/          # 多渠道推送
├── scheduler/             # APScheduler 定时（V2 开放）
├── batch/                 # 并发批量分析（V2 开放）
└── config/
    ├── stock_pool.py   # JSON 股票池
    └── __init__.py     # 配置模块
```

## 关键设计

**LangGraph 工作流（核心路由逻辑）**：

```
supervisor[首次] ──(completed_tasks 为空)──→ parallel_phase
                                                      │
                                              Send() 并发分发到 6 个 Agent
                                                      │
                              ┌───────────────────────┼───────────────────────┐
                              ↓                       ↓                       ↓
                       quantitative              chart                  intelligence
                             │                       │                       │
                       fundamental                risk                  sentiment
                              └───────────────────────┼───────────────────────┘
                                                      │
                                                      ↓
supervisor[再次] ──(completed_tasks 非空)──→ END
```

关键点：
- `builder.py:111-143` 的 `supervisor_routing` 条件边根据 `routing_target` 和 `has_missing` 决定路由
- Supervisor **被触发两次**：首次执行时结果未齐，设置 `routing_target="parallel"`，6 个 Agent 并行完成后各自通过边返回 Supervisor，触发二次执行，此时无缺失结果则生成报告
- `parallel_phase` 节点通过 LangGraph Send API 实现真正的并发执行，6 个 Agent 同时运行
- 6 个 Agent 完成后各自通过边返回 Supervisor，触发二次执行，此时进入 END

**权重模式**：
- Fixed：`config.AGENT_WEIGHTS` 固定权重汇总
- Auto：Supervisor 根据 `data_quality.quality_score` 和 `confidence` 动态分配，报告需含"权重分配理由"

**合规 P0**：
- `DisclaimerFilter`（`compliance/disclaimer_filter.py`）过滤高风险煽动性词汇，保留专业投资建议术语（建议买入、止损位等）
- `MandatoryDisclaimer`（`compliance/mandatory_disclaimer.py`）在报告尾部注入完整免责文本
- 所有报告生成必经这两个过滤环节

**数据缓存**（`src/cache/`）：
| 数据类型 | 缓存时间 | 说明 |
|----------|----------|------|
| K线数据 | 5分钟 | 实时性要求高 |
| 行情数据 | 5分钟 | 实时性要求高 |
| 资金流向 | 10分钟 | 相对稳定 |
| 新闻/搜索 | 5分钟 | 时效性强 |

手动清理：`from src.tools.akshare_tools import clear_akshare_cache`

**股票池存储**（`config/stock_pool.py`）：JSON 文件管理，支持 list/add/remove/enable/disable 命令

**AgentState（`graph/state.py`）核心字段**：
- `query: StockQuery` — 查询请求（含 ts_code、日期范围）
- 6 个 `*_result: AgentResult` — 各 Agent 分析结果
- `final_report: str` — Supervisor 生成的综合报告
- `data_quality_summary: DataQualitySummary` — 各维度数据质量指标

## 开发注意事项

- 所有方法上方必须有中文注释（参数、返回值、用途）
- 投资建议需基于数据分析结论，不可主观臆断
- 报告必须附带完整免责声明
- 测试文件：`src/test_workflow.py`（工作流测试）、`src/test_agents.py`（Agent 测试）、`src/test_debug.py`（调试）

## 文档索引

| 文档 | 说明 |
|------|------|
| `docs/01-用户使用文档.md` | 用户使用指南，环境配置，常用命令 |
| `docs/02-项目介绍.md` | 项目概述，核心特性，目录结构 |
| `docs/03-设计文档.md` | 详细设计，API 说明，Agent 详解，工作流 |