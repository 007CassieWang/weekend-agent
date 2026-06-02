"""
结构化数据模型定义
定义 Agent 使用的所有数据结构
"""

from typing import List, Optional, Dict, Any
from dataclasses import dataclass, field
from enum import Enum
from datetime import datetime


class BudgetLevel(str, Enum):
    """预算等级"""
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class ExecutionMode(str, Enum):
    """执行模式"""
    ONLY_RECOMMEND = "only_recommend"
    PLAN_THEN_CONFIRM = "plan_then_confirm"
    MOCK_EXECUTE = "mock_execute"


class CompanionsType(str, Enum):
    """同行人类型"""
    FAMILY_WITH_KIDS = "family_with_kids"      # 带儿童的家庭
    FAMILY_WITH_ELDERLY = "family_with_elderly"  # 带老人的家庭
    FAMILY_MIXED = "family_mixed"              # 既有老人又有儿童
    FRIENDS = "friends"                        # 朋友聚会
    COUPLE = "couple"                          # 情侣/夫妻
    SOLO = "solo"                              # 独自出行
    MIXED = "mixed"                            # 其他混合类型


@dataclass
class Location:
    """地理位置"""
    name: str
    address: str
    coordinates: Optional[Dict[str, float]] = None
    district: Optional[str] = None


@dataclass
class UserRequest:
    """用户请求结构"""
    # 原始输入
    raw_text: str

    # 时间相关
    time_window: Optional[str] = None
    start_time: Optional[str] = None  # 格式: "HH:MM"
    duration_hours: Optional[int] = None

    # 位置相关
    location: Optional[str] = None
    from_location: Optional[Location] = None

    # 人员相关
    people_count: Optional[int] = None
    companions: Optional[CompanionsType] = None
    child_age: Optional[int] = None
    has_child: bool = False
    has_elderly: bool = False  # 是否有老人同行

    # 偏好相关
    wife_preference: Optional[str] = None
    friends_count: Optional[int] = None
    friend_gender_structure: Optional[str] = None
    distance_preference: Optional[str] = None
    transportation: Optional[str] = None  # 通勤方式: driving/transit/taxi/bike_walk（核心槽位）
    budget_level: Optional[BudgetLevel] = None
    activity_preference: Optional[str] = None
    food_preference: Optional[str] = None
    diet_goal: str = "none"

    # 场景识别
    scenario_type: str = "general_leisure"
    activated_constraints: List[str] = field(default_factory=list)
    scoring_profile: str = "general"
    scenario_labels: Dict[str, Any] = field(default_factory=dict)
    companion_context: List[str] = field(default_factory=list)
    relation_context: List[str] = field(default_factory=list)
    primary_intent: Optional[str] = None
    context_modifiers: List[str] = field(default_factory=list)
    hard_constraints: List[str] = field(default_factory=list)
    soft_preferences: List[str] = field(default_factory=list)
    should_ask: List[str] = field(default_factory=list)
    should_not_assume: List[str] = field(default_factory=list)

    # 执行意图
    execution_intent: Optional[str] = None
    require_confirmation: bool = True

    # 解析状态
    parsed_at: Optional[datetime] = None
    missing_slots: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            "raw_text": self.raw_text,
            "time_window": self.time_window,
            "start_time": self.start_time,
            "duration_hours": self.duration_hours,
            "location": self.location,
            "people_count": self.people_count,
            "companions": self.companions.value if self.companions else None,
            "child_age": self.child_age,
            "has_child": self.has_child,
            "has_elderly": self.has_elderly,
            "transportation": self.transportation,
            "budget_level": self.budget_level.value if self.budget_level else None,
            "activity_preference": self.activity_preference,
            "food_preference": self.food_preference,
            "diet_goal": self.diet_goal,
            "scenario_type": self.scenario_type,
            "activated_constraints": self.activated_constraints,
            "scoring_profile": self.scoring_profile,
            "scenario_labels": self.scenario_labels,
            "companion_context": self.companion_context,
            "relation_context": self.relation_context,
            "primary_intent": self.primary_intent,
            "context_modifiers": self.context_modifiers,
            "hard_constraints": self.hard_constraints,
            "soft_preferences": self.soft_preferences,
            "should_ask": self.should_ask,
            "should_not_assume": self.should_not_assume,
            "execution_intent": self.execution_intent,
            "missing_slots": self.missing_slots,
        }


@dataclass
class Activity:
    """活动信息"""
    id: str
    name: str
    type: str
    location: Location
    distance_km: float
    duration_minutes: int
    suggested_duration_minutes: int

    # 适用人群
    child_friendly: bool = False
    child_min_age: Optional[int] = None
    group_friendly: bool = True

    # 费用和等待
    price_per_person: float = 0.0
    queue_minutes: int = 0

    # 预约相关
    reservation_available: bool = False
    need_booking: bool = False

    # 描述
    description: str = ""
    tags: List[str] = field(default_factory=list)

    # 当前状态
    is_available: bool = True
    current_capacity: Optional[int] = None


@dataclass
class Restaurant:
    """餐厅信息"""
    id: str
    name: str
    type: str
    cuisine_type: str
    location: Location
    distance_km: float

    # 适用人群
    child_friendly: bool = False
    diet_friendly: bool = False  # 减脂友好
    group_friendly: bool = True

    # 费用和等待
    price_per_person: float = 100.0
    queue_minutes: int = 0

    # 预约相关
    reservation_available: bool = True
    need_booking: bool = True

    # 描述
    description: str = ""
    signature_dishes: List[str] = field(default_factory=list)
    tags: List[str] = field(default_factory=list)

    # 当前状态
    is_available: bool = True
    current_capacity: Optional[int] = None


@dataclass
class RouteInfo:
    """路线信息"""
    from_location: Location
    to_location: Location
    travel_minutes: int
    distance_km: float
    transportation: str = "driving"
    traffic_condition: str = "normal"  # normal, light, heavy


@dataclass
class TimelineItem:
    """时间线项目"""
    start_time: str
    end_time: str
    activity: str
    location: str
    type: str  # "travel", "activity", "meal", "pickup", "departure"
    description: str = ""


@dataclass
class ScoreBreakdown:
    """评分细项"""
    time_fit: float = 0.0
    distance_fit: float = 0.0
    child_friendly: float = 0.0
    diet_friendly: float = 0.0
    group_fit: float = 0.0
    booking_risk: float = 0.0
    scores: Dict[str, float] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, float]:
        if self.scores:
            return self.scores
        return {
            "time_fit": self.time_fit,
            "distance_fit": self.distance_fit,
            "child_friendly": self.child_friendly,
            "diet_friendly": self.diet_friendly,
            "group_fit": self.group_fit,
            "booking_risk": self.booking_risk,
        }


@dataclass
class CandidatePlan:
    """候选方案"""
    plan_id: str
    title: str

    # 时间线
    timeline: List[TimelineItem] = field(default_factory=list)
    total_duration_minutes: int = 0

    # 活动内容
    activities: List[Activity] = field(default_factory=list)
    restaurant: Optional[Restaurant] = None
    route_infos: List[RouteInfo] = field(default_factory=list)

    # 评分
    score: float = 0.0
    score_breakdown: ScoreBreakdown = field(default_factory=ScoreBreakdown)

    # 风险和推荐理由
    risks: List[str] = field(default_factory=list)
    recommendation_reason: str = ""

    # 可行性
    is_feasible: bool = True
    infeasible_reason: Optional[str] = None


@dataclass
class BookingResult:
    """预约结果"""
    success: bool
    item_name: str
    booking_id: Optional[str] = None
    message: str = ""
    alternative_options: List[str] = field(default_factory=list)


@dataclass
class OrderResult:
    """订单结果"""
    success: bool
    item_type: str
    order_id: Optional[str] = None
    message: str = ""


@dataclass
class MessageResult:
    """消息发送结果"""
    success: bool
    recipient: str
    message: str = ""


@dataclass
class ExecutionResult:
    """执行结果"""
    # 各项执行状态
    activity_booking_status: List[BookingResult] = field(default_factory=list)
    restaurant_booking_status: Optional[BookingResult] = None
    order_status: List[OrderResult] = field(default_factory=list)
    message_status: List[MessageResult] = field(default_factory=list)

    # 执行摘要
    final_summary: str = ""
    all_succeeded: bool = False
    failed_steps: List[str] = field(default_factory=list)

    # 执行时间
    executed_at: Optional[datetime] = None


@dataclass
class AgentState:
    """Agent 执行状态"""
    # 当前步骤
    current_step: str = "idle"

    # 请求追踪
    request_id: str = ""

    # 执行日志
    logs: List[Dict[str, Any]] = field(default_factory=list)

    # 中间结果
    user_request: Optional[UserRequest] = None
    found_activities: List[Activity] = field(default_factory=list)
    found_restaurants: List[Restaurant] = field(default_factory=list)
    candidate_plans: List[CandidatePlan] = field(default_factory=list)
    selected_plan: Optional[CandidatePlan] = None
    execution_result: Optional[ExecutionResult] = None

    # 异常处理与重试
    fallback_used: bool = False
    fallback_reason: Optional[str] = None
    retry_count: int = 0
    max_retries: int = 3
    relaxed_constraints: List[str] = field(default_factory=list)

    # Draft/Commit 两阶段确认
    confirmation_status: str = "none"  # none | pending | confirmed | rejected
    confirmed_plan_id: Optional[str] = None

    # Round 2 锁定约束（来自泛方案卡片选择）
    locked_constraints: Dict[str, Any] = field(default_factory=dict)

    # 可观测性
    total_tokens: int = 0
    total_cost: float = 0.0
    llm_call_count: int = 0

    def add_log(self, step: str, message: str, details: Optional[Dict] = None):
        """添加执行日志"""
        self.logs.append({
            "timestamp": datetime.now().isoformat(),
            "request_id": self.request_id,
            "step": step,
            "message": message,
            "details": details or {}
        })
        self.current_step = step

    def record_llm_usage(self, model: str, prompt_tokens: int, completion_tokens: int):
        """记录 LLM 调用用量和估算成本"""
        self.llm_call_count += 1
        self.total_tokens += prompt_tokens + completion_tokens

        # 成本估算（RMB，按 DeepSeek 公开价格）
        pricing = {
            "deepseek-chat": (0.001, 0.002),     # 输入/输出 元/1K tokens
            "deepseek-reasoner": (0.004, 0.016),
        }
        input_price, output_price = pricing.get(model, (0.001, 0.002))
        cost = (prompt_tokens / 1000) * input_price + (completion_tokens / 1000) * output_price
        self.total_cost += cost
