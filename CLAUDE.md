# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## 项目概述

周末闲时活动规划 Agent — 根据用户输入的自然语言，自动完成从需求理解、POI 搜索、方案生成、评分排序到 Mock 预约执行的全流程。面向本地短时活动规划场景（半天到一天）。

## 常用命令

### 安装与运行

```bash
# 安装 Python 依赖
pip install -r requirements.txt

# 启动 FastAPI 后端（前后端分离模式，推荐）
uvicorn api:app --reload --port 8000

# 启动前端开发服务器（另开终端）
cd frontend && npm install && npm run dev
# 访问 http://localhost:5173

# 构建前端静态文件
cd frontend && npm run build

# 旧 Streamlit 应用（单文件模式）
streamlit run app.py
```

### 测试与校验

```bash
# 校验 POI seed 数据完整性和字段覆盖
python3 scripts/validate_poi_seed.py

# 运行场景分类器回归评测
python3 scripts/evaluate_scenario_classifier.py

# 运行端到端评测
python3 scripts/evaluate_e2e.py
```

### 配置文件

- **产品规则、槽位定义、评分权重**: `config/product_rules.yaml` — 产品经理优先修改此文件；`scoring.py`/`prompts.py`/`agent_harness.py` 从它读取配置
- **POI 种子数据**（活动 120 个 + 餐厅 75 个）: `data/poi_seed.yaml`
- **LLM API Key**（可选，默认用 mock 规则解析）: 复制 `.env.example` → `.env`，填入 `DEEPSEEK_API_KEY`

## 架构

### 前后端分离模式（当前主力）

```
浏览器 (React + Vite, :5173)
  → Vite proxy /api → FastAPI (uvicorn, :8000)
    → agent_harness.py (核心 Agent)
    → orchestration.py (多轮对话状态机)
    → prompts.py (NLU 解析, mock_llm 或 DeepSeek)
    → tools.py → poi_repository.py → data/poi_seed.yaml
```

前端是 `frontend/src/App.jsx`（React 19 + Vite 7 + lucide-react 图标）。构建产物在 `frontend/dist/`，FastAPI 将其作为静态文件挂载。

### 核心模块职责

| 文件 | 职责 |
|------|------|
| `agent_harness.py` | Agent 主流程：解析请求 → 补全槽位 → 搜索活动/餐厅 → 路线检查 → 构建候选方案 → 评分 → 选择最优 → 执行/兜底。`run_agent()` 是顶层入口，`run_agent_plan_only()` 仅生成方案不执行。含 Agentic feedback loop：搜索/评分失败时自动放宽约束重试（最多 3 次，阈值 55 分）。 |
| `orchestration.py` | **多轮对话状态机**（Round 0-4）：槽位收集 → 小猜问 → 泛方案卡片 → 用户选择锁定 → 正式方案搜索 → 小票生成。含跳步逻辑、防死循环检测（max_rounds=8）、回退策略。`Orchestrator` 类是驱动多轮流程的顶层控制器。 |
| `prompts.py` | NLU 解析层。`parse_request_mock()` 是规则解析器（默认），`parse_request_llm()` 调用 DeepSeek API。`generate_followup_questions()` 生成追问。含 LLM token 用量追踪。 |
| `scoring.py` | 方案评分。从 `product_rules.yaml` 读取 `scoring_strategy`，根据 companion_context + primary_intent 的 multi-label 动态调整权重，计算每个 CandidatePlan 的 ScoreBreakdown。 |
| `tools.py` | Mock API 工具：`search_activities()`, `search_restaurants()`, `check_route_time()`, `check_availability()`, `book_activity()`, `book_restaurant()`, `order_item()`, `send_plan()`。数据源来自 `poi_repository.py`。 |
| `poi_repository.py` | POI 数据抽象层。当前加载 `data/poi_seed.yaml`，定义了 `PoiAdapter` Protocol 供未来接入高德/美团等外部 POI 源。`default_poi_repository` 是全局单例。 |
| `schemas.py` | 所有 dataclass 定义：`UserRequest`, `Activity`, `Restaurant`, `RouteInfo`, `CandidatePlan`, `TimelineItem`, `ExecutionResult`, `Location`, `ScoreBreakdown` 等。`CompanionsType` / `BudgetLevel` / `ExecutionMode` 等 Enum。 |
| `receipt.py` | Round 4 小票生成：从确认的方案生成可视化小票卡片和分享文案（纯展示层，与 agent_harness 的 execute_plan 解耦）。 |
| `api.py` | FastAPI 应用。端点：`POST /api/chat`, `POST /api/execute`, `POST /api/suggest-followup`, `POST /api/template-cards`, `POST /api/select-card`, `POST /api/receipt`。内存 `_sessions` 存会话状态（MVP 单用户）。 |
| `app.py` | 旧 Streamlit UI（手机壳风格），`run_agent()` 调用 agent_harness。保留兼容，主力已切到前后端分离。 |

### 多轮对话流程 (orchestration.py)

```
INIT → SLOT_COLLECTING → GUESS_QUESTIONS → TEMPLATE_CARDS → PLAN_SEARCHING → PLAN_SHOWN → RECEIPT_GENERATED → COMPLETED
```

- **跳步**：用户已提供足够信息时跳过小猜问或模板卡片，直接进入方案搜索
- **Round X**：必填槽位缺失时插入追问引导，最多 3 次
- **回退**：`PLAN_SHOWN` 可回退到 `SLOT_COLLECTING` 供用户修改约束

### 关键设计约定

1. **配置驱动**：`config/product_rules.yaml` 是产品规则的唯一真相源（槽位 schema、评分权重、默认值、兜底策略）。`scoring.py` 和 `prompts.py` 都从它动态读取，不应在代码中硬编码业务规则。
2. **transportation 是核心槽位**：支持 driving/transit/taxi/bike_walk 四种通勤方式，自动派生 context_modifiers（如 `parking_needed`、`near_subway`），影响 max_drive_minutes 解读和路线规划。
3. **Mock 默认模式**：所有外部能力（搜索、预约、下单、消息）均为 Mock 实现，无需外部 API Key 即可运行。`prompts.py` 默认用规则解析而非 LLM。
4. **POI 扩展**：新增外部数据源时，实现 `PoiAdapter` Protocol 接入 `poi_repository.py`，不要把平台字段散落到 `tools.py`。
5. **评分是 multi-label 动态权重**：不再使用固定 6 维度权重，而是 `scoring_strategy.base_weights` + `label_adjustments`（根据 companion_context 和 primary_intent 的 label 调整），最终 normalize 到 100 分。

### 项目 Skills

- **classifier-sync**: 检查 `product_rules.yaml` 与 `prompts.py` 之间的分类器关键词一致性。编辑 YAML 或 prompts.py 的分类器逻辑后运行。
- **quality-gate**: 代码质量门禁检查。
