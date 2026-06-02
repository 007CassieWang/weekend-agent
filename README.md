# 周末闲时活动规划 Agent

一个本地场景短时活动规划与执行 Agent 的 MVP Demo。

## 项目背景

本项目旨在帮助临时产生半天闲暇时间的本地用户（主要是带孩子的家庭或朋友聚会）快速规划周末活动。用户只需输入一句自然语言，Agent 就能自动完成从需求理解、信息查询、方案生成、评分选择到预约执行的全流程。

## 什么是 Agent Harness

本项目中的 **Agent Harness** 是连接需求理解、工具调用、状态管理、异常处理和执行动作的轻量级 Agent 执行框架。

它不是一个模型训练框架，也不是复杂的评测框架，而是让大模型或规则系统在一个可控、可观察、可复现的流程中完成任务。Harness 的核心职责包括：

1. **状态管理**：维护 Agent 执行过程中的所有中间状态
2. **工具调度**：按顺序调用各类 Mock API 工具
3. **异常处理**：当某个环节失败时，自动触发备选策略
4. **执行动作**：完成预约、下单、通知等最终操作

## 系统架构

```
┌─────────────────────────────────────────────────────────────┐
│                      Streamlit UI (app.py)                   │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────────────┐  │
│  │ 用户输入框   │  │ 规则展示区   │  │ 执行过程可视化       │  │
│  └─────────────┘  └─────────────┘  └─────────────────────┘  │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│                   Agent Harness (agent_harness.py)           │
│  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────────┐   │
│  │ 需求解析  │→│ 信息补全  │→│ 工具调用  │→│ 方案评分排序  │   │
│  └──────────┘ └──────────┘ └──────────┘ └──────────────┘   │
│         │                                                    │
│         ▼                                                    │
│  ┌──────────────────────────────────────────────────────┐   │
│  │ 异常处理模块: 餐厅满座/活动不可用/路线过远/儿童不适合...  │   │
│  └──────────────────────────────────────────────────────┘   │
│         │                                                    │
│         ▼                                                    │
│  ┌──────────────────────────────────────────────────────┐   │
│  │ 执行模块: Mock预约/Mock下单/Mock消息发送              │   │
│  └──────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────┘
                              │
            ┌─────────────────┼─────────────────┐
            ▼                 ▼                 ▼
    ┌──────────────┐ ┌──────────────┐ ┌──────────────┐
    │   tools.py   │ │  scoring.py  │ │  prompts.py  │
    │  Mock API    │ │   评分规则    │ │ 提示词/解析   │
    └──────────────┘ └──────────────┘ └──────────────┘
                              │
                              ▼
              ┌───────────────────────────┐
              │ config/product_rules.yaml │
              │      产品规则配置          │
              └───────────────────────────┘
```

## 文件结构说明

```
weekend_agent/
├── app.py                      # Streamlit 前端入口
│   └── 提供 Web UI，展示 Agent 执行过程和结果
│
├── agent_harness.py             # Agent 主流程、状态管理、工具调度、异常处理
│   ├── WeekendActivityAgent 类
│   ├── 10 步标准执行流程
│   └── 异常处理机制
│
├── data/poi_seed.yaml           # 本地 POI seed 数据
│   ├── activities: 120 个预设活动/场所
│   └── restaurants: 75 个预设餐饮/咖啡茶饮
│
├── poi_repository.py            # POI 读取与模型转换层
│
├── tools.py                     # Mock API 工具函数
│   └── 搜索/查询/预约/下单/发送消息等工具
│
├── schemas.py                   # 结构化数据模型
│   ├── UserRequest: 用户请求
│   ├── Activity/Restaurant: 活动和餐厅
│   ├── CandidatePlan: 候选方案
│   └── ExecutionResult: 执行结果
│
├── scoring.py                   # 方案评分规则
│   ├── 6 个评分维度
│   └── 从 product_rules.yaml 读取权重
│
├── prompts.py                   # 大模型提示词或 mock_llm 解析规则
│   ├── parse_request_mock: 规则解析用户输入
│   └── 从 product_rules.yaml 读取配置
│
├── config/
│   └── product_rules.yaml       # 产品经理可配置的产品规则
│       ├── 用户画像
│       ├── 默认配置
│       ├── 追问规则
│       ├── 评分权重
│       └── 异常兜底策略
│
├── requirements.txt             # Python 依赖
└── README.md                    # 项目说明
```

## Agent 执行流程

Agent 按照以下固定流程运行：

```
Step 1: parse_request          解析用户自然语言，输出结构化约束 JSON
       ↓
Step 2: complete_missing_slots 根据 product_rules.yaml 补全缺失信息
       ↓
Step 3: search_activities      查询附近适合的活动
       ↓
Step 4: search_restaurants     查询适合的餐厅
       ↓
Step 5: check_route_time       检查家、活动、餐厅之间的路线时间
       ↓
Step 6: build_candidate_plans  组合 2-3 个候选方案
       ↓
Step 7: score_plans            根据评分权重对候选方案评分
       ↓
Step 8: choose_best_plan       选择最优方案，并给出选择理由
       ↓
Step 9: execute_plan           执行 Mock 预约、下单、发送消息动作
       ↓
Step 10: handle_failure        如果失败，自动切换备选方案
```

## 工具调用链路

典型的工具调用链路如下：

```
用户输入
    │
    ├──→ get_user_context()          # 获取用户位置、家庭信息
    │
    ├──→ search_activities()         # 搜索活动
    │        └── 返回 Activity[]
    │
    ├──→ search_restaurants()        # 搜索餐厅
    │        └── 返回 Restaurant[]
    │
    ├──→ check_route_time()          # 计算路线（多次调用）
    │        └── 返回 RouteInfo
    │
    ├──→ check_availability()        # 检查可预约状态
    │
    └──→ 对每个选中的活动和餐厅：
            ├──→ book_activity()     # 预约活动
            ├──→ book_restaurant()   # 预约餐厅
            ├──→ order_item()        # 下单（蛋糕/鲜花）
            └──→ send_plan()         # 发送消息给家人/朋友
```

## 评分规则

总分 100 分，各项权重从 `product_rules.yaml` 读取：

| 维度 | 权重 | 评估标准 |
|------|------|----------|
| 时间合理性 | 20分 | 活动时长是否合适，能否在指定时间内完成 |
| 距离合理性 | 20分 | 是否超过最大车程限制，通勤时间占比 |
| 儿童友好度 | 20分 | 是否适合 5 岁儿童，有无年龄限制 |
| 饮食适配度 | 15分 | 是否适合减脂需求，菜品健康程度 |
| 多人适配度 | 15分 | 是否适合家庭/朋友多人同行 |
| 预约风险 | 10分 | 是否需要预约，排队时间长短 |

### 具体评分逻辑

- **时间合理性**：在目标时长 ±20% 范围内得满分，偏离越远扣分越多
- **距离合理性**：单程超过 max_drive_minutes 明显扣分
- **儿童友好度**：活动不适合儿童大幅扣分或剔除
- **饮食适配度**：餐厅明确减脂友好加分，重口味餐厅扣分
- **预约风险**：无需预约的活动/餐厅得满分

## 异常处理机制

### 异常场景及处理策略

| 异常场景 | 处理策略 | 配置位置 |
|----------|----------|----------|
| 餐厅满座 | 选择同商圈、同价位、儿童友好且减脂友好的备选餐厅 | `failure_fallbacks.restaurant_unavailable` |
| 活动不可预约 | 优先替换为无需预约的 citywalk、公园、商场亲子区 | `failure_fallbacks.activity_unavailable` |
| 路线过远 | 重新搜索 30 分钟车程内的活动和餐厅 | `failure_fallbacks.route_too_far` |
| 儿童不适合 | 剔除该活动或餐厅 | `failure_fallbacks.not_child_friendly` |
| 减脂不适合 | 降低该餐厅评分，优先选择轻食/粤菜/日料 | `failure_fallbacks.diet_unfriendly` |

### 用户输入缺失处理

| 缺失信息 | 处理方式 |
|----------|----------|
| 出发时间 | 默认 14:00 |
| 活动时长 | 默认 5 小时 |
| 预算 | 默认中等消费 |
| 位置 | 默认 mock_home_location |
| 同行人 | 默认家庭（2大1小） |

## 产品经理如何修改规则

### 1. 修改用户画像

**文件**: `config/product_rules.yaml`

```yaml
user_profile:
  target_user: "你的目标用户描述"
  default_scenario: "默认场景描述"
  product_positioning: "产品定位描述"
```

### 2. 修改默认出发时间

**文件**: `config/product_rules.yaml`

```yaml
defaults:
  start_time: "14:00"  # 修改这里
  duration_hours: 5
  max_drive_minutes: 30
```

### 3. 修改最大可接受车程

**文件**: `config/product_rules.yaml`

```yaml
defaults:
  max_drive_minutes: 30  # 修改这里（单位：分钟）
```

### 4. 修改评分权重

**文件**: `config/product_rules.yaml`

```yaml
scoring_weights:
  time_fit: 20           # 时间合理性权重
  distance_fit: 20       # 距离合理性权重
  child_friendly: 20     # 儿童友好度权重
  diet_friendly: 15      # 饮食适配度权重
  group_fit: 15          # 多人适配度权重
  booking_risk: 10       # 预约风险权重
```

**注意**: 所有权重之和应等于 100。

### 5. 修改异常兜底策略

**文件**: `config/product_rules.yaml`

```yaml
failure_fallbacks:
  restaurant_unavailable: "餐厅满座时的备选策略描述"
  activity_unavailable: "活动不可预约时的备选策略描述"
  route_too_far: "路线过远时的备选策略描述"
  not_child_friendly: "儿童不适合时的处理策略"
  diet_unfriendly: "饮食不适合时的处理策略"
```

### 6. 修改本地 POI seed 数据

**文件**: `data/poi_seed.yaml`

在 `activities` 或 `restaurants` 中添加/修改条目。`poi_repository.py` 会自动把 YAML 转成 `Activity` / `Restaurant` 模型，并忽略模型暂时不用的扩展字段：

```yaml
activities:
  - id: act_xxx
    name: 活动名称
    type: 活动类型
    location:
      name: 场地名称
      address: 详细地址
      district: 所在商圈
    distance_km: 5.0
    duration_minutes: 90
    suggested_duration_minutes: 90
    child_friendly: true
    group_friendly: true
    price_per_person: 80
    queue_minutes: 10
    reservation_available: true
    need_booking: true
    description: 活动描述
    tags: ["室内", "亲子"]
```

校验 seed 覆盖和字段完整性：

```bash
python3 scripts/validate_poi_seed.py
```

### 7. 修改是否需要用户确认后再执行

**文件**: `config/product_rules.yaml`

```yaml
execution_level:
  require_user_confirmation_before_booking: true  # 改为 false 则无需确认直接执行
```

### 8. 修改提示词

**文件**: `prompts.py`

如果需要使用真实 LLM 替换 mock_llm，修改 `parse_request_mock` 函数或添加新的解析函数。

### 9. 修改页面展示

**文件**: `app.py`

修改 Streamlit 页面的布局、样式、展示内容等。

### 10. 修改主流程

**文件**: `agent_harness.py`

修改 Agent 的执行流程、添加新的步骤、调整异常处理逻辑等。

## 如何运行项目

### 0. 配置 API Key（使用 LLM 功能时需要）

复制环境变量模板文件并填入你的 API Key：

```bash
cp .env.example .env
```

然后编辑 `.env` 文件，将 `DEEPSEEK_API_KEY` 替换为你的真实 Key：

```env
DEEPSEEK_API_KEY=sk-your-real-key-here
```

> ⚠️ **注意**：`.env` 已加入 `.gitignore`，不会被提交到 Git。请勿将 API Key 硬编码在代码中。

获取 DeepSeek API Key: https://platform.deepseek.com/api_keys

> 💡 项目默认使用 `mock_llm` 模式运行，无需 API Key 也可体验全部功能。只有需要使用真实 LLM 解析时才需配置。

### 1. 安装依赖

```bash
cd weekend_agent
pip install -r requirements.txt
```

### 2. 运行新的前后端分离应用

启动 Python API：

```bash
uvicorn api:app --reload --port 8000
```

另开一个终端启动前端：

```bash
cd frontend
npm install
npm run dev
```

访问地址：

```text
http://localhost:5173
```

### 3. 运行旧 Streamlit 应用

```bash
streamlit run app.py
```

### 4. 在浏览器中访问旧版本

默认地址: http://localhost:8501

### 5. 使用示例

在输入框中输入：

```
今天下午有空，想和老婆孩子出去玩几个小时，别离家太远，帮我安排一下。
```

点击「开始规划」按钮，查看 Agent 的执行过程和生成的方案。

## 如何切换 mock_llm 和真实 LLM

### 当前实现：mock_llm

项目默认使用 `prompts.py` 中的 `parse_request_mock` 函数进行规则解析，无需 LLM API Key。

### 接入真实 LLM

1. **安装 LLM SDK**

```bash
pip install openai  # 或其他 LLM SDK
```

2. **修改 prompts.py**

添加真实 LLM 调用：

```python
import openai

def parse_request_llm(user_input: str) -> Dict[str, Any]:
    """使用真实 LLM 解析用户请求"""
    client = openai.OpenAI(api_key="your-api-key")

    response = client.chat.completions.create(
        model="gpt-4",
        messages=[
            {"role": "system", "content": get_system_prompt()},
            {"role": "user", "content": user_input}
        ],
        response_format={"type": "json_object"}
    )

    return json.loads(response.choices[0].message.content)
```

3. **修改 agent_harness.py**

将 `parse_request_mock` 替换为 `parse_request_llm`：

```python
# 修改前
parsed_data = parse_request_mock(user_input)

# 修改后
parsed_data = parse_request_llm(user_input)
```

4. **配置 API Key**

推荐使用 `.env` 文件（项目启动时自动加载）：

```bash
# 复制模板文件
cp .env.example .env
# 编辑 .env，填入真实 Key
```

```env
DEEPSEEK_API_KEY=sk-your-real-key-here
```

或者直接设置环境变量：

```bash
export DEEPSEEK_API_KEY="your-api-key"
```

## 后续如何接入真实 API

### 接入真实地图 API

**修改文件**: `tools.py` 中的 `check_route_time` 函数

```python
def check_route_time(from_location: Location, to_location: Location) -> RouteInfo:
    # 使用高德/百度/腾讯地图 API
    import requests

    url = "https://restapi.amap.com/v3/direction/driving"
    params = {
        "origin": f"{from_location.coordinates['lng']},{from_location.coordinates['lat']}",
        "destination": f"{to_location.coordinates['lng']},{to_location.coordinates['lat']}",
        "key": "your-amap-key"
    }

    response = requests.get(url, params=params)
    data = response.json()

    # 解析返回结果
    route = data['route']['paths'][0]
    return RouteInfo(
        from_location=from_location,
        to_location=to_location,
        travel_minutes=int(route['duration']) // 60,
        distance_km=int(route['distance']) / 1000
    )
```

### 接入真实餐厅/活动 API

**修改文件**: 优先新增 adapter 并接入 `poi_repository.py`，不要直接把平台字段散落到 `tools.py`

```python
class AmapPoiAdapter:
    def search(self, query: str, city: str):
        # 使用官方授权 API 拉取 POI，再规范化为 Activity/Restaurant 字段
        ...
```

### 接入真实预约/下单 API

**修改文件**: `tools.py` 中的 `book_activity`, `book_restaurant`, `order_item` 函数

```python
def book_activity(activity: Activity) -> BookingResult:
    # 接入实际预约系统
    import requests

    url = "https://api.example.com/bookings"
    payload = {
        "activity_id": activity.id,
        "user_id": "current_user_id",
        # ...
    }

    response = requests.post(url, json=payload)
    # 解析返回结果
    # ...
```

### 接入真实消息 API

**修改文件**: `tools.py` 中的 `send_plan` 函数

```python
def send_plan(recipient: str, plan_summary: str) -> MessageResult:
    # 接入微信/短信/邮件 API
    import requests

    # 微信企业号示例
    url = "https://qyapi.weixin.qq.com/cgi-bin/message/send"
    payload = {
        "touser": recipient,
        "msgtype": "text",
        "text": {"content": plan_summary}
    }

    response = requests.post(url, json=payload)
    # 解析返回结果
    # ...
```

## 技术栈

- **Python 3.8+**
- **Streamlit**: Web UI 框架
- **PyYAML**: 配置文件解析
- **Dataclasses**: 结构化数据模型

## 注意事项

1. **所有外部能力均为 Mock**: 本项目所有预约、下单、发送消息操作都是模拟的，不会触发真实交易或通知
2. **无需 LLM API Key**: 默认使用规则解析，可直接运行
3. **配置文件热加载**: 修改 `product_rules.yaml` 后刷新页面即可生效

## 未来扩展方向

1. **接入真实 LLM**: 提升自然语言理解能力
2. **接入真实 API**: 地图、餐厅、票务、支付、消息
3. **用户反馈学习**: 根据用户历史选择优化推荐
4. **多轮对话**: 支持追问和信息澄清
5. **实时信息**: 接入实时排队、天气、交通信息
6. **个性化推荐**: 基于用户画像的个性化方案

## License

MIT License
