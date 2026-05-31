# 活动规划 Agent 开发文档

> 版本：v1.1 | 日期：2026-05-31 | 面向：代码开发AI

---

## 一、交互流程总览

```
Round 0: 槽位初始化 → 三句小猜问
Round 1: 泛方案卡片（3张）
Round 2: 用户选择泛方案
Round 3: 具体方案输出
Round 4: 小票生成 + 分享语
Round X: 槽位补全引导（Orchestration按需插入）
```

**跳步规则**：用户信息丰富 → 槽位提前填满 → 跳过部分Round

---

## 二、槽位定义

| 槽位ID | 显示名 | 类型 | 必填 | 默认值 | 收集时机 |
|-|-|-|-|-|-|
| `group_type` | 和谁一起 | enum | 是 | - | Round 0 |
| `time_slot` | 什么时候 | enum | 是 | - | Round 0 |
| `mobility` | 怎么过去 | enum | 是 | - | Round 0 |
| `child_age` | 孩子多大 | int | 家庭场景必填 | - | Round X / 推断 |
| `max_duration` | 玩多久 | int | 否 | 4 | Round X / 推断 |
| `budget` | 预算 | int | 否 | 中等 | Round X / 推断 |
| `preference` | 特殊偏好 | string | 否 | - | Round 1 |

**枚举值定义**：

```python
GROUP_TYPE = ["家庭出行", "朋友聚会", "情侣约会", "独自一人"]
TIME_SLOT = ["今天", "明天", "本周末", "下周末", "自定义"]
MOBILITY = ["自驾", "打车", "公共交通", "无偏好"]
```

---

## 三、Round 0：槽位初始化 + 小猜问

### 3.1 输入

用户点击对话框触发，无显式输入。

### 3.2 输出

**第一层输出：三个分类选项**

```json
{
  "round": 0,
  "stage": "slot_init",
  "output_type": "slot_options",
  "data": {
    "slots": [
      {
        "slot_id": "group_type",
        "display_name": "和谁一起",
        "options": ["家庭出行", "朋友聚会", "情侣约会", "独自一人"],
        "selected": null
      },
      {
        "slot_id": "time_slot",
        "display_name": "什么时候",
        "options": ["今天", "明天", "本周末", "下周末", "自定义"],
        "selected": null
      },
      {
        "slot_id": "mobility",
        "display_name": "怎么过去",
        "options": ["自驾", "打车", "公共交通", "无偏好"],
        "selected": null
      }
    ]
  }
}
```

**用户交互**：用户依次选择三个选项。

### 3.3 第二层输出：三句小猜问

**触发条件**：用户完成三个分类选项选择。

**输入**：用户选择的槽位值

```json
{
  "user_selections": {
    "group_type": "家庭出行",
    "time_slot": "本周末",
    "mobility": "自驾"
  }
}
```

**输出**：

```json
{
  "round": 0,
  "stage": "guess_questions",
  "output_type": "mini_guess_questions",
  "data": {
    "questions": [
      {
        "q_id": "gq_1",
        "template": "我猜是{child_age_desc}，{activity_preference}？",
        "filled": "我猜是带5岁左右的孩子，想轻松一点室内玩？",
        "editable_slots": ["child_age", "activity_preference"],
        "default_values": {"child_age": 5, "activity_preference": "轻松室内"}
      },
      {
        "q_id": "gq_2",
        "template": "我猜是{child_age_desc}，{activity_preference}？",
        "filled": "我猜是带大一点的孩子，想互动参与感强一点的？",
        "editable_slots": ["child_age", "activity_preference"],
        "default_values": {"child_age": 10, "activity_preference": "互动参与"}
      },
      {
        "q_id": "gq_3",
        "template": "我猜是{child_age_desc}，{activity_preference}？",
        "filled": "我猜是趁天气好，想户外跑跑透透气？",
        "editable_slots": ["activity_preference"],
        "default_values": {"activity_preference": "户外透气"}
      }
    ],
    "hint": "点击一句最符合的，可以修改其中的关键信息"
  }
}
```

**小猜问生成逻辑**：

```python
def generate_guess_questions(slots):
    scene = slots["group_type"]
    
    if scene == "家庭出行":
        return [
            # 猜问1：低龄轻松室内
            {"template": "我猜是带{child_age}岁左右的孩子，想轻松一点室内玩？",
             "defaults": {"child_age": 5, "preference": "轻松室内"}},
            # 猜问2：学龄互动参与
            {"template": "我猜是带大一点的孩子，想互动参与感强一点的？",
             "defaults": {"child_age": 10, "preference": "互动参与"}},
            # 猜问3：户外透气
            {"template": "我猜是趁天气好，想户外跑跑透透气？",
             "defaults": {"preference": "户外透气"}}
        ]
    elif scene == "朋友聚会":
        return [
            {"template": "我猜是边走边聊，轻松漫步那种？", ...},
            {"template": "我猜是找个地方坐坐喝东西聊天？", ...},
            {"template": "我猜是一起玩点什么有参与感？", ...}
        ]
    # ... 其他场景
```

---

## 四、Round 1：泛方案卡片

### 4.1 输入

用户点击小猜问，可修改关键信息。

```json
{
  "selected_q_id": "gq_1",
  "user_modifications": {
    "child_age": 5,
    "activity_preference": "轻松室内",
    "additional_query": "老婆最近减肥，想有轻食的地方"
  }
}
```

### 4.2 Orchestration判断

```python
def orchestrate_slots_check(current_slots):
    # 检查必填槽位
    required = ["group_type", "time_slot", "mobility"]
    if current_slots["group_type"] == "家庭出行":
        required.append("child_age")
    
    missing = [s for s in required if s not in current_slots]
    
    if missing:
        return {"action": "insert_round_x", "missing_slots": missing}
    else:
        return {"action": "proceed_to_round_1"}
```

### 4.3 输出：三张泛方案卡片

```json
{
  "round": 1,
  "output_type": "template_cards",
  "data": {
    "cards": [
      {
        "card_id": "card_1",
        "title": "轻松省心 · 室内一站式",
        "description": "孩子玩得住，大人也不累，全程一个地方搞定",
        "tags": ["室内", "短车程", "低强度", "一站式"],
        "implied_constraints": {
          "intent_mode": "relax",
          "indoor_outdoor": "indoor",
          "activity_intensity": "low",
          "travel_radius": "short"
        },
        "example_content": "商场亲子乐园 / 科技馆儿童区 / 室内游乐馆 + 顺路吃饭"
      },
      {
        "card_id": "card_2",
        "title": "放电互动 · 孩子能参与",
        "description": "不是纯逛，有动手、有互动、孩子能沉浸玩",
        "tags": ["互动", "参与感", "沉浸"],
        "implied_constraints": {
          "intent_mode": "interact",
          "activity_intensity": "medium",
          "theme": "interactive"
        },
        "example_content": "儿童科学乐园 / 手作体验馆 / 互动主题展"
      },
      {
        "card_id": "card_3",
        "title": "有点特别 · 不只是遛娃",
        "description": "有新鲜感，能留下记忆点",
        "tags": ["新鲜", "小众", "记忆点"],
        "implied_constraints": {
          "intent_mode": "novelty",
          "feature": "special"
        },
        "example_content": "快闪展 / 小众主题馆 / 特色体验空间"
      }
    ]
  }
}
```

---

## 五、Round 2：用户选择泛方案

### 5.1 输入

```json
{
  "selected_card_id": "card_1",
  "user_additional_input": "想轻松一点的，最好车程别超过20分钟"
}
```

### 5.2 槽位更新

```python
def update_slots_from_card(card_id, user_input):
    card = get_card(card_id)
    
    # 合并卡片隐含约束
    locked_constraints = {
        **current_slots,
        **card["implied_constraints"],
        **parse_user_input(user_input)
    }
    
    return locked_constraints
```

### 5.3 输出

```json
{
  "round": 2,
  "output_type": "selection_confirmed",
  "data": {
    "locked_constraints": {
      "group_type": "家庭出行",
      "time_slot": "本周末",
      "mobility": "自驾",
      "child_age": 5,
      "intent_mode": "relax",
      "indoor_outdoor": "indoor",
      "activity_intensity": "low",
      "travel_radius": "short",
      "max_travel_time": 20
    },
    "next_action": "search_poi"
  }
}
```

---

## 六、Round 3：具体方案输出

### 6.1 输入

已锁定的约束条件，触发Search Skill。

### 6.2 输出

```json
{
  "round": 3,
  "output_type": "concrete_plans",
  "data": {
    "plans": [
      {
        "plan_id": "plan_1",
        "title": "自然博物馆恐龙特展 + 西单晚餐",
        "recommend_reasons": [
          "自然博物馆近期有「恐龙灭绝之谜」特展（限6.30），互动装置6个",
          "上周被小红书亲子博主刷屏",
          "西单大悦城有Wagas轻食，适合老婆减肥需求",
          "距离朝阳区出发自驾约22分钟，在20分钟半径内"
        ],
        "timeline": [
          {"time": "14:00", "action": "出发", "detail": ""},
          {"time": "14:22", "action": "到达自然博物馆", "detail": "地下停车场8元/小时"},
          {"time": "14:30-16:30", "action": "恐龙特展 + 常设展厅", "detail": "5岁能看懂讲解，6个互动装置"},
          {"time": "16:40", "action": "开车去西单大悦城", "detail": "约8分钟"},
          {"time": "17:00-18:00", "action": "晚餐", "detail": "Wagas轻食 / 西贝儿童友好"},
          {"time": "18:30", "action": "回家", "detail": "约25分钟"}
        ],
        "budget": {
          "total": "280-350元",
          "breakdown": [
            {"item": "博物馆门票", "cost": "50元/人 × 2"},
            {"item": "晚餐", "cost": "150-200元"},
            {"item": "停车费", "cost": "约30元"}
          ]
        },
        "execution_status": {
          "museum_ticket": "现场购票，周末人流适中无需预约",
          "restaurant_queue": "建议当天17:00线上取号"
        }
      },
      {
        "plan_id": "plan_2",
        "title": "朝阳大悦城悠游堂 + 西贝晚餐",
        "recommend_reasons": [
          "全程在同一个商场，不用换地方",
          "商场内有Wagas轻食和西贝儿童友好餐厅",
          "距离朝阳区出发自驾约18分钟"
        ],
        "timeline": [],
        "budget": {"total": "350-450元", "breakdown": []},
        "execution_status": {}
      }
    ]
  }
}
```

---

## 七、Round 4：小票生成 + 分享语

### 7.1 输入

```json
{
  "selected_plan_id": "plan_1",
  "user_feedback": "这个不错，就这个吧"
}
```

### 7.2 输出

```json
{
  "round": 4,
  "output_type": "receipt_card",
  "data": {
    "receipt": {
      "title": "🦕 本周末遛娃计划",
      "summary": {
        "time": "本周末 14:00出发，约5小时",
        "group": "一家三口，孩子5岁",
        "activity": "自然博物馆恐龙特展",
        "dining": "西单大悦城西贝 / Wagas轻食",
        "mobility": "自驾，单程22分钟",
        "budget": "约280-350元"
      },
      "highlights": [
        "恐龙特展限6.30，6个互动装置",
        "适合老婆减肥的轻食选择",
        "全程自驾20分钟内，轻松不累"
      ],
      "status": {
        "ticket": "✅ 现场购票",
        "restaurant": "⏰ 当天17:00提醒取号",
        "parking": "✅ 博物馆地下停车场"
      }
    },
    "share_text": "周末下午安排好了！带娃去自然博物馆看恐龙特展，听说互动装置很多应该能玩住。晚饭在西单吃，有轻食也有儿童餐。全程开车20多分钟，轻松不累。你看看行不行？",
    "actions": [
      {"action": "share_to_wechat", "label": "发给微信好友"},
      {"action": "share_to_family_group", "label": "转发家庭群"},
      {"action": "copy_text", "label": "复制分享语"}
    ]
  }
}
```

---

## 八、Round X：槽位补全引导

### 8.1 触发条件

Orchestration检测到必填槽位缺失时插入。

```python
def should_insert_round_x(current_slots, round_count):
    required = get_required_slots(current_slots["group_type"])
    missing = [s for s in required if s not in current_slots]
    
    if missing and round_count < MAX_ROUNDS:
        return True, missing
    return False, []
```

### 8.2 输出

选项引导类型：

```json
{
  "round": "X",
  "output_type": "slot_guidance",
  "data": {
    "missing_slot": "child_age",
    "display_name": "孩子多大",
    "guidance_type": "options",
    "options": [
      {"value": "3-6", "label": "3-6岁（学龄前）"},
      {"value": "7-12", "label": "7-12岁（小学）"},
      {"value": "13+", "label": "13岁以上"}
    ],
    "hint": "孩子年龄会影响活动推荐哦"
  }
}
```

自由输入类型：

```json
{
  "round": "X",
  "output_type": "slot_guidance",
  "data": {
    "missing_slot": "budget",
    "display_name": "预算范围",
    "guidance_type": "free_input",
    "placeholder": "人均预算大概多少？不填默认中等预算",
    "optional": true
  }
}
```

---

## 九、跳步逻辑

### 9.1 跳步判断

```python
def check_skip_possible(user_input, current_slots):
    # 从用户输入中提取所有可能槽位
    extracted = extract_all_slots(user_input)
    
    # 合并已有槽位
    merged = {**current_slots, **extracted}
    
    # 检查必填槽位是否齐全
    required = get_required_slots(merged.get("group_type", "general"))
    if all(s in merged for s in required):
        return {"can_skip": True, "target_round": determine_target_round(merged)}
    
    return {"can_skip": False}
```

### 9.2 跳步场景

| 用户输入特征 | 跳过Round | 直达 |
|-|-|-|
| 明确POI："去自然博物馆" | 0, 1, 2 | Round 3 |
| 明确场景+偏好："带孩子5岁去玩恐龙" | 0 | Round 1 |
| 完整信息："周六下午带孩子5岁去自然博物馆，自驾" | 0, 1 | Round 2 |

### 9.3 跳步实现

```python
def execute_skip(user_input, target_round):
    # 一次性提取所有槽位
    all_slots = extract_all_slots(user_input)
    
    if target_round == 3:
        # 直接搜索具体方案
        return search_skill.invoke(all_slots)
    elif target_round == 2:
        # 生成泛方案卡片
        return template_skill.invoke(all_slots)
    elif target_round == 1:
        # 跳过小猜问，直给卡片
        return template_skill.invoke(all_slots)
```

---

## 十、Benchmark与防死循环

### 10.1 Benchmark配置

```python
BENCHMARK = {
    "max_rounds": 8,              # 最大交互轮次
    "max_slot_guidance": 3,       # 最多Round X次数
    "max_same_question": 2,       # 相同问题最多问2次
    "timeout_per_round": 30,      # 每轮超时30秒
    "fallback_threshold": 3       # 连续失败3次触发降级
}
```

### 10.2 防死循环检测

```python
def check_loop_risk(session):
    # 1. 总轮次检测
    if session.round_count >= BENCHMARK["max_rounds"]:
        return {"action": "force_complete", "reason": "max_rounds_exceeded"}
    
    # 2. Round X次数检测
    if session.slot_guidance_count >= BENCHMARK["max_slot_guidance"]:
        return {"action": "use_defaults", "reason": "slot_guidance_exceeded"}
    
    # 3. 相同问题重复检测
    if session.last_question == session.current_question:
        session.repeat_count += 1
        if session.repeat_count >= BENCHMARK["max_same_question"]:
            return {"action": "skip_question", "reason": "question_repeated"}
    
    # 4. 用户无响应检测
    if session.no_response_count >= 2:
        return {"action": "provide_defaults", "reason": "user_inactive"}
    
    return {"action": "continue"}
```

### 10.3 降级策略

```python
def fallback_strategy(session, reason):
    if reason == "max_rounds_exceeded":
        # 强制用当前槽位输出方案
        return generate_best_effort_plan(session.current_slots)
    
    elif reason == "slot_guidance_exceeded":
        # 用默认值填充缺失槽位
        filled = fill_with_defaults(session.current_slots)
        return proceed_with_slots(filled)
    
    elif reason == "user_inactive":
        # 提供默认方案并结束
        return provide_default_plan()
```

---

## 十一、Orchestration状态机

### 11.1 状态定义

```python
class State(Enum):
    INIT = "init"                           # 初始
    SLOT_COLLECTING = "slot_collecting"     # 槽位收集中
    GUESS_QUESTIONS = "guess_questions"     # 小猜问
    TEMPLATE_CARDS = "template_cards"       # 泛方案卡片
    PLAN_SEARCHING = "plan_searching"       # 具体方案搜索中
    PLAN_SHOWN = "plan_shown"               # 具体方案展示
    RECEIPT_GENERATED = "receipt_generated" # 小票生成
    COMPLETED = "completed"                 # 完成
```

### 11.2 状态转移

```python
TRANSITIONS = {
    State.INIT: {
        "user_click": State.SLOT_COLLECTING
    },
    State.SLOT_COLLECTING: {
        "slots_filled": State.GUESS_QUESTIONS,
        "can_skip": State.TEMPLATE_CARDS,  # 跳步
        "missing_slots": State.SLOT_COLLECTING  # Round X
    },
    State.GUESS_QUESTIONS: {
        "user_select": State.TEMPLATE_CARDS,
        "can_skip": State.PLAN_SEARCHING  # 跳步
    },
    State.TEMPLATE_CARDS: {
        "user_select": State.PLAN_SEARCHING
    },
    State.PLAN_SEARCHING: {
        "search_complete": State.PLAN_SHOWN
    },
    State.PLAN_SHOWN: {
        "user_confirm": State.RECEIPT_GENERATED,
        "user_modify": State.SLOT_COLLECTING  # 回溯
    },
    State.RECEIPT_GENERATED: {
        "complete": State.COMPLETED
    }
}
```

### 11.3 回溯处理

```python
def handle_backtrack(session, modification):
    # 判断修改类型
    mod_type = classify_modification(modification)
    
    if mod_type == "minor_constraint":
        # 微调约束，局部重搜
        session.state = State.PLAN_SEARCHING
        return {"action": "re_search", "scope": "partial"}
    
    elif mod_type == "direction_change":
        # 方向变更，回到泛方案
        session.state = State.TEMPLATE_CARDS
        return {"action": "back_to_templates"}
    
    elif mod_type == "major_change":
        # 大变更，回到槽位收集
        session.state = State.SLOT_COLLECTING
        return {"action": "restart"}
```

---

## 十二、Skill调用编排

### 12.1 各Round的Skill调用

| Round | 触发Skill | 并发情况 |
|-|-|-|
| Round 0 | SlotInitSkill → GuessQuestionSkill | 串行 |
| Round 1 | TemplateSkill | 单Skill |
| Round 2 | 无（状态更新） | - |
| Round 3 | SearchSkill | 单Skill |
| Round 4 | ReceiptSkill + ShareTextSkill | 并行 |
| Round X | SlotGuidanceSkill | 单Skill |

### 12.2 并发调用示例

```python
# Round 4：小票和分享语可并行生成
async def round_4(plan, user_feedback):
    receipt_task = receipt_skill.invoke(plan)
    share_text_task = share_text_skill.invoke(plan, user_feedback)
    
    receipt, share_text = await asyncio.gather(
        receipt_task, 
        share_text_task
    )
    
    return {"receipt": receipt, "share_text": share_text}
```

---

## 十三、数据结构定义

### 13.1 SessionState

```python
@dataclass
class SessionState:
    session_id: str
    current_round: int
    current_state: State
    
    # 槽位信息
    slots: Dict[str, Any]
    locked_constraints: Dict[str, Any]
    
    # 用户选择历史
    user_selections: List[Dict]
    
    # Benchmark计数
    slot_guidance_count: int = 0
    repeat_question_count: int = 0
    no_response_count: int = 0
    
    # 方案数据
    candidate_plans: List[Dict] = None
    selected_plan: Dict = None
```

### 13.2 SlotDefinition

```python
@dataclass
class SlotDefinition:
    slot_id: str
    display_name: str
    slot_type: str  # "enum" | "int" | "string"
    required: bool
    default_value: Any
    enum_options: List[str] = None
    collect_round: str  # "round_0" | "round_x" | "infer"
```

### 13.3 Plan

```python
@dataclass
class Plan:
    plan_id: str
    title: str
    recommend_reasons: List[str]
    timeline: List[TimelineItem]
    budget: Budget
    execution_status: Dict[str, str]
```

---

## 十四、错误处理

### 14.1 错误类型

| 错误类型 | 处理方式 |
|-|-|
| 槽位提取失败 | Round X引导用户填写 |
| 搜索无结果 | 放宽约束重试 / 提示修改需求 |
| API超时 | 返回缓存 / 降级提示 |
| 用户输入无法理解 | 追问澄清 |

### 14.2 错误响应格式

```json
{
  "error": true,
  "error_type": "search_empty",
  "message": "没找到符合条件的方案",
  "fallback_options": [
    {"action": "relax_constraints", "label": "扩大搜索范围"},
    {"action": "modify_requirements", "label": "调整需求"}
  ]
}
```

---

## 十五、完整调用示例

### 场景：家庭出行完整流程

```json
// Step 1: 用户点击对话框
INPUT: {"trigger": "dialog_click"}
OUTPUT: Round 0 槽位选项

// Step 2: 用户选择槽位
INPUT: {
  "group_type": "家庭出行",
  "time_slot": "本周末",
  "mobility": "自驾"
}
OUTPUT: Round 0 三句小猜问

// Step 3: 用户点击小猜问
INPUT: {
  "selected_q_id": "gq_1",
  "modifications": {"child_age": 5}
}
OUTPUT: Round 1 三张泛方案卡片

// Step 4: 用户选择泛方案
INPUT: {"selected_card_id": "card_1"}
OUTPUT: Round 2 确认 + 触发搜索

// Step 5: 搜索完成
OUTPUT: Round 3 两套具体方案

// Step 6: 用户确认方案
INPUT: {"selected_plan_id": "plan_1"}
OUTPUT: Round 4 小票 + 分享语

// Step 7: 完成
OUTPUT: {"status": "completed"}
```

---

## 附录：配置项

```python
CONFIG = {
    # Benchmark
    "max_rounds": 8,
    "max_slot_guidance": 3,
    "timeout_per_round": 30,
    
    # 槽位
    "required_slots": {
        "家庭出行": ["group_type", "time_slot", "mobility", "child_age"],
        "朋友聚会": ["group_type", "time_slot", "mobility"],
        "情侣约会": ["group_type", "time_slot", "mobility"],
        "独自一人": ["group_type", "time_slot", "mobility"]
    },
    
    # 默认值
    "slot_defaults": {
        "child_age": 5,
        "max_duration": 4,
        "budget": "中等"
    },
    
    # 模板
    "template_cards": {
        "家庭出行": ["轻松省心", "放电互动", "有点特别"],
        "朋友聚会": ["边走边聊", "共同体验", "找个地方坐坐"],
        "情侣约会": ["浪漫氛围", "互动体验", "轻松漫步"],
        "独自一人": ["放松充电", "探索体验", "舒适休闲"]
    }
}
```
