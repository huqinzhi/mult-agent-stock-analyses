"""
系统配置模块

管理所有全局配置，包括：
- MiniMax API 配置（API 密钥、地址、模型）
- 通知渠道配置（飞书/Server酱/钉钉的 Webhook URL）
- 调度配置（定时任务开关、时间）
- Agent 权重配置（Fixed/Auto 双模式）
- 批量分析配置
- 缓存配置

设计思路：
- 所有配置从环境变量读取（通过 python-dotenv）
- 提供默认值，确保即使环境变量未配置也能运行
- 配置集中管理，便于维护和修改

环境变量配置（.env 文件）：
    MINIMAX_API_KEY=your_api_key
    MINIMAX_BASE_URL=https://api.minimax.chat/v1
    MINIMAX_MODEL=MiniMax-Text-01
    FEISHU_WEBHOOK=https://open.feishu.cn/...
    SERVERCHAN_KEY=your_sendkey
    SERVERCHAN_APP_KEY=your_app_key
    DINGTALK_WEBHOOK=https://oapi.dingtalk.com/...
    WEIGHT_MODE=fixed
    SCHEDULER_TIME=10:00
"""

# ─── 标准库 ─────────────────────────────────────────────────────────────────
import os  # 操作系统，用于读取环境变量

# ─── 第三方库 ─────────────────────────────────────────────────────────────────
from dotenv import load_dotenv  # 加载 .env 文件中的环境变量

# 加载 .env 文件（如果存在）
# load_dotenv() 会查找项目根目录的 .env 文件并加载其内容
# 这允许我们在 .env 文件中配置环境变量，而不是写在代码中
load_dotenv()


# ══════════════════════════════════════════════════════════════════════════════
# MiniMax API 配置
# ══════════════════════════════════════════════════════════════════════════════

MINIMAX_API_KEY = os.getenv("MINIMAX_API_KEY", "")
"""MiniMax API 密钥（必须配置）

获取方式：在 MiniMax 开放平台注册并创建 API Key
用途：调用 MiniMax 大模型进行股票分析
"""

MINIMAX_BASE_URL = os.getenv("MINIMAX_BASE_URL", "https://api.minimax.chat/v1")
"""MiniMax API 地址

默认使用官方地址，如有代理或私有部署可修改
"""

MINIMAX_MODEL = os.getenv("MINIMAX_MODEL", "MiniMax-Text-01")
"""MiniMax 模型名称

可选模型：
- MiniMax-Text-01（默认）
- 其他可用模型见 MiniMax 文档
"""


# ══════════════════════════════════════════════════════════════════════════════
# 通知渠道配置
# ══════════════════════════════════════════════════════════════════════════════

FEISHU_WEBHOOK = os.getenv("FEISHU_WEBHOOK", "")
"""飞书 Webhook URL，如不需要飞书推送则留空

配置方式：
1. 在飞书群中添加"自定义机器人"
2. 复制 Webhook 地址并填入此处
3. 格式：https://open.feishu.cn/open-apis/bot/v2/hook/xxx
"""

WECOM_WEBHOOK = os.getenv("WECOM_WEBHOOK", "")
"""企业微信 Webhook URL（已废弃，改用 Server酱）

历史版本使用，现已被 Server酱 替代。
保留此配置仅用于兼容旧版本。
"""

DINGTALK_WEBHOOK = os.getenv("DINGTALK_WEBHOOK", "")
"""钉钉 Webhook URL

配置方式：
1. 在钉钉群中添加"机器人"
2. 选择"自定义"机器人
3. 复制 Webhook 地址并填入此处
"""

SERVERCHAN_KEY = os.getenv("SERVERCHAN_KEY", "")
"""Server酱 SendKey，用于微信推送

Server酱 是一种微信消息推送服务。
配置方式：
1. 访问 https://sct.ftqq.com/ 注册
2. 绑定微信获取 SendKey
3. 填入此处即可收到微信推送
"""

SERVERCHAN_APP_KEY = os.getenv("SERVERCHAN_APP_KEY", "")
"""Server酱 AppKey，用于微信推送（可选）

接口升级所需，如果 Server酱 提示需要升级接口，填写此值。
通常不需要配置。
"""


# ══════════════════════════════════════════════════════════════════════════════
# 调度配置
# ══════════════════════════════════════════════════════════════════════════════

SCHEDULER_ENABLED = os.getenv("SCHEDULER_ENABLED", "true").lower() == "true"
"""是否启用定时调度

- true：启用每日定时分析（V2 功能）
- false：禁用定时任务
"""

SCHEDULER_TIME = os.getenv("SCHEDULER_TIME", "10:00")
"""每日调度时间，格式 HH:MM

示例：
- "10:00" 表示每天上午 10:00 执行分析
- "14:30" 表示每天下午 2:30 执行分析
"""


# ══════════════════════════════════════════════════════════════════════════════
# Agent 权重模式配置
# ══════════════════════════════════════════════════════════════════════════════

WEIGHT_MODE = os.getenv("WEIGHT_MODE", "fixed")
"""权重模式

两种模式：
- "fixed"：使用固定权重（AGENT_WEIGHTS 配置）
- "auto"：由 Supervisor 根据数据质量和置信度动态分配权重

使用固定权重模式时，权重总和必须等于 1.0
使用自动权重模式时，报告需要包含"权重分配理由"
"""

# 固定权重配置（WEIGHT_MODE="fixed" 时生效）
# 每个 Agent 的权重代表其在综合评分中的重要性
# 权重总和必须等于 1.0
# key 为 Agent 的路由键，与 builder.py 中的节点名对应
AGENT_WEIGHTS = {
    "quantitative": float(os.getenv("WEIGHT_QUANTITATIVE", "0.25")),  # 量化分析师（权重 25%）
    "chart": float(os.getenv("WEIGHT_CHART", "0.15")),               # 图表分析师（权重 15%）
    "intelligence": float(os.getenv("WEIGHT_INTELLIGENCE", "0.10")),  # 情报官（权重 10%）
    "risk": float(os.getenv("WEIGHT_RISK", "0.20")),                 # 风险评估师（权重 20%）
    "fundamental": float(os.getenv("WEIGHT_FUNDAMENTAL", "0.20")),   # 基本面分析师（权重 20%）
    "sentiment": float(os.getenv("WEIGHT_SENTIMENT", "0.10")),       # 舆情监控师（权重 10%）
}
"""6 个 Agent 的固定权重配置

可通过环境变量覆盖：
- WEIGHT_QUANTITATIVE
- WEIGHT_CHART
- WEIGHT_INTELLIGENCE
- WEIGHT_RISK
- WEIGHT_FUNDAMENTAL
- WEIGHT_SENTIMENT

默认权重分配理由：
- quantitative (25%): 量化分析是核心，基于数据的客观分析
- risk (20%): 风险评估非常重要，防止重大亏损
- fundamental (20%): 基本面分析是价值投资的核心
- chart (15%): 技术分析辅助判断买卖时机
- intelligence (10%): 宏观和行业情报
- sentiment (10%): 市场情绪和舆情
"""


# ══════════════════════════════════════════════════════════════════════════════
# 批量分析配置
# ══════════════════════════════════════════════════════════════════════════════

BATCH_TOP_N_ENABLED = os.getenv("BATCH_TOP_N_ENABLED", "true").lower() == "true"
"""批量分析时是否仅输出评分前N名

- true：只输出评分最高的前 N 名股票（默认开启，避免输出过多）
- false：输出所有股票的分析结果
"""

BATCH_TOP_N_COUNT = int(os.getenv("BATCH_TOP_N_COUNT", "5"))
"""批量分析时保留的前几名数量

当 BATCH_TOP_N_ENABLED=true 时，只输出评分最高的前 N 名股票。
"""


# ══════════════════════════════════════════════════════════════════════════════
# 缓存配置
# ══════════════════════════════════════════════════════════════════════════════

CACHE_DIR = os.path.join(os.path.dirname(__file__), "cache")
"""缓存目录路径

用于存储缓存数据（如果有持久化缓存需求）。
默认位于 src/cache 目录。
"""


# ─── 导出所有配置项 ──────────────────────────────────────────────────────────
# 这样其他模块可以通过 `from src import config` 访问所有配置
__all__ = [
    "MINIMAX_API_KEY",         # MiniMax API 密钥
    "MINIMAX_BASE_URL",        # MiniMax API 地址
    "MINIMAX_MODEL",           # MiniMax 模型名称
    "FEISHU_WEBHOOK",          # 飞书 Webhook URL
    "WECOM_WEBHOOK",           # 企业微信 Webhook URL（已废弃）
    "DINGTALK_WEBHOOK",        # 钉钉 Webhook URL
    "SERVERCHAN_KEY",          # Server酱 SendKey
    "SERVERCHAN_APP_KEY",      # Server酱 AppKey
    "SCHEDULER_ENABLED",       # 是否启用定时调度
    "SCHEDULER_TIME",          # 每日调度时间
    "WEIGHT_MODE",             # 权重模式
    "AGENT_WEIGHTS",           # Agent 固定权重配置
    "BATCH_TOP_N_ENABLED",     # 批量分析是否只输出前N名
    "BATCH_TOP_N_COUNT",      # 批量分析保留的前几名数量
    "CACHE_DIR",               # 缓存目录路径
]
