# 飞书 WebSocket 长连接方案设计文档

> **最后更新**: 2026-04-21

---

## 目录

- [方案概述](#方案概述)
- [架构设计](#架构设计)
- [数据流](#数据流)
- [飞书 WebSocket 接入](#飞书-websocket-接入)
- [代码改造点](#代码改造点)
- [新增模块详细设计](#新增模块详细设计)
- [环境变量配置](#环境变量配置)
- [测试计划](#测试计划)

---

## 方案概述

### 背景

原计划使用 Server酱（微信推送）实现"微信接收股票代码 → 本地分析 → 微信接收报告"的闭环，但 Server酱 仅支持单向推送，无法接收微信消息。

改用飞书 WebSocket 长连接方案，实现：

```
飞书机器人接收消息 → 本地服务 → 执行分析 → 飞书机器人推送结果
```

### 技术选型

| 组件 | 方案 | 说明 |
|------|------|------|
| **消息接收** | 飞书 WebSocket 长连接 | 本地服务主动连接飞书服务器，无需公网地址 |
| **消息推送** | 飞书 Webhook | 现有的 FeishuNotifier 复用 |
| **SDK** | lark-oapi | 飞书官方 Python SDK，支持 WebSocket |

### 优势

- **无需公网地址**：WebSocket 由本地主动连接飞书服务器，突破防火墙限制
- **实时性好**：长连接即时推送，无轮询延迟
- **官方支持**：lark-oapi SDK 稳定可靠
- **复用现有代码**：通知推送模块（FeishuNotifier）可直接复用

---

## 架构设计

### 整体架构

```
┌─────────────────────────────────────────────────────────────────┐
│                          飞书服务器                              │
│  ┌─────────────────────────────────────────────────────────┐   │
│  │                  飞书机器人 (App)                         │   │
│  │  - 接收用户消息 (WebSocket 长连接)                         │   │
│  │  - 推送消息 (Webhook POST)                                │   │
│  └─────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────┘
                              ↕ (WebSocket + HTTP)
┌─────────────────────────────────────────────────────────────────┐
│                      本地服务                                   │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐         │
│  │ feishu_ws/   │  │  analysis/   │  │notification/│         │
│  │ listener.py  │  │  engine.py   │  │  notifier.py │         │
│  └──────────────┘  └──────────────┘  └──────────────┘         │
│         ↓                ↓                  ↑                  │
│         └────────────────┼──────────────────┘                  │
│                          ↓                                     │
│                   ┌──────────────┐                             │
│                   │   main.py    │                             │
│                   └──────────────┘                             │
└─────────────────────────────────────────────────────────────────┘
```

### 模块职责

| 模块 | 文件 | 职责 |
|------|------|------|
| **飞书 WebSocket 监听** | `src/feishu_ws/listener.py` | 长连接管理、接收消息、解析命令 |
| **飞书消息处理器** | `src/feishu_ws/handler.py` | 命令识别、路由、响应构建 |
| **分析引擎** | `src/feishu_ws/engine.py` | 复用现有 `build_stock_analysis_graph` |
| **飞书通知器** | `src/notification/feishu.py` | 报告推送（已存在） |

---

## 数据流

### 消息流程

```
用户: "000001"
    ↓ (飞书客户端发送消息)
飞书服务器
    ↓ (WebSocket 长连接推送到本地)
listener.py (消息接收)
    ↓
handler.py (解析命令: 股票代码)
    ↓
engine.py (执行分析流程)
    ↓
notifier.py (推送报告到飞书)
    ↓
用户收到: 分析报告
```

### 完整序列图

```
用户        飞书服务器      本地 listener     handler        engine        notifier
 │              │                │              │              │              │
 │──发送消息──→ │                │              │              │              │
 │              │──WebSocket───→ │              │              │              │
 │              │                │              │              │              │
 │              │                │──解析命令──→ │              │              │
 │              │                │              │──路由──→    │              │
 │              │                │              │              │              │
 │              │                │              │──分析请求──→│              │
 │              │                │              │              │              │
 │              │                │              │              │──执行分析──→│
 │              │                │              │              │              │
 │              │                │              │←──报告──────│              │
 │              │                │              │              │              │
 │              │                │              │──推送请求──→│              │
 │              │←───────────────│              │              │              │
 │←推送报告────│                │              │              │              │
```

### 实时 Agent 结果推送

飞书机器人在分析过程中，**实时推送每个子 Agent 的完成状态和结论**，而非等全部完成后才发送最终报告。

**推送时机与内容**：

| 阶段 | 推送内容 | 说明 |
|------|----------|------|
| Supervisor 分发任务 | `📤 开始分析: {股票名称} ({ts_code})` | 告知开始分析 |
| 量化分析师完成 | `✅ [量化分析师] 评分: {score}/100\n{conclusion}` | 立即推送中间结果 |
| 图表分析师完成 | `✅ [图表分析师] 评分: {score}/100\n{conclusion}` | 立即推送中间结果 |
| 情报官完成 | `✅ [情报官] 评分: {score}/100\n{conclusion}` | 立即推送中间结果 |
| 风险评估师完成 | `✅ [风险评估师] 评分: {score}/100\n{conclusion}` | 立即推送中间结果 |
| 基本面分析师完成 | `✅ [基本面分析师] 评分: {score}/100\n{conclusion}` | 立即推送中间结果 |
| 舆情监控师完成 | `✅ [舆情监控师] 评分: {score}/100\n{conclusion}` | 立即推送中间结果 |
| Supervisor 生成报告 | 完整综合分析报告 | 最终报告 |

**流式推送序列图**：

```
用户        飞书服务器      engine         Agent完成回调
 │              │              │                │
 │              │              │──分析开始──────→│
 │←─────────────│              │                │
 │  📤 开始分析 │              │                │
 │              │              │                │
 │              │         ┌────┴────┐           │
 │              │         │ 6 Agent │           │
 │              │         │ 并行执行│           │
 │              │         └────┬────┘           │
 │              │              │                │
 │              │    ←量化完成通知─┤            │
 │←─────────────│              │                │
 │ ✅ 量化结论  │              │                │
 │              │              │                │
 │              │    ←图表完成通知─┤            │
 │←─────────────│              │                │
 │ ✅ 图表结论  │              │                │
 │              │              │                │
 │              │    ←...继续...─┤              │
 │              │              │                │
 │              │   ←Supervisor完成─┤           │
 │←─────────────│              │                │
 │ 📋 最终报告  │              │                │
```

**Engine 改造点**：

```python
class AnalysisEngine:
    """分析引擎 - 支持流式回调推送"""

    def __init__(self, weight_mode: str = "fixed", push_callback=None):
        """初始化引擎

        Args:
            weight_mode: 权重模式
            push_callback: 推送回调函数，签名: (agent_name, result) -> None
        """
        self.weight_mode = weight_mode
        self.push_callback = push_callback  # 飞书推送回调

    def analyze(self, ts_code: str, name: str) -> str:
        """执行股票分析，带实时推送"""
        graph = build_stock_analysis_graph(
            weight_mode=self.weight_mode,
            enable_checkpoints=False,
        )
        query = StockQuery(ts_code=ts_code, stock_name=name)
        state = AgentState(query=query, messages=[], completed_tasks=[])
        config_dict = {"configurable": {"thread_id": f"feishu_{ts_code}"}}

        for event in graph.stream(state, config=config_dict):
            for node_name, node_state in event.items():
                # 实时推送各 Agent 结果
                if node_name in ["quantitative", "chart", "intelligence",
                                 "risk", "fundamental", "sentiment"]:
                    result = getattr(node_state, f"{node_name}_result", None)
                    if result and self.push_callback:
                        self.push_callback(node_name, result)

                # Supervisor 生成最终报告
                elif node_name == "supervisor":
                    final_report = getattr(node_state, "final_report", None)
                    if final_report:
                        return final_report

        return "分析失败"
```

---

---

## 飞书 WebSocket 接入

### 接入方式

飞书提供两种接收消息的方式：

| 模式 | 说明 | 适用场景 |
|------|------|----------|
| **HTTP 回调** | 飞书服务器主动调用你的地址 | 需要公网地址 |
| **WebSocket 长连接** | 本地主动连接飞书服务器 | 本地部署，无公网 |

本方案使用 **WebSocket 长连接**模式。

### lark-oapi SDK 使用

```python
from lark_oapi.adapter.websocket import WebSocketClient
from lark_oapi.api.im.v1 import CreateMessageRequest

class FeishuWebSocketListener:
    """飞书 WebSocket 长连接监听器"""

    def __init__(self, app_id: str, app_secret: str, event_handler):
        self.app_id = app_id
        self.app_secret = app_secret
        self.event_handler = event_handler
        self.ws_client = None

    def start(self):
        """启动 WebSocket 长连接"""
        self.ws_client = WebSocketClient(
            self.app_id,
            self.app_secret,
            self.event_handler,
        )
        self.ws_client.start()

    def send_message(self, open_id: str, content: str):
        """发送消息到用户"""
        # 使用 im.v1 API 发送消息
        request = CreateMessageRequest.builder()
            .user_id(open_id)
            .msg_type("text")
            .content(content)
            .build()
        # 调用发送逻辑
```

### 消息类型

飞书机器人接收的消息类型：

| 消息类型 | 说明 | 处理方式 |
|----------|------|----------|
| `text` | 文本消息 | 解析股票代码 |
| `post` | 富文本消息 | 暂不支持 |
| `image` | 图片 | 暂不支持 |

### 命令格式

```
# 格式
股票代码 [股票名称]

# 示例
000001
000001 平安银行
600036.SH 招商银行
```

---

## 代码改造点

### 新增文件

| 文件 | 说明 |
|------|------|
| `src/feishu_ws/__init__.py` | 模块入口 |
| `src/feishu_ws/listener.py` | WebSocket 长连接管理 |
| `src/feishu_ws/handler.py` | 消息处理和路由 |
| `src/feishu_ws/matcher.py` | 股票匹配器（支持三种格式解析） |
| `src/feishu_ws/engine.py` | 分析引擎封装 |

### 改造文件

| 文件 | 改造内容 |
|------|----------|
| `src/main.py` | 新增 `--feishu-ws` 启动模式 |
| `src/config/__init__.py` | 新增飞书 WebSocket 配置项 |
| `src/notification/feishu.py` | 增强，支持推送消息到用户 |
| `docs/04-飞书机器人部署指南.md` | 新增部署文档 |

### 移除文件

| 文件 | 说明 |
|------|------|
| `src/notification/serverchan.py` | Server酱方案废弃 |
| `src/notification/notifier.py` 中的 Server酱相关代码 | 移除 |

---

## 新增模块详细设计

### 1. FeishuWebSocketListener (`src/feishu_ws/listener.py`)

```python
class FeishuWebSocketListener:
    """飞书 WebSocket 长连接监听器

    通过 WebSocket 长连接接收飞书消息，无需公网地址。
    """

    def __init__(
        self,
        app_id: str,
        app_secret: str,
        event_handler: "FeishuEventHandler",
    ):
        """初始化监听器

        Args:
            app_id: 飞书应用 App ID
            app_secret: 飞书应用 App Secret
            event_handler: 事件处理器
        """
        self.app_id = app_id
        self.app_secret = app_secret
        self.event_handler = event_handler
        self.ws_client = None

    def start(self):
        """启动 WebSocket 长连接

        建立与飞书服务器的 WebSocket 连接，开始接收消息。
        连接断开时会自动重连。
        """
        ...

    def stop(self):
        """停止监听器"""
        ...
```

### 命令格式与股票匹配

支持三种输入格式，均能正确匹配到股票：

| 输入格式 | 示例 | 匹配方式 |
|----------|------|----------|
| 纯股票代码 | `000001` | 精确匹配 ts_code（自动补全 .SZ/.SH） |
| 代码 + 名称 | `000001 平安银行` | 代码精确匹配，名称仅作参考 |
| 纯股票名称 | `平安银行` | 模糊匹配股票池 → AKShare 搜索 |

**股票代码自动识别规则**：
- 6 位数字 → 视为股票代码，自动补全后缀
- 末尾 `.SZ` / `.SH` 存在则保留
- 匹配顺序：精确 ts_code > 模糊名称匹配

### 2. FeishuEventHandler (`src/feishu_ws/handler.py`)

```python
class FeishuEventHandler:
    """飞书消息事件处理器

    负责解析消息、识别命令、构建响应。
    """

    def __init__(self, engine: "AnalysisEngine"):
        """初始化处理器

        Args:
            engine: 分析引擎实例
        """
        self.engine = engine
        # 股票匹配器
        from src.feishu_ws.matcher import StockMatcher
        self.matcher = StockMatcher()

    def handle(self, event: dict):
        """处理飞书事件

        Args:
            event: 飞书 WebSocket 事件
        """
        # 解析消息类型
        message_type = event.get("msg_type", "")
        if message_type == "text":
            return self._handle_text(event)
        # 其他类型暂不处理
        return None

    def _handle_text(self, event: dict) -> str:
        """处理文本消息

        Args:
            event: 消息事件

        Returns:
            响应内容
        """
        # 提取消息内容
        content = event.get("content", "")
        # 解析股票信息（支持三种格式）
        stock_info = self._parse_stock_command(content)
        if stock_info is None:
            return "格式错误，请输入股票代码或名称，如：000001 或 平安银行"

        ts_code = stock_info["ts_code"]
        name = stock_info["name"]

        # 执行分析
        report = self.engine.analyze(ts_code, name)
        return report

    def _parse_stock_command(self, text: str) -> Optional[dict]:
        """解析股票命令

        支持三种格式：
        1. 纯股票代码: "000001" → (ts_code, name)
        2. 代码+名称: "000001 平安银行" → (ts_code, name)
        3. 纯名称: "平安银行" → (ts_code, name)

        Args:
            text: 原始消息文本

        Returns:
            {"ts_code": str, "name": str, "source": str} 或 None
        """
        return self.matcher.match(text)

### 3. StockMatcher (`src/feishu_ws/matcher.py`)

```python
import re
from typing import Optional, Dict

class StockMatcher:
    """股票匹配器

    支持三种输入格式的股票匹配：
    1. 纯股票代码: "000001" → 精确匹配 ts_code
    2. 代码+名称: "000001 平安银行" → 代码精确匹配
    3. 纯股票名称: "平安银行" → 模糊匹配股票池 → AKShare

    股票代码自动识别规则：
    - 6 位纯数字 → 自动补全 .SZ 或 .SH 后缀
    - 已包含 .SZ/.SH 后缀 → 直接使用
    - 优先精确匹配，其次模糊匹配
    """

    # A股股票代码正则（6位数字，可选后缀）
    STOCK_CODE_PATTERN = re.compile(r"^(\d{6})(?:\.(SZ|SH))?$")

    def __init__(self):
        """初始化股票匹配器"""
        self._stock_pool = None  # 延迟加载

    @property
    def stock_pool(self):
        """延迟加载股票池"""
        if self._stock_pool is None:
            from src.config.stock_pool import get_stock_pool
            self._stock_pool = get_stock_pool()
        return self._stock_pool

    def match(self, text: str) -> Optional[Dict[str, any]]:
        """匹配股票

        Args:
            text: 用户输入，如 "000001"、"平安银行"、"000001 平安银行"

        Returns:
            {"ts_code": str, "name": str, "source": str, "confidence": float}
            或 None（匹配失败）
        """
        text = text.strip()
        if not text:
            return None

        # 情况1: 输入包含空格，优先按代码匹配
        if " " in text:
            parts = text.split()
            code = parts[0].strip()
            name = parts[1].strip() if len(parts) > 1 else None

            # 尝试补全代码
            ts_code = self._normalize_code(code)
            if ts_code and self._exists_in_pool(ts_code):
                stock = self._get_stock_by_code(ts_code)
                return {
                    "ts_code": ts_code,
                    "name": name or stock["name"],
                    "source": "stock_pool",
                    "confidence": 1.0,
                }

            # 如果股票池没有，通过代码查 AKShare
            if ts_code:
                result = self._search_akshare_by_code(ts_code, name)
                if result:
                    return result

            return None

        # 情况2: 纯数字 → 股票代码
        if text.isdigit() and len(text) == 6:
            ts_code = self._normalize_code(text)
            if ts_code and self._exists_in_pool(ts_code):
                stock = self._get_stock_by_code(ts_code)
                return {
                    "ts_code": ts_code,
                    "name": stock["name"],
                    "source": "stock_pool",
                    "confidence": 1.0,
                }
            # 查 AKShare
            result = self._search_akshare_by_code(ts_code)
            if result:
                return result
            return None

        # 情况3: 非纯数字 → 股票名称
        return self._match_by_name(text)

    def _normalize_code(self, code: str) -> Optional[str]:
        """标准化股票代码

        Args:
            code: 原始代码，如 "000001" 或 "000001.SZ"

        Returns:
            标准化后的代码，如 "000001.SZ" 或 None
        """
        match = self.STOCK_CODE_PATTERN.match(code)
        if not match:
            return None

        number, suffix = match.groups()
        if suffix:
            return f"{number}.{suffix}"

        # 无后缀，根据代码范围判断
        # 深圳: 000xxx / 300xxx / 001xxx
        # 上海: 600xxx / 601xxx / 688xxx / 900xxx
        if number.startswith(("000", "001", "002", "003", "300")):
            return f"{number}.SZ"
        elif number.startswith(("6", "9")):
            return f"{number}.SH"
        else:
            # 默认深圳
            return f"{number}.SZ"

    def _exists_in_pool(self, ts_code: str) -> bool:
        """检查股票是否在股票池中"""
        for stock in self.stock_pool.list_stocks():
            if stock["ts_code"] == ts_code:
                return True
        return False

    def _get_stock_by_code(self, ts_code: str) -> Optional[dict]:
        """从股票池获取股票信息"""
        for stock in self.stock_pool.list_stocks():
            if stock["ts_code"] == ts_code:
                return stock
        return None

    def _match_by_name(self, name: str) -> Optional[Dict[str, any]]:
        """通过名称模糊匹配

        优先级：股票池精确匹配 → 股票池模糊匹配 → AKShare 搜索

        Args:
            name: 股票名称

        Returns:
            匹配结果或 None
        """
        # 股票池精确匹配
        for stock in self.stock_pool.list_stocks():
            if stock["name"] == name:
                return {
                    "ts_code": stock["ts_code"],
                    "name": stock["name"],
                    "source": "stock_pool",
                    "confidence": 1.0,
                }

        # 股票池模糊匹配（包含关键词）
        for stock in self.stock_pool.list_stocks():
            if name in stock["name"] or stock["name"] in name:
                return {
                    "ts_code": stock["ts_code"],
                    "name": stock["name"],
                    "source": "stock_pool",
                    "confidence": 0.8,
                }

        # AKShare 搜索
        return self._search_akshare_by_name(name)

    def _search_akshare_by_code(self, ts_code: str, name: str = None) -> Optional[Dict[str, any]]:
        """通过代码搜索 AKShare

        Args:
            ts_code: 股票代码，如 "000001.SZ"
            name: 可选的名称

        Returns:
            匹配结果或 None
        """
        try:
            import akshare as ak
            # 获取股票信息
            stock_info = ak.stock_individual_info(symbol=ts_code)
            # 解析返回数据...
            # 返回格式: {"ts_code": str, "name": str, "source": "akshare"}
        except Exception:
            return None

    def _search_akshare_by_name(self, name: str) -> Optional[Dict[str, any]]:
        """通过名称搜索 AKShare

        Args:
            name: 股票名称

        Returns:
            匹配结果或 None
        """
        try:
            import akshare as ak
            # 使用 stock_name_code_map 函数搜索
            # 返回股票代码列表
        except Exception:
            return None
```

### 4. AnalysisEngine (`src/feishu_ws/engine.py`)

```python
class AnalysisEngine:
    """分析引擎

    封装现有分析流程，提供简单的接口。
    """

    def __init__(self, weight_mode: str = "fixed"):
        """初始化引擎

        Args:
            weight_mode: 权重模式，"fixed" 或 "auto"
        """
        self.weight_mode = weight_mode

    def analyze(self, ts_code: str, name: str) -> str:
        """执行股票分析

        Args:
            ts_code: 股票代码，如 "000001.SZ"
            name: 股票名称

        Returns:
            分析报告文本
        """
        # 复用现有工作流
        from src.graph.builder import build_stock_analysis_graph
        from src.graph.state import AgentState, StockQuery

        graph = build_stock_analysis_graph(
            weight_mode=self.weight_mode,
            enable_checkpoints=False,
        )
        query = StockQuery(ts_code=ts_code, stock_name=name)
        state = AgentState(query=query, messages=[], completed_tasks=[])

        # 流式执行
        config_dict = {"configurable": {"thread_id": f"feishu_{ts_code}"}}
        final_report = None

        for event in graph.stream(state, config=config_dict):
            for node_name, node_state in event.items():
                if node_name == "supervisor":
                    final_report_val = getattr(node_state, "final_report", None)
                    if final_report_val:
                        final_report = final_report_val

        if final_report is None:
            return "分析失败，请稍后重试"

        return final_report
```

---

## 环境变量配置

### 新增配置项

`.env` 文件需要配置：

```bash
# 飞书 WebSocket 配置（新增）
FEISHU_APP_ID=cli_xxxxxxxxxxxxxxxx
FEISHU_APP_SECRET=xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
FEISHU_WS_ENABLED=true

# 飞书 Webhook（已存在，用于推送）
FEISHU_WEBHOOK=https://open.feishu.cn/open-apis/bot/v2/hook/xxx

# 现有配置
MINIMAX_API_KEY=sk-xxxxxxxx
WEIGHT_MODE=fixed
```

### 飞书应用配置

在飞书开放平台创建应用后，需要：

1. **获取 App ID 和 App Secret**
2. **开启机器人能力**
3. **配置消息权限**
   - `im:message` - 读取消息
   - `im:message:send_as_bot` - 发送消息
4. **订阅事件**（WebSocket 模式）
   - `im.message.receive_v1` - 接收消息

---

## 启动方式

### 方式 A：纯 WebSocket 监听模式（接收消息 + 推送）

```bash
python -m src.main --feishu-ws
```

### 方式 B：CLI 模式 + WebSocket 监听（同时支持）

```bash
# 后台运行 WebSocket 监听
python -m src.main --feishu-ws &

# 前台运行 CLI
python -m src.main --stock 000001.SZ --name 平安银行 --notify feishu
```

### 方式 C：定时调度 + WebSocket（V2）

```bash
python -m src.main --feishu-ws --schedule --schedule-time 10:00
```

---

## 测试计划

### 单元测试

| 测试项 | 文件 | 说明 |
|--------|------|------|
| 消息解析 | `test_feishu_handler.py` | `_parse_stock_command` 边界测试 |
| 引擎封装 | `test_feishu_engine.py` | Mock 分析流程 |
| 监听器启动 | `test_feishu_listener.py` | Mock WebSocket 连接 |

### 集成测试

| 测试项 | 说明 |
|--------|------|
| WebSocket 连接 | 验证能成功连接飞书服务器 |
| 消息接收 | 发送测试消息，验证能正确接收 |
| 命令解析 | 发送各种格式的命令，验证解析正确 |
| 分析执行 | 验证分析流程正常运行 |
| 结果推送 | 验证飞书能收到推送消息 |

### 测试用例

```python
# 命令解析测试
assert _parse_stock_command("000001") == ("000001.SZ", None)
assert _parse_stock_command("000001 平安银行") == ("000001.SZ", "平安银行")
assert _parse_stock_command("600036.SH") == ("600036.SH", None)

# 消息处理测试
# 发送 "000001" → 应返回分析报告
# 发送 "格式错误" → 应返回错误提示
```

---

## 风险与注意事项

### 1. 飞书消息限制

- 飞书机器人每秒最多发送 20 条消息
- 单条消息最大 4KB
- 报告超长时需要分多次发送

### 2. 长连接稳定性

- 网络断开时 SDK 会自动重连
- 建议增加心跳机制
- 长时间断开可考虑重启监听

### 3. 安全性

- `APP_ID` 和 `APP_SECRET` 必须保密
- 建议使用环境变量而非明文配置
- 验证消息来源（飞书 SDK 已做签名验证）

### 4. 限流处理

- 分析耗时较长（30-60 秒），需要防重复触发
- 可在 handler 中增加命令冷却时间（如同一用户 30 秒内只处理一次）

---

## 版本规划

| 版本 | 功能 | 说明 |
|------|------|------|
| **V1.1** | 飞书 WebSocket 接入 | 实现消息接收和推送 |
| **V1.2** | 命令解析增强 | 支持更多格式 |
| **V2.0** | 定时调度 + 批量分析 | 结合飞书实现自动化 |