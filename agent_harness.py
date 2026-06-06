"""
Agent Harness - 周末闲时活动规划 Agent 主流程
负责状态管理、工具调度、异常处理和执行动作

v2 更新:
- Agentic feedback loop: 搜索/构建失败时自动放宽约束重试
- Draft/Commit 分离: 方案生成与执行分离，支持用户确认后再执行
- 结构化日志与成本追踪
"""

import json
import logging
import re
import yaml
import uuid
from typing import List, Optional, Dict, Any, Tuple
from datetime import datetime, timedelta
from dataclasses import replace

from schemas import (
    UserRequest, Activity, Restaurant, RouteInfo,
    CandidatePlan, TimelineItem, ExecutionResult,
    BookingResult, OrderResult, MessageResult,
    AgentState, Location, ScoreBreakdown,
    CompanionsType, BudgetLevel
)
from tools import (
    get_user_context, search_activities, search_restaurants,
    check_route_time, check_availability, book_activity,
    book_restaurant, order_item, send_plan
)
from prompts import parse_request, get_recommendation_reason, generate_creative_title
from scoring import score_plans, calculate_plan_score

# 结构化日志
logger = logging.getLogger("weekend_agent")
logger.setLevel(logging.DEBUG)
if not logger.handlers:
    _handler = logging.StreamHandler()
    _handler.setFormatter(logging.Formatter(
        '{"ts":"%(asctime)s","lvl":"%(levelname)s","logger":"%(name)s",%(message)s}',
        datefmt="%Y-%m-%dT%H:%M:%S",
    ))
    logger.addHandler(_handler)

# 质量门禁阈值
QUALITY_SCORE_THRESHOLD = 55  # 低于此分触发重试
MAX_SEARCH_RETRIES = 3

# 场景偏好排序配置（模块级常量，避免每次调用 _sort_supply_by_scenario 时重建）
SCENARIO_PREFERENCES = {
    "elderly_friendly": {
        "restaurants": ["cantonese", "chinese", "japanese", "light_meal", "粤菜", "中餐", "日料"],
        "activities": ["botanical_garden", "park", "citywalk", "cafe", "art_exhibition", "museum"],
        "avoid": ["hotpot", "bbq", "korean", "livehouse", "hiking", "sports", "火锅", "烧烤", "韩料"],
    },
    "couple_date": {
        "restaurants": ["japanese", "cantonese", "thai", "western", "日料", "粤菜", "泰式", "西餐"],
        "activities": ["cafe", "citywalk", "art_exhibition", "botanical_garden", "onsen"],
        "avoid": ["food_court", "board_game", "ktv", "hotpot", "综合"],
    },
    "solo_relax": {
        "restaurants": ["cafe", "japanese", "light_meal", "日料", "轻食"],
        "activities": ["cafe", "citywalk", "park", "art_exhibition", "museum"],
        "avoid": ["ktv", "hotpot", "bbq"],
    },
    "active_outdoor": {
        "restaurants": ["barbecue", "casual", "cafe", "chinese", "烧烤", "中餐", "西餐"],
        "activities": ["park", "hiking", "citywalk", "botanical_garden", "onsen"],
        "avoid": ["mall", "ktv", "cinema", "indoor_playground", "board_game", "livehouse", "商场", "KTV"],
    },
}


def _is_same_location(loc_a, loc_b) -> bool:
    """判断两个地点是否相同（名称或地址匹配）。"""
    if not loc_a or not loc_b:
        return False
    name_a = (loc_a.name or "").strip()
    name_b = (loc_b.name or "").strip()
    addr_a = (getattr(loc_a, "address", "") or "").strip()
    addr_b = (getattr(loc_b, "address", "") or "").strip()
    # 名称相同 或 名称包含对方 或 地址相同
    if name_a == name_b:
        return True
    if name_a and name_b and (name_a in name_b or name_b in name_a):
        return True
    if addr_a and addr_b and addr_a == addr_b:
        return True
    return False


def _resolve_time_slot(time_slot: Optional[str]) -> Dict[str, Any]:
    """
    根据用户选择的时间槽位，推断合理的开始时间和时长。

    Args:
        time_slot: 用户选择的时间槽位 (morning/afternoon/full_day/now)

    Returns:
        {"start_time": "HH:MM", "duration_hours": int} 或 {}
    """
    if not time_slot:
        return {}

    now = datetime.now()
    current_hour = now.hour

    if time_slot == "morning":
        # 上午出发，如果已经过了上午则默认明天上午
        return {"start_time": "09:00", "duration_hours": 5}
    elif time_slot == "afternoon":
        return {"start_time": "14:00", "duration_hours": 5}
    elif time_slot == "full_day":
        # 全天：从上午开始，8-10 小时，覆盖午餐+活动+晚餐
        return {"start_time": "09:00", "duration_hours": 9}
    elif time_slot == "now":
        # 现在就出发
        hour_str = f"{current_hour:02d}:00" if current_hour < 20 else "14:00"
        return {"start_time": hour_str, "duration_hours": 5}
    elif time_slot == "今天":
        # 如果是上午则现在出发，下午则下午开始
        if current_hour < 12:
            return {"start_time": f"{current_hour + 1:02d}:00", "duration_hours": max(4, 18 - current_hour)}
        else:
            return {"start_time": "14:00", "duration_hours": 4}
    elif time_slot == "明天":
        return {"start_time": "09:00", "duration_hours": 6}
    elif time_slot in ("本周末", "下周末"):
        return {"start_time": "10:00", "duration_hours": 8}

    return {}


def _enrich_restaurant_dict(base: Optional[Dict[str, Any]], recommendations: list) -> Optional[Dict[str, Any]]:
    """为餐厅 dict 附加 recommendations 字段。"""
    if base is None:
        return None
    return {**base, "recommendations": recommendations}


class WeekendActivityAgent:
    """周末闲时活动规划 Agent"""

    def __init__(self):
        self.state = AgentState()
        self.state.request_id = uuid.uuid4().hex[:12]
        self.product_rules = self._load_product_rules()

    def _load_product_rules(self) -> Dict[str, Any]:
        """加载产品规则配置"""
        try:
            with open("config/product_rules.yaml", "r", encoding="utf-8") as f:
                return yaml.safe_load(f)
        except Exception as e:
            logger.warning("product_rules.yaml 加载失败，使用默认配置", extra={"error": str(e)})
            return {
                "defaults": {
                    "start_time": "14:00",
                    "duration_hours": 4,
                    "max_drive_minutes": 30,
                    "budget_level": "medium",
                    "companions": "unknown",
                    "child_age": None,
                    "diet_goal": "none"
                },
                "execution_level": {
                    "require_user_confirmation_before_booking": True,
                    "allow_mock_booking": True,
                    "allow_mock_order": True,
                    "allow_mock_send_message": True
                },
                "failure_fallbacks": {
                    "restaurant_unavailable": "选择同商圈、同价位的备选餐厅",
                    "activity_unavailable": "优先替换为无需预约的 citywalk、公园或商场综合体",
                    "route_too_far": "重新搜索 30 分钟车程内的活动和餐厅",
                }
            }

    def _log(self, step: str, message: str, details: Optional[Dict] = None, level: str = "info"):
        """结构化日志记录"""
        self.state.add_log(step, message, details)
        log_data = json.dumps({
            "rid": self.state.request_id,
            "step": step,
            "msg": message,
            "details": details or {},
        }, ensure_ascii=False)
        log_method = getattr(logger, level, logger.info)
        log_method(log_data)

    # ==================== Step 1: 解析请求 ====================

    def parse_request(self, user_input: str) -> UserRequest:
        """
        解析用户自然语言请求

        Args:
            user_input: 用户输入的自然语言

        Returns:
            结构化的用户请求
        """
        self._log("parse_request", f"正在解析用户请求: {user_input[:50]}...")

        # 使用统一入口解析（优先 LLM，fallback mock）
        parsed_data = parse_request(user_input)

        # 记录解析器来源
        parser_info = parsed_data.get("parser", "unknown")
        parse_error = parsed_data.get("parse_error")
        if parse_error:
            self._log("parse_request", f"LLM 解析失败，已 fallback 到 mock: {parse_error}")
        else:
            self._log("parse_request", f"使用解析器: {parser_info}")

        # 置信度检查（仅 LLM 解析时有此字段）
        confidence = parsed_data.get("confidence")
        if confidence is not None:
            threshold = self.product_rules.get("scenario_detection", {}).get("confidence_threshold", 0.55)
            if confidence < threshold:
                self._log("parse_request", f"LLM 置信度较低 ({confidence:.2f} < {threshold})，结果可能不准确")

        # 将字符串转换为枚举类型
        companions_str = parsed_data.get("companions")
        companions_enum = None
        if companions_str:
            try:
                companions_enum = CompanionsType(companions_str)
            except ValueError:
                companions_enum = None

        budget_str = parsed_data.get("budget_level")
        budget_enum = None
        if budget_str:
            try:
                budget_enum = BudgetLevel(budget_str)
            except ValueError:
                budget_enum = None

        # 创建 UserRequest 对象
        request = UserRequest(
            raw_text=user_input,
            time_window=parsed_data.get("time_window"),
            start_time=parsed_data.get("start_time"),
            duration_hours=parsed_data.get("duration_hours"),
            location=parsed_data.get("location"),
            people_count=parsed_data.get("people_count"),
            companions=companions_enum,
            child_age=parsed_data.get("child_age"),
            has_child=parsed_data.get("has_child", False),
            has_elderly=parsed_data.get("has_elderly", False),
            distance_preference=parsed_data.get("distance_preference"),
            transportation=parsed_data.get("transportation"),
            budget_level=budget_enum,
            activity_preference=parsed_data.get("activity_preference"),
            food_preference=parsed_data.get("food_preference"),
            diet_goal=parsed_data.get("diet_goal", "none"),
            scenario_type=parsed_data.get("scenario_type", "general_leisure"),
            activated_constraints=parsed_data.get("activated_constraints", []),
            scoring_profile=parsed_data.get("scoring_profile", "general"),
            scenario_labels=parsed_data.get("scenario_labels", {}),
            companion_context=parsed_data.get("companion_context", []),
            relation_context=parsed_data.get("relation_context", []),
            primary_intent=parsed_data.get("primary_intent"),
            context_modifiers=parsed_data.get("context_modifiers", []),
            hard_constraints=parsed_data.get("hard_constraints", []),
            soft_preferences=parsed_data.get("soft_preferences", []),
            should_ask=parsed_data.get("should_ask", []),
            should_not_assume=parsed_data.get("should_not_assume", []),
            execution_intent=parsed_data.get("execution_intent"),
            parsed_at=datetime.now(),
            missing_slots=parsed_data.get("missing_slots", [])
        )

        self.state.user_request = request
        self._log(
            "parse_request",
            f"解析完成: {request.people_count}人, 时长{request.duration_hours}小时, "
            f"同伴类型: {request.companions}, 场景: {request.scenario_type}",
            request.to_dict()
        )

        return request

    # ==================== Step 2: 补全缺失信息 ====================

    def complete_missing_slots(self, request: UserRequest) -> UserRequest:
        """
        根据产品规则补全缺失信息。
        优先使用 locked_constraints（Round 2 锁定约束）作为默认值来源。

        Args:
            request: 用户请求

        Returns:
            补全后的用户请求
        """
        self._log("complete_missing_slots", "正在补全缺失信息...")

        defaults = self.product_rules.get("defaults", {})
        clarification = self.product_rules.get("clarification_rules", {})
        default_when_missing = clarification.get("default_when_missing", {})
        locked = getattr(self.state, "locked_constraints", {}) or {}

        # ── 根据用户选择的时间槽位推断开始时间和时长 ──
        # 多源检测：locked_constraints.time_slot → time_window → request.time_window → raw_text
        time_slot = (
            locked.get("time_slot") or
            locked.get("time_window") or
            request.time_window
        )

        # 兜底：从原始消息中检测"全天"关键词
        if not time_slot and request.raw_text:
            raw = request.raw_text
            if any(kw in raw for kw in ["全天", "一整天", "整天", "full_day", "泡一天"]):
                time_slot = "full_day"
                self._log("complete_missing_slots", f"从 raw_text 检测到全天意图: '{raw[:80]}'")

        time_slot_defaults = _resolve_time_slot(time_slot)

        # 用户通过结构化槽位明确选了时间 → 强制覆盖（parse_request 的默认值 4h 不优先）
        if time_slot and time_slot_defaults:
            if time_slot_defaults.get("start_time"):
                request.start_time = time_slot_defaults["start_time"]
                self._log("complete_missing_slots", f"槽位覆盖开始时间: {request.start_time} (time_slot={time_slot})")
            if time_slot_defaults.get("duration_hours"):
                request.duration_hours = time_slot_defaults["duration_hours"]
                self._log("complete_missing_slots", f"槽位覆盖时长: {request.duration_hours}小时 (time_slot={time_slot})")

        # 同步 time_window 到 request，确保下游 is_full_day 检测一致
        if time_slot and not request.time_window:
            request.time_window = time_slot

        self._log("complete_missing_slots",
                  f"最终时间参数: start={request.start_time}, duration={request.duration_hours}h, "
                  f"time_window={request.time_window}, time_slot_source={time_slot}")

        # 补全各个字段（仅在槽位未覆盖时才用默认值）
        if not request.start_time:
            request.start_time = (
                default_when_missing.get("exact_start_time") or
                defaults.get("start_time", "14:00")
            )
            self._log("complete_missing_slots", f"使用默认开始时间: {request.start_time}")

        if not request.duration_hours:
            request.duration_hours = (
                default_when_missing.get("duration_hours") or
                defaults.get("duration_hours", 4)
            )
            self._log("complete_missing_slots", f"使用默认时长: {request.duration_hours}小时")

        if not request.budget_level:
            budget_str = default_when_missing.get("budget_level", defaults.get("budget_level", "medium"))
            try:
                request.budget_level = BudgetLevel(budget_str)
            except ValueError:
                request.budget_level = BudgetLevel.MEDIUM

        if not request.location:
            request.location = defaults.get("default_location", "mock_home_location")
            # 获取用户上下文中的位置信息
            user_context = get_user_context()
            request.from_location = user_context.get("home_location")

        if not request.people_count:
            default_people_count = default_when_missing.get("people_count", defaults.get("people_count"))
            if default_people_count:
                request.people_count = default_people_count

        if not request.companions:
            companions_str = default_when_missing.get("companions", defaults.get("companions"))
            if companions_str and companions_str != "unknown":
                try:
                    request.companions = CompanionsType(companions_str)
                except ValueError:
                    request.companions = None

        if not request.distance_preference:
            request.distance_preference = "nearby"

        # 应用 locked_constraints（Round 2 锁定约束）中的值
        if locked:
            if locked.get("travel_radius") == "short" and not request.distance_preference:
                request.distance_preference = "nearby"
            if locked.get("travel_radius") == "far":
                request.distance_preference = "far"
            # 预算：支持 budget 和 budget_level 两种 key（兼容不同来源）
            budget_val = locked.get("budget_level") or locked.get("budget")
            if budget_val and not request.budget_level:
                budget_map = {"low": BudgetLevel.LOW, "medium": BudgetLevel.MEDIUM, "medium_high": BudgetLevel.MEDIUM, "high": BudgetLevel.HIGH}
                if mapped := budget_map.get(str(budget_val).lower() if budget_val else ""):
                    request.budget_level = mapped
                    self._log("complete_missing_slots", f"locked_constraints 覆盖 budget_level: {budget_val} → {mapped}")
            # 同行人类型映射：group_type（中文字符串）→ CompanionsType
            group_type = locked.get("group_type", "")
            if group_type and not request.companions:
                group_map = {
                    "家庭出行": CompanionsType.FAMILY_WITH_KIDS,
                    "朋友聚会": CompanionsType.FRIENDS,
                    "情侣约会": CompanionsType.COUPLE,
                    "独自一人": CompanionsType.SOLO,
                }
                if mapped_companion := group_map.get(group_type):
                    request.companions = mapped_companion
                    self._log("complete_missing_slots", f"locked_constraints 覆盖 companions: {group_type} → {mapped_companion}")
            # 活动偏好：activity_preference（如 "indoor"/"outdoor"）
            if locked.get("activity_preference") and not request.activity_preference:
                request.activity_preference = locked["activity_preference"]
            if locked.get("intent_mode") and not request.activity_preference:
                intent_to_activity = {
                    "relax": "relax", "interact": "entertainment", "novelty": "art",
                    "explore": "outdoor", "romantic": "celebration", "dining": "food",
                }
                if activity := intent_to_activity.get(locked["intent_mode"]):
                    request.activity_preference = activity
            if locked.get("max_travel_time") and locked.get("max_travel_time", 0) < 30:
                request.distance_preference = "nearby"

            # 合并 locked_constraints 中的 context_modifiers 和 hard_constraints 到 request
            if locked.get("context_modifiers"):
                existing_mods = set(request.context_modifiers or [])
                for mod in locked["context_modifiers"]:
                    if mod not in existing_mods:
                        request.context_modifiers.append(mod)
            if locked.get("hard_constraints"):
                existing_hards = set(request.hard_constraints or [])
                for hc in locked["hard_constraints"]:
                    if hc not in existing_hards:
                        request.hard_constraints.append(hc)

        self._log("complete_missing_slots", "信息补全完成", request.to_dict())

        return request

    # ==================== Step 3: 搜索活动（支持重试放宽） ====================

    def _get_search_params(self, request: UserRequest, overrides: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """构建搜索参数，支持重试时逐步放宽约束。"""
        overrides = overrides or {}
        defaults = self.product_rules.get("defaults", {})
        max_drive = overrides.get("max_drive_minutes", defaults.get("max_drive_minutes", 30))
        return {
            "location": request.location or "home",
            "child_age": request.child_age if (request.has_child and not overrides.get("drop_child_filter")) else None,
            "duration_hours": request.duration_hours or defaults.get("duration_hours", 4),
            "max_drive_minutes": max_drive,
            "preferences": {
                "activity_style": request.activity_preference,
                "budget": request.budget_level,
            },
        }

    def search_activities(self, request: UserRequest, overrides: Optional[Dict[str, Any]] = None) -> List[Activity]:
        """
        搜索附近适合的活动

        Args:
            request: 用户请求
            overrides: 搜索参数覆盖（用于重试放宽）

        Returns:
            活动列表
        """
        overrides = overrides or {}
        params = self._get_search_params(request, overrides)
        self._log("search_activities", f"正在搜索附近活动 (max_drive={params['max_drive_minutes']}min)...")

        activities = search_activities(**params)
        activities = self._sort_supply_by_scenario(
            self._filter_supply_by_scenario(activities, request),
            request,
        )

        self.state.found_activities = activities
        self._log("search_activities", f"找到 {len(activities)} 个符合条件的活动")

        return activities

    # ==================== Step 4: 搜索餐厅（支持重试放宽） ====================

    # 用户 food_preference → 中文菜系关键词的映射，与 data/poi_seed.yaml 中的 cuisine_type 对齐
    CUISINE_KEYWORD_MAP: Dict[str, List[str]] = {
        "hotpot": ["火锅"],
        "火锅": ["火锅"],
        "cantonese": ["粤菜", "本帮菜"],
        "粤菜": ["粤菜", "本帮菜"],
        "japanese": ["日料"],
        "日料": ["日料"],
        "sushi": ["日料"],
        "spicy": ["火锅", "烧烤", "小吃", "夜宵"],
        "western": ["西餐"],
        "西餐": ["西餐"],
        "牛排": ["西餐"],
        "chinese": ["粤菜", "本帮菜", "火锅", "中餐"],
        "中餐": ["粤菜", "本帮菜", "火锅"],
        "healthy": ["轻食", "健康餐", "日料"],
        "轻食": ["轻食", "健康餐"],
        "korean": ["韩料"],
        "韩料": ["韩料"],
        "barbecue": ["烧烤"],
        "烧烤": ["烧烤"],
        "cafe": ["咖啡", "茶馆", "甜品"],
        "咖啡": ["咖啡"],
        "下午茶": ["茶馆", "甜品", "咖啡"],
        "seafood": ["粤菜", "日料"],
        "小吃": ["小吃", "夜宵"],
        "甜品": ["甜品"],
        "本帮菜": ["本帮菜", "粤菜"],
        "东南亚": ["东南亚"],
        "thai": ["东南亚"],
        "茶馆": ["茶馆", "咖啡"],
    }

    @classmethod
    def _resolve_cuisine_keywords(cls, request: UserRequest) -> List[str]:
        """从 request 中提取菜系关键词，用于 search_restaurants 的 cuisine 过滤。"""
        keywords: List[str] = []

        # 1. 优先从 food_preference 字段提取
        fp = request.food_preference
        if fp and fp != "none":
            mapped = cls.CUISINE_KEYWORD_MAP.get(fp.lower() if fp else "", [fp])
            keywords.extend(mapped)

        # 2. 从 context_modifiers 中提取菜系 hint
        for mod in (request.context_modifiers or []):
            mapped = cls.CUISINE_KEYWORD_MAP.get(mod, [])
            if mapped and mapped != [mod]:
                keywords.extend(mapped)

        # 3. 从 raw_text 中提取已知菜系关键词
        raw = (request.raw_text or "").lower()
        for key, mapped in cls.CUISINE_KEYWORD_MAP.items():
            if len(key) >= 2 and key in raw and key not in ("chinese", "spicy", "healthy", "western", "cantonese", "japanese", "korean", "barbecue", "sushi", "thai", "seafood"):
                keywords.extend(mapped)

        # 去重且保留顺序
        seen = set()
        result = []
        for kw in keywords:
            if kw not in seen:
                seen.add(kw)
                result.append(kw)
        return result

    def search_restaurants(self, request: UserRequest, overrides: Optional[Dict[str, Any]] = None) -> List[Restaurant]:
        """
        搜索适合的餐厅

        Args:
            request: 用户请求
            overrides: 搜索参数覆盖（用于重试放宽）

        Returns:
            餐厅列表
        """
        overrides = overrides or {}
        defaults = self.product_rules.get("defaults", {})
        max_drive = overrides.get("max_drive_minutes", defaults.get("max_drive_minutes", 30))

        # 从 request 中提取菜系关键词
        cuisine_keywords = self._resolve_cuisine_keywords(request)

        self._log("search_restaurants",
                  f"正在搜索餐厅 (max_drive={max_drive}min, cuisine={cuisine_keywords}, budget={request.budget_level})...")

        restaurants = search_restaurants(
            location=request.location or "home",
            people_count=request.people_count or 1,
            diet_friendly=(request.scenario_type == "health_diet" or request.diet_goal != "none") and not overrides.get("drop_diet_filter"),
            child_friendly=request.has_child and not overrides.get("drop_child_filter"),
            group_friendly=bool(request.people_count and request.people_count > 2),
            max_drive_minutes=max_drive,
            cuisine_keywords=cuisine_keywords,
            budget_level=request.budget_level.value if request.budget_level else None,
        )
        restaurants = self._sort_supply_by_scenario(
            self._filter_supply_by_scenario(restaurants, request),
            request,
            cuisine_keywords=cuisine_keywords,
        )

        self.state.found_restaurants = restaurants
        self._log("search_restaurants", f"找到 {len(restaurants)} 家符合条件的餐厅")

        return restaurants

    def _filter_supply_by_scenario(self, items: List[Any], request: UserRequest) -> List[Any]:
        """过滤明显不匹配当前场景的供给，避免非亲子场景返回亲子主题结果。"""
        if request.has_child or request.scenario_type == "family_with_children":
            return items

        child_theme_terms = ["亲子", "儿童乐园", "宝宝", "童话", "游乐区", "儿童餐"]
        family_theme_terms = ["家庭餐厅", "家庭路", "儿童娱乐区", "儿童套餐"]
        all_theme_terms = child_theme_terms + family_theme_terms  # hoisted: 避免循环内重复拼接
        filtered = []
        for item in items:
            text_parts = [
                getattr(item, "name", ""),
                getattr(item, "type", ""),
                getattr(item, "cuisine_type", ""),
                " ".join(getattr(item, "signature_dishes", []) or []),
            ]
            if isinstance(item, Restaurant):
                text_parts.extend([
                    getattr(item, "description", ""),
                    " ".join(getattr(item, "tags", []) or []),
                ])
            text = " ".join(text_parts)
            if any(term in text for term in all_theme_terms):
                continue
            filtered.append(item)

        return filtered or items

    def _sort_supply_by_scenario(
        self, items: List[Any], request: UserRequest,
        cuisine_keywords: Optional[List[str]] = None,
    ) -> List[Any]:
        """按当前场景重排供给，候选构建阶段会优先取更匹配的前几项。"""
        if not items:
            return items

        prefs = SCENARIO_PREFERENCES.get(request.scenario_type)
        cuisine_lower = [kw.strip().lower() for kw in (cuisine_keywords or []) if kw]

        modifiers = set(request.context_modifiers or [])
        hard_constraints = set(request.hard_constraints or [])
        locked = getattr(self.state, "locked_constraints", {}) or {}

        def rank(item: Any) -> tuple:
            item_type = getattr(item, "type", "")
            cuisine = getattr(item, "cuisine_type", "")
            name = getattr(item, "name", "")
            tags = " ".join(getattr(item, "tags", []) or [])
            category = getattr(item, "poi_category", "")
            risks = getattr(item, "risk_tags", []) or []
            text = " ".join([item_type, cuisine, name, tags, category, " ".join(risks)])
            preferred = []
            avoid = []
            if prefs:
                preferred = prefs["restaurants"] if isinstance(item, Restaurant) else prefs["activities"]
                avoid = prefs.get("avoid", [])
            avoid_penalty = 100 if any(term in text for term in avoid) else 0
            preferred_rank = 0 if any(term in text for term in preferred) else 20
            label_penalty = 0
            label_bonus = 0

            # 菜系匹配信号：精确匹配加 -50（排序值越小越靠前），模糊匹配加 -20
            cuisine_match_bonus = 0
            if cuisine_lower:
                ct = (cuisine or "").lower()
                ct_parts = [p.strip() for p in ct.replace("/", " ").split()]
                for kw in cuisine_lower:
                    if kw == ct or kw in ct_parts:
                        cuisine_match_bonus = -50  # 精确菜系匹配，大幅提升
                        break
                    elif kw in ct:
                        cuisine_match_bonus = -20  # 模糊菜系匹配

            # locked_constraints 影响排序
            if locked.get("indoor_outdoor") == "indoor" and getattr(item, "indoor_outdoor", "") == "outdoor":
                label_penalty += 50
            if locked.get("indoor_outdoor") == "outdoor" and getattr(item, "indoor_outdoor", "") == "indoor":
                label_penalty += 50
            # Round 1 自由文本路径：locked_constraints 未设置时从 request 属性推断
            if not locked.get("indoor_outdoor"):
                activity_pref = getattr(request, "activity_preference", None)
                primary_intent = getattr(request, "primary_intent", None)
                if activity_pref == "outdoor" or primary_intent == "outdoor_walk":
                    if getattr(item, "indoor_outdoor", "") == "indoor":
                        label_penalty += 50
            if locked.get("activity_intensity") == "low" and getattr(item, "walking_load", "") == "high":
                label_penalty += 40

            if "rainy_day" in modifiers and getattr(item, "indoor_outdoor", "") == "outdoor":
                label_penalty += 45
            if "low_energy" in modifiers or "low_walking" in modifiers or "elder_mobility" in hard_constraints:
                walking_load = getattr(item, "walking_load", "")
                if walking_load == "high":
                    label_penalty += 45
                elif walking_load == "medium":
                    label_penalty += 18
                elif walking_load == "low":
                    label_bonus += 15
            if "quiet" in modifiers and getattr(item, "noise_level", "") == "high":
                label_penalty += 35
            if "pet_allowed" in hard_constraints:
                if getattr(item, "pet_friendly", False):
                    label_bonus += 40
                else:
                    label_penalty += 70
            if "no_reservation" in modifiers and getattr(item, "need_booking", False):
                label_penalty += 40
            if "queue_sensitive" in modifiers and (
                getattr(item, "queue_minutes", 0) > 10 or "排队" in risks
            ):
                label_penalty += 35
            if "low_budget" in modifiers or "budget_cap" in hard_constraints:
                price = float(getattr(item, "price_per_person", 0) or 0)
                if isinstance(item, Restaurant):
                    if price > 120:
                        label_penalty += 35
                    elif price <= 90:
                        label_bonus += 15
                else:
                    if price > 120:
                        label_penalty += 30
                    elif price <= 80:
                        label_bonus += 12
            if "photo_spot" in modifiers and getattr(item, "photo_spot", False):
                label_bonus += 20
            if "near_subway" in modifiers and getattr(item, "near_subway", False):
                label_bonus += 18
            if "parking_needed" in modifiers and getattr(item, "parking_available", False):
                label_bonus += 18

            # GUESS_CARD 地点锁定：优先选择位于锁定地点附近的供给
            must_loc = locked.get("must_include_location", "")
            if must_loc:
                loc = getattr(item, "location", None)
                loc_district = getattr(loc, "district", "") if loc else ""
                loc_addr = getattr(loc, "address", "") if loc else ""
                item_name = getattr(item, "name", "")
                item_desc = getattr(item, "description", "")
                item_tags = " ".join(getattr(item, "tags", []) or [])
                item_text = f"{loc_district} {loc_addr} {item_name} {item_desc} {item_tags}"
                if must_loc in item_text:
                    label_bonus += 80  # 强力优先：确保猜问卡提及的地点/餐厅排在最前面

            return (
                avoid_penalty + preferred_rank + label_penalty - label_bonus + cuisine_match_bonus,
                getattr(item, "distance_km", 999),
            )

        return sorted(items, key=rank)

    # ==================== Step 5: 检查路线 ====================

    def check_route_time(
        self,
        from_loc: Location,
        to_loc: Location
    ) -> RouteInfo:
        """
        检查路线时间

        Args:
            from_loc: 起点
            to_loc: 终点

        Returns:
            路线信息
        """
        return check_route_time(from_loc, to_loc, "driving")

    # ==================== Step 6: 构建候选方案 ====================

    def build_candidate_plans(
        self,
        request: UserRequest,
        activities: List[Activity],
        restaurants: List[Restaurant]
    ) -> List[CandidatePlan]:
        """
        构建候选方案

        Args:
            request: 用户请求
            activities: 活动列表
            restaurants: 餐厅列表

        Returns:
            候选方案列表
        """
        self._log("build_candidate_plans", "正在构建候选方案...")

        plans = []

        # 如果没有找到足够的活动或餐厅，使用备选
        if len(activities) < 2:
            self._log("build_candidate_plans", "活动数量不足，添加备选活动")
            activities = activities + self._get_fallback_activities()

        if len(restaurants) < 2:
            self._log("build_candidate_plans", "餐厅数量不足，添加备选餐厅")
            restaurants = restaurants + self._get_fallback_restaurants()

        # 获取用户位置
        home_location = request.from_location or get_user_context().get("home_location")

        # 判断是否全天模式
        locked = getattr(self.state, "locked_constraints", {}) or {}

        # GUESS_CARD 地点锁定：确保 must_include_location 对应的地点进入活动列表
        must_loc = locked.get("must_include_location", "")
        if must_loc:
            # 活动：匹配 → 提升到最前；不匹配 → 创建合成活动
            matched_acts = []
            other_acts = []
            for a in activities:
                if must_loc in (a.name or "") or must_loc in (a.location.name or ""):
                    matched_acts.append(a)
                else:
                    other_acts.append(a)
            if matched_acts:
                activities = matched_acts + other_acts
                self._log("build_candidate_plans", f"GUESS_CARD 地点 '{must_loc}' 匹配 {len(matched_acts)} 个活动，已提升到最前")
            else:
                # 创建合成活动，确保方案中一定包含该地点
                synthetic = Activity(
                    id=f"guesscard_{must_loc}",
                    name=must_loc,
                    type="citywalk" if "公园" in must_loc or "路" in must_loc else "cultural_site",
                    location=Location(name=must_loc, address=must_loc, district=""),
                    distance_km=4.0,
                    duration_minutes=90,
                    suggested_duration_minutes=90,
                    child_friendly=True,
                    group_friendly=True,
                    price_per_person=0,
                    reservation_available=False,
                    need_booking=False,
                    description=f"精选推荐地点：{must_loc}，一个值得探索的好去处",
                    tags=["拍照打卡"] if "公园" in must_loc or "上生" in must_loc else [],
                )
                activities = [synthetic] + list(activities)
                self._log("build_candidate_plans", f"GUESS_CARD 锁定地点 '{must_loc}' 已添加为合成活动")

            # 餐厅：匹配 → 提升到最前，确保 plan builder 的 restaurants[:2] 能选中
            matched_rests = []
            other_rests = []
            for r in restaurants:
                loc_text = f"{r.name} {(r.location.name or '')} {(r.location.address or '')} {(r.location.district or '')} {getattr(r, 'description', '')}"
                if must_loc in loc_text:
                    matched_rests.append(r)
                else:
                    other_rests.append(r)
            if matched_rests:
                restaurants = matched_rests + other_rests
                self._log("build_candidate_plans", f"GUESS_CARD 地点 '{must_loc}' 匹配 {len(matched_rests)} 家餐厅: {[r.name for r in matched_rests]}")
            else:
                self._log("build_candidate_plans", f"GUESS_CARD 地点 '{must_loc}' 未匹配任何餐厅，将继续使用搜索结果", level="warning")

        # ── GUESS_CARD 保证项：确保 guaranteed_activities / guaranteed_restaurants 必出 ──
        # 这些是从 GUESS_CARD 的 implied_constraints 传入的，描述了开屏卡片中展示的具体 POI。
        # 逻辑：尝试在搜索结果中匹配；匹配到就提升到最前，没匹配到就创建合成 POI 注入。
        guaranteed_activities: List[Dict[str, Any]] = locked.get("guaranteed_activities", []) or []
        guaranteed_restaurants_list: List[Dict[str, Any]] = locked.get("guaranteed_restaurants", []) or []

        for ga in guaranteed_activities:
            ga_name = str(ga.get("name", "") or "")
            ga_type = str(ga.get("type", "") or "")
            ga_location = str(ga.get("location_hint", "") or "")
            ga_tags = [t for t in list(ga.get("tags", []) or []) if isinstance(t, str)]
            ga_desc = str(ga.get("description", "") or "")
            ga_duration = int(ga.get("duration_minutes", 90))

            # 尝试匹配：name 或 type+location_hint 出现在现有活动中
            matched_acts = []
            other_acts = []
            for a in activities:
                a_name = str(getattr(a, "name", "") or "")
                a_type = str(getattr(a, "type", "") or "")
                a_loc_addr = str(getattr(a, "location", None).address if getattr(a, "location", None) else "")
                a_loc_district = str(getattr(a, "location", None).district if getattr(a, "location", None) else "")
                a_text = f"{a_name} {a_type} {a_loc_addr} {a_loc_district}"
                # 匹配策略：名称相似 / 地点关键词在地址中 / 类型一致 + 地点包含
                loc_match = bool(ga_location) and (
                    ga_location in a_loc_addr or ga_location in a_loc_district or ga_location in a_name)
                type_match = bool(ga_type) and ga_type in a_type
                name_overlap = bool(ga_name) and any(
                    len(part) >= 2 and part in a_name for part in ga_name.replace("·", " ").replace("「", "").replace("」", "").split())
                if name_overlap or (type_match and loc_match) or (ga_name and ga_name in a_text):
                    matched_acts.append(a)
                else:
                    other_acts.append(a)
            if matched_acts:
                activities = matched_acts + other_acts
                self._log("build_candidate_plans",
                          f"保证活动 '{ga_name}' 匹配 {len(matched_acts)} 个: {[a.name for a in matched_acts]}")
            else:
                # 创建合成活动
                synthetic = Activity(
                    id=f"guaranteed_act_{ga_name.replace(' ', '_')[:30]}",
                    name=ga_name,
                    type=ga_type if ga_type else "cultural_site",
                    location=Location(
                        name=ga_name,
                        address=ga_location if ga_location else ga_name,
                        district=ga_location if ga_location else "",
                    ),
                    distance_km=4.0,
                    duration_minutes=ga_duration,
                    suggested_duration_minutes=ga_duration,
                    child_friendly=True,
                    group_friendly=True,
                    price_per_person=0,
                    reservation_available=False,
                    need_booking=False,
                    description=ga_desc if ga_desc else f"精选推荐活动：{ga_name}，适合周末放松体验",
                    tags=ga_tags,
                )
                activities = [synthetic] + list(activities)
                self._log("build_candidate_plans", f"保证活动 '{ga_name}' 未匹配，已创建合成活动")

        for gr in guaranteed_restaurants_list:
            gr_name = str(gr.get("name", "") or "")
            gr_cuisine = str(gr.get("cuisine_type", "") or "")
            gr_location = str(gr.get("location_hint", "") or "")
            gr_tags = list(gr.get("tags", []) or [])
            gr_desc = str(gr.get("description", "") or "")
            gr_budget = str(gr.get("budget_level", "medium") or "medium")
            # 预算 → 人均价格映射
            price_map = {"low": 80, "medium": 150, "medium_high": 220, "high": 320}
            gr_price = int(price_map.get(gr_budget, 150))

            # 尝试匹配：name 关键词或 cuisine_type + location_hint 出现在现有餐厅中
            matched_rests = []
            other_rests = []
            for r in restaurants:
                r_name = str(getattr(r, "name", "") or "")
                r_cuisine = str(getattr(r, "cuisine_type", "") or "")
                r_addr = str(getattr(r, "location", None).address if getattr(r, "location", None) else "")
                r_district = str(getattr(r, "location", None).district if getattr(r, "location", None) else "")
                r_tags_raw = getattr(r, "tags", [])
                r_tags_list = list(r_tags_raw) if isinstance(r_tags_raw, (list, tuple)) else []
                r_text = f"{r_name} {r_cuisine} {r_addr} {r_district}"
                # 匹配策略：名称关键词重叠 / 菜系一致+地点 / 标签命中 / 纯地点兜底
                cuisine_match = bool(gr_cuisine) and (
                    gr_cuisine in r_cuisine or r_cuisine in gr_cuisine)
                loc_match = bool(gr_location) and (
                    gr_location in r_addr or gr_location in r_district or gr_location in r_name)
                tag_match = bool(gr_tags) and any(
                    any(tag in t for t in r_tags_list) for tag in gr_tags if isinstance(tag, str))
                name_match = bool(gr_name) and any(
                    len(part) >= 2 and part in r_name for part in gr_name.replace("·", " ").split())
                # 无菜系指定 + 有地点 → 地点匹配即可（如"世纪公园附近随便吃"）
                location_fallback = (not gr_cuisine) and loc_match
                if name_match or (cuisine_match and loc_match) or (tag_match and loc_match) or location_fallback:
                    matched_rests.append(r)
                else:
                    other_rests.append(r)
            if matched_rests:
                restaurants = matched_rests + other_rests
                self._log("build_candidate_plans",
                          f"保证餐厅 '{gr_name or gr_location}' 匹配 {len(matched_rests)} 家: {[r.name for r in matched_rests]}")
            else:
                # 创建合成餐厅：name 为空说明 GUESS_CARD 未指定具体餐馆，
                # 不再用生硬的"地点+类型"拼接名，直接用描述信息作为店名
                if gr_name:
                    synth_name = gr_name
                    synth_type = gr_cuisine if gr_cuisine else "中餐"
                else:
                    # 无指定名称：用描述的前 10 个字截断作为自然店名兜底
                    desc_short = gr_desc[:10].rstrip("，,。 ") if gr_desc else "特色餐厅"
                    synth_name = desc_short if len(desc_short) >= 3 else "特色餐厅"
                    synth_type = "休闲简餐"
                synth_id = f"guaranteed_rest_{synth_name.replace(' ', '_')[:30]}"
                synthetic = Restaurant(
                    id=synth_id,
                    name=synth_name,
                    type=synth_type,
                    cuisine_type=synth_type,
                    location=Location(
                        name=synth_name,
                        address=gr_location if gr_location else synth_name,
                        district=gr_location if gr_location else "",
                    ),
                    distance_km=3.0,
                    child_friendly=True,
                    diet_friendly=False,
                    group_friendly=True,
                    price_per_person=gr_price,
                    queue_minutes=0,
                    reservation_available=True,
                    need_booking=False,
                    description=gr_desc if gr_desc else f"精选推荐餐厅：{gr_name}，值得一试的好味道",
                    tags=gr_tags,
                )
                restaurants = [synthetic] + list(restaurants)
                self._log("build_candidate_plans", f"保证餐厅 '{gr_name}' 未匹配，已创建合成餐厅")

        is_full_day = (
            locked.get("time_slot") == "full_day"
            or locked.get("time_window") == "full_day"
            or request.time_window == "full_day"
            or (request.duration_hours and request.duration_hours >= 7)
        )
        self._log("build_candidate_plans",
                  f"全天检测: is_full_day={is_full_day}, "
                  f"locked.time_slot={locked.get('time_slot')}, "
                  f"request.time_window={request.time_window}, "
                  f"request.duration_hours={request.duration_hours}, "
                  f"activities={len(activities)}, restaurants={len(restaurants)}")

        # ── 全天方案优先构建，防止被普通方案挤掉 Top 5 ──
        # 全天特别方案：上午活动 → 午餐 → 下午活动 → 晚餐（4 张 POI 卡）
        # 约束：
        #   1. 上午/下午不能同一地点（名称+地址）
        #   2. 上午/下午尽量不同类型（户外 vs 室内 vs 文化等）
        #   3. 午餐/晚餐必须不同餐厅、不同菜系
        if is_full_day and len(activities) >= 2 and len(restaurants) >= 2:
            n_act = len(activities)
            n_rest = len(restaurants)
            # 扩大召回范围：活动取前 8，餐厅取前 6
            act_range = min(8, n_act)
            rest_range = min(6, n_rest)
            for i in range(act_range - 1):
                act_a = activities[i]
                for j in range(i + 1, min(i + 6, act_range)):
                    act_b = activities[j]
                    # 约束 1: 不能同一地点
                    if _is_same_location(act_a.location, act_b.location):
                        continue
                    # 约束 2: 上下午必须不同类型（mall→mall 太单调）
                    if act_a.type == act_b.type:
                        continue
                    combo_count = 0
                    for lunch_idx in range(rest_range):
                        lunch = restaurants[lunch_idx]
                        for dinner_idx in range(rest_range):
                            if lunch_idx == dinner_idx:
                                continue
                            dinner = restaurants[dinner_idx]
                            # 约束 3: 午餐和晚餐必须是不同餐厅、不同菜系
                            # 餐厅名称和地点具有唯一对应性 — 用已有的 _is_same_location 兜底
                            if lunch.id == dinner.id or lunch.name == dinner.name:
                                continue
                            if _is_same_location(lunch.location, dinner.location):
                                continue  # 同地点即同餐厅，防御性兜底
                            if lunch.cuisine_type == dinner.cuisine_type:
                                continue  # 同菜系直接拒绝（如两家居酒屋）
                            plan_id = f"plan_fullday_{i}_{j}_{lunch_idx}_{dinner_idx}"
                            plan = self._build_single_plan(
                                plan_id, request,
                                [act_a, act_b],
                                lunch,
                                home_location,
                                full_day=True,
                                dinner_restaurant=dinner,
                            )
                            if plan:
                                plans.append(plan)

        # 全天两活动+午餐方案（无晚餐，3 张 POI 卡，兜底用）
        if is_full_day and len(activities) >= 2 and len(restaurants) >= 1:
            for i in range(min(3, len(activities) - 1)):
                for j in range(i + 1, min(i + 4, len(activities))):
                    if _is_same_location(activities[i].location, activities[j].location):
                        continue  # 上下午不能同一地点
                    if activities[i].type == activities[j].type:
                        continue  # 上下午必须不同类型
                    for r_idx in range(min(6, len(restaurants))):
                        plan_id = f"plan_combo_{i}_{j}_{r_idx}"
                        plan = self._build_single_plan(
                            plan_id, request,
                            [activities[i], activities[j]],
                            restaurants[r_idx],
                            home_location,
                            full_day=True,
                        )
                        if plan:
                            plans.append(plan)

        # 普通两活动方案（时长 >= 5h）
        if len(activities) >= 2 and request.duration_hours and request.duration_hours >= 5:
            for i in range(min(2, len(activities) - 1)):
                for j in range(min(2, len(restaurants))):
                    plan_id = f"plan_two_{i}_{j}"
                    plan = self._build_single_plan(
                        plan_id, request,
                        activities[i:i+2],
                        restaurants[j],
                        home_location,
                        full_day=False,
                    )
                    if plan:
                        plans.append(plan)

        # 单活动方案（最短，优先级最低）
        if activities and restaurants:
            for i, activity in enumerate(activities[:3]):
                for j, restaurant in enumerate(restaurants[:2]):
                    plan_id = f"plan_{i}_{j}"
                    plan = self._build_single_plan(
                        plan_id, request,
                        [activity], restaurant, home_location
                    )
                    if plan:
                        plans.append(plan)

        # 去重 + 轮询排序：按活动对分组后轮询取，确保 Top 5 里活动多样性
        seen = set()
        full_day_plans = []
        other_plans = []
        # 按活动对分组
        pair_groups = {}  # {act_pair_key: [plan, ...]}
        for plan in plans:
            key = (
                tuple(a.id for a in plan.activities),
                plan.restaurant.id if plan.restaurant else None,
                plan.dinner_restaurant.id if plan.dinner_restaurant else None,
            )
            if key in seen:
                continue
            seen.add(key)
            if plan.title.startswith("全天·"):
                pair_key = tuple(a.id for a in plan.activities)
                pair_groups.setdefault(pair_key, []).append(plan)
            else:
                other_plans.append(plan)

        # 轮询：每轮从每个活动对取 1 个，优先从未用过的餐厅组合
        group_keys = list(pair_groups.keys())
        group_idxs = [0] * len(group_keys)
        used_lunch_ids = set()
        used_dinner_ids = set()

        while len(full_day_plans) < 5 and group_keys:
            added_any = False
            for g in range(len(group_keys)):
                gk = group_keys[g]
                group_plans = pair_groups[gk]
                # 在该组中找第一个未用餐厅组合的计划
                picked = None
                for idx in range(group_idxs[g], len(group_plans)):
                    p = group_plans[idx]
                    lunch_id = p.restaurant.id if p.restaurant else None
                    dinner_id = p.dinner_restaurant.id if p.dinner_restaurant else None
                    if lunch_id not in used_lunch_ids or dinner_id not in used_dinner_ids:
                        picked = idx
                        break
                if picked is None:
                    picked = group_idxs[g]  # fallback: 取下一个未用的
                if picked < len(group_plans):
                    plan = group_plans[picked]
                    full_day_plans.append(plan)
                    if plan.restaurant:
                        used_lunch_ids.add(plan.restaurant.id)
                    if plan.dinner_restaurant:
                        used_dinner_ids.add(plan.dinner_restaurant.id)
                    group_idxs[g] = picked + 1
                    added_any = True
            if not added_any:
                break

        unique_plans = full_day_plans + other_plans
        self.state.candidate_plans = unique_plans[:5]
        self._log("build_candidate_plans",
                  f"成功构建 {len(self.state.candidate_plans)} 个候选方案 "
                  f"(全天={len(full_day_plans)}, 普通={len(other_plans)})")

        return self.state.candidate_plans

    # ── 时间线构建辅助函数 ──

    @staticmethod
    def _add_travel_stop(timeline, route_infos, current_time, from_loc, to_loc, activity_label, check_fn, description=None):
        """添加一段通勤行程到 timeline，返回到达时间。"""
        route = check_fn(from_loc, to_loc)
        route_infos.append(route)
        travel_minutes = route.travel_minutes
        arrival = current_time + timedelta(minutes=travel_minutes)
        timeline.append(TimelineItem(
            start_time=current_time.strftime("%H:%M"),
            end_time=arrival.strftime("%H:%M"),
            activity=activity_label,
            location="途中",
            type="travel",
            description=description or f"车程约{travel_minutes}分钟"
        ))
        return arrival

    @staticmethod
    def _add_activity_stop(timeline, current_time, activity):
        """添加一个活动站点到 timeline，返回活动结束时间。"""
        end_time = current_time + timedelta(minutes=activity.suggested_duration_minutes)
        timeline.append(TimelineItem(
            start_time=current_time.strftime("%H:%M"),
            end_time=end_time.strftime("%H:%M"),
            activity=activity.name,
            location=activity.location.name,
            type="activity",
            description=activity.description[:50] + "..."
        ))
        return end_time + timedelta(minutes=10)

    @staticmethod
    def _add_meal_stop(timeline, current_time, restaurant, meal_label, duration_minutes=70):
        """添加一个用餐站点到 timeline，返回用餐结束时间。"""
        end_time = current_time + timedelta(minutes=duration_minutes)
        timeline.append(TimelineItem(
            start_time=current_time.strftime("%H:%M"),
            end_time=end_time.strftime("%H:%M"),
            activity=f"在{restaurant.name}{meal_label}",
            location=restaurant.location.name,
            type="meal",
            description=f"{restaurant.cuisine_type}，人均¥{restaurant.price_per_person}"
        ))
        return end_time + timedelta(minutes=15)

    def _build_single_plan(
        self,
        plan_id: str,
        request: UserRequest,
        activities: List[Activity],
        restaurant: Restaurant,
        home_location: Location,
        full_day: bool = False,
        dinner_restaurant: Optional[Restaurant] = None,
    ) -> Optional[CandidatePlan]:
        """
        构建单个方案的时间线。

        full_day=True 且提供 dinner_restaurant 时，构建完整的全天行程：
        Home → 上午活动 → 午餐(restaurant) → 下午活动 → 晚餐(dinner_restaurant) → Home

        仅 full_day=True 无 dinner_restaurant 时：
        Home → 活动1 → 午餐(restaurant) → 活动2 → Home

        默认模式：
        Home → 活动1 → 活动2 → 餐厅(restaurant) → Home
        """
        try:
            timeline = []
            route_infos = []

            # 解析开始时间
            start_time = datetime.strptime(request.start_time or "14:00", "%H:%M")
            current_time = start_time

            # 决定模式
            has_dinner = full_day and dinner_restaurant is not None and restaurant is not None and len(activities) >= 2
            meal_between = full_day and len(activities) >= 2 and restaurant is not None

            # 1. 从家出发
            timeline.append(TimelineItem(
                start_time=current_time.strftime("%H:%M"),
                end_time=current_time.strftime("%H:%M"),
                activity="从家出发",
                location=home_location.name,
                type="departure",
                description="准备出发"
            ))

            first_activity = None
            last_location = home_location

            # ── 2. 上午活动 ──
            if activities:
                first_activity = activities[0]
                current_time = self._add_travel_stop(
                    timeline, route_infos, current_time,
                    home_location, first_activity.location,
                    f"前往{first_activity.name}", self.check_route_time)

                current_time = self._add_activity_stop(timeline, current_time, first_activity)
                last_location = first_activity.location

            # ── 3. 午餐（全天模式：放在活动之间）──
            if meal_between and restaurant:
                current_time = self._add_travel_stop(
                    timeline, route_infos, current_time,
                    last_location, restaurant.location,
                    f"前往{restaurant.name}（午餐）", self.check_route_time)
                current_time = self._add_meal_stop(timeline, current_time, restaurant, "用午餐", 70)
                last_location = restaurant.location

            # ── 4. 下午活动 ──
            if len(activities) > 1 and not meal_between:
                # 非全天模式：第二个活动在餐厅之前
                second_activity = activities[1]
                current_time = self._add_travel_stop(
                    timeline, route_infos, current_time,
                    last_location, second_activity.location,
                    f"前往{second_activity.name}", self.check_route_time)
                current_time = self._add_activity_stop(timeline, current_time, second_activity)
                last_location = second_activity.location

            elif len(activities) > 1 and meal_between:
                # 全天模式：午餐之后的下午活动
                second_activity = activities[1]
                current_time = self._add_travel_stop(
                    timeline, route_infos, current_time,
                    last_location, second_activity.location,
                    f"前往{second_activity.name}", self.check_route_time)
                current_time = self._add_activity_stop(timeline, current_time, second_activity)
                last_location = second_activity.location

            # ── 5. 晚餐（仅全天+有 dinner_restaurant 时）──
            if has_dinner:
                current_time = self._add_travel_stop(
                    timeline, route_infos, current_time,
                    last_location, dinner_restaurant.location,
                    f"前往{dinner_restaurant.name}（晚餐）", self.check_route_time)
                current_time = self._add_meal_stop(timeline, current_time, dinner_restaurant, "用晚餐", 80)
                last_location = dinner_restaurant.location

            # ── 6. 餐厅（非全天默认模式：活动之后用餐）──
            if restaurant and not meal_between:
                current_time = self._add_travel_stop(
                    timeline, route_infos, current_time,
                    last_location, restaurant.location,
                    f"前往{restaurant.name}", self.check_route_time)
                current_time = self._add_meal_stop(timeline, current_time, restaurant, "用餐", 80)
                last_location = restaurant.location

            # ── 7. 返程 ──
            current_time = self._add_travel_stop(
                timeline, route_infos, current_time,
                last_location, home_location,
                "返程回家", self.check_route_time)
            # 返程时间已是 timeline 中最后一项的 end_time

            # 计算总时长
            total_duration = (current_time - start_time).total_seconds() / 60

            # 生成标题
            title_parts = [a.name for a in activities]
            if has_dinner:
                title_parts.append(f"{restaurant.name}(午)")
                title_parts.append(f"{dinner_restaurant.name}(晚)")
            elif restaurant:
                title_parts.append(restaurant.name)
            title = " + ".join(title_parts)
            if full_day:
                title = f"全天·{title}"

            # 创建方案
            plan = CandidatePlan(
                plan_id=plan_id,
                title=title,
                timeline=timeline,
                total_duration_minutes=int(total_duration),
                activities=activities,
                restaurant=restaurant,
                dinner_restaurant=dinner_restaurant,
                route_infos=route_infos,
                score=0.0,
                score_breakdown=ScoreBreakdown(),
                risks=[],
                recommendation_reason=""
            )

            return plan

        except Exception as e:
            self._log("build_single_plan", f"构建方案失败: {str(e)}")
            return None

    def _get_fallback_activities(self) -> List[Activity]:
        """获取备选活动（当搜索不到足够活动时）"""
        # 返回一些默认活动
        fallback = [
            Activity(
                id="fallback_001",
                name="公园休闲散步",
                type="park",
                location=Location(name="附近公园", address="社区公园"),
                distance_km=2.0,
                duration_minutes=60,
                suggested_duration_minutes=60,
                child_friendly=True,
                price_per_person=0,
                reservation_available=False,
                need_booking=False,
                description="家附近的公园，适合休闲散步"
            ),
            Activity(
                id="fallback_002",
                name="商场亲子区",
                type="mall",
                location=Location(name="附近商场", address="社区商场"),
                distance_km=3.0,
                duration_minutes=90,
                suggested_duration_minutes=90,
                child_friendly=True,
                price_per_person=50,
                reservation_available=False,
                need_booking=False,
                description="商场内的儿童游乐区"
            )
        ]
        return fallback

    def _get_fallback_restaurants(self) -> List[Restaurant]:
        """获取备选餐厅（当搜索不到足够餐厅时）"""
        return [
            Restaurant(
                id="fallback_rest_001",
                name="社区家庭餐厅",
                type="family",
                cuisine_type="中餐",
                location=Location(name="社区餐厅", address="社区中心"),
                distance_km=2.5,
                child_friendly=True,
                diet_friendly=False,
                group_friendly=True,
                price_per_person=80,
                reservation_available=False,
                need_booking=False,
                description="社区内的家庭餐厅，方便快捷"
            ),
            Restaurant(
                id="fallback_rest_002",
                name="邻里小馆",
                type="casual",
                cuisine_type="本帮菜",
                location=Location(name="邻里小馆", address="社区商业街"),
                distance_km=1.8,
                child_friendly=True,
                diet_friendly=True,
                group_friendly=True,
                price_per_person=60,
                reservation_available=False,
                need_booking=False,
                description="社区商业街的家常菜馆，经济实惠"
            ),
        ]

    # ==================== Step 7: 评分 ====================

    def score_plans(self, plans: List[CandidatePlan]) -> List[CandidatePlan]:
        """
        对候选方案进行评分

        Args:
            plans: 候选方案列表

        Returns:
            评分后的方案列表
        """
        self._log("score_plans", "正在对候选方案评分...")

        defaults = self.product_rules.get("defaults", {})

        scored_plans = score_plans(
            plans,
            target_duration_hours=self.state.user_request.duration_hours or defaults.get("duration_hours", 4),
            max_drive_minutes=defaults.get("max_drive_minutes", 30),
            companions=self.state.user_request.companions,
            activity_preference=self.state.user_request.activity_preference,
            scenario_type=self.state.user_request.scenario_type,
            scoring_profile=self.state.user_request.scoring_profile,
            scenario_labels=self.state.user_request.scenario_labels,
            activated_constraints=self.state.user_request.activated_constraints,
            has_child=self.state.user_request.has_child,
            diet_goal=self.state.user_request.diet_goal,
        )

        # ── GUESS_CARD 保证项评分加成 ──
        # 包含 guaranteed_restaurants/guaranteed_activities 的方案获得额外加分，
        # 确保在最终排名中优先展示，兑现开屏 GUESS_CARD 中的地点/餐馆承诺。
        locked = getattr(self.state, "locked_constraints", {}) or {}
        # 保证项信息：同时保留 name、location、cuisine 用于多维度匹配
        guaranteed_rest_infos: list = [
            {
                "name": str(gr.get("name", "") or ""),
                "location": str(gr.get("location_hint", "") or ""),
                "cuisine": str(gr.get("cuisine_type", "") or ""),
            }
            for gr in (locked.get("guaranteed_restaurants", []) or [])
        ]
        guaranteed_act_infos: list = [
            {
                "name": str(ga.get("name", "") or ""),
                "location": str(ga.get("location_hint", "") or ""),
            }
            for ga in (locked.get("guaranteed_activities", []) or [])
        ]

        if guaranteed_rest_infos or guaranteed_act_infos:
            for plan in scored_plans:
                bonus = 0
                # 餐厅命中加分
                if guaranteed_rest_infos and plan.restaurant:
                    plan_rest_name = str(getattr(plan.restaurant, "name", "") or "")
                    plan_cuisine = str(getattr(plan.restaurant, "cuisine_type", "") or "")
                    plan_addr = str(getattr(plan.restaurant, "location", None).address if getattr(plan.restaurant, "location", None) else "")
                    plan_district = str(getattr(plan.restaurant, "location", None).district if getattr(plan.restaurant, "location", None) else "")
                    for gr in guaranteed_rest_infos:
                        gname, gloc, gcuisine = gr["name"], gr["location"], gr["cuisine"]
                        # 名称匹配
                        if gname and (gname in plan_rest_name or plan_rest_name in gname):
                            bonus += 25
                            break
                        # 菜系匹配
                        if gcuisine and (gcuisine in plan_cuisine or plan_cuisine in gcuisine):
                            bonus += 25
                            break
                        # 地点匹配（无菜系指定时纯地点兜底，如"世纪公园附近"）
                        if gloc and (gloc in plan_addr or gloc in plan_district):
                            bonus += 25
                            break
                # 晚餐餐厅命中（全天方案）
                if guaranteed_rest_infos and plan.dinner_restaurant:
                    dinner_name = str(getattr(plan.dinner_restaurant, "name", "") or "")
                    for gr in guaranteed_rest_infos:
                        gname = gr["name"]
                        if gname and (gname in dinner_name or dinner_name in gname):
                            bonus += 15
                            break
                # 活动命中加分
                if guaranteed_act_infos and plan.activities:
                    for act in plan.activities:
                        act_name = str(getattr(act, "name", "") or "")
                        for ga in guaranteed_act_infos:
                            gname, gloc = ga["name"], ga["location"]
                            if (gname and (gname in act_name or act_name in gname)) or \
                               (gloc and gloc in act_name):
                                bonus += 20
                                break
                if bonus > 0:
                    plan.score = min(plan.score + bonus, 100.0)
                    self._log("score_plans",
                              f"保证项加成: {plan.plan_id} +{bonus}分 → {plan.score}分（封顶100）")

            # 重新排序
            scored_plans.sort(key=lambda x: x.score, reverse=True)

        for plan in scored_plans:
            self._log(
                "score_plans",
                f"方案 {plan.plan_id}: {plan.score}分",
                plan.score_breakdown.to_dict()
            )

        return scored_plans

    # ==================== Step 8: 选择最优方案 ====================

    def choose_best_plan(self, plans: List[CandidatePlan]) -> CandidatePlan:
        """
        选择最优方案

        Args:
            plans: 候选方案列表

        Returns:
            最优方案
        """
        self._log("choose_best_plan", "正在选择最优方案...")

        if not plans:
            raise ValueError("没有可用的候选方案")

        # 按分数排序后的第一个就是最优方案
        best_plan = plans[0]

        # 生成推荐理由
        has_diet_constraint = (
            self.state.user_request.scenario_type == "health_diet"
            or self.state.user_request.diet_goal != "none"
        )
        best_plan.recommendation_reason = get_recommendation_reason({
            "activities": [{"child_friendly": a.child_friendly} for a in best_plan.activities] if self.state.user_request.has_child else [],
            "restaurant": {"diet_friendly": best_plan.restaurant.diet_friendly if best_plan.restaurant and has_diet_constraint else False},
            "score": best_plan.score
        })

        # 生成风险提示
        risks = []
        for activity in best_plan.activities:
            if activity.need_booking and not activity.is_available:
                risks.append(f"{activity.name} 可能需要提前预约")
            if activity.queue_minutes > 15:
                risks.append(f"{activity.name} 可能需要排队约{activity.queue_minutes}分钟")

        if best_plan.restaurant:
            if best_plan.restaurant.queue_minutes > 20:
                risks.append(f"{best_plan.restaurant.name} 可能需要等位")

        best_plan.risks = risks

        self.state.selected_plan = best_plan
        self._log(
            "choose_best_plan",
            f"已选择最优方案: {best_plan.title}, 得分: {best_plan.score}"
        )

        return best_plan

    # ==================== Step 9: 执行方案 ====================

    def execute_plan(
        self,
        plan: CandidatePlan,
        user_confirmed: bool = True
    ) -> ExecutionResult:
        """
        执行方案

        Args:
            plan: 要执行的方案
            user_confirmed: 用户是否已确认

        Returns:
            执行结果
        """
        self._log("execute_plan", "开始执行方案...")

        exec_config = self.product_rules.get("execution_level", {})
        result = ExecutionResult()

        # 检查是否需要用户确认
        if exec_config.get("require_user_confirmation_before_booking", True) and not user_confirmed:
            result.final_summary = "等待用户确认后执行"
            result.all_succeeded = False
            return result

        # 1. 预约活动
        if exec_config.get("allow_mock_booking", True):
            for activity in plan.activities:
                booking_result = book_activity(activity)
                result.activity_booking_status.append(booking_result)
                self._log(
                    "execute_plan",
                    f"活动预约: {activity.name} - {'成功' if booking_result.success else '失败'}"
                )

        # 2. 预约餐厅
        if exec_config.get("allow_mock_booking", True) and plan.restaurant:
            # 从时间线中提取用餐开始时间
            meal_time = "18:00"
            for item in plan.timeline:
                if item.type == "meal":
                    meal_time = item.start_time
                    break

            booking_result = book_restaurant(
                plan.restaurant,
                self.state.user_request.people_count or 1,
                meal_time
            )
            result.restaurant_booking_status = booking_result
            self._log(
                "execute_plan",
                f"餐厅预约: {plan.restaurant.name} - {'成功' if booking_result.success else '失败'}"
            )

            # 如果餐厅预约失败，尝试备选
            if not booking_result.success:
                self._log("execute_plan", "餐厅预约失败，尝试备选餐厅...")
                fallback_restaurant = self._find_fallback_restaurant(plan.restaurant)
                if fallback_restaurant:
                    booking_result = book_restaurant(
                        fallback_restaurant,
                        self.state.user_request.people_count or 1,
                        meal_time
                    )
                    if booking_result.success:
                        plan.restaurant = fallback_restaurant
                        result.restaurant_booking_status = booking_result
                        self._log("execute_plan", f"已切换至备选餐厅: {fallback_restaurant.name}")

        # 3. 下单（蛋糕/鲜花）
        if exec_config.get("allow_mock_order", True):
            # 根据场景决定是否需要蛋糕或鲜花
            if self.state.user_request.companions in [CompanionsType.FAMILY_WITH_KIDS, CompanionsType.FAMILY_MIXED]:
                # 家庭场景：可能买蛋糕
                order_result = order_item("cake", plan.restaurant.location if plan.restaurant else get_user_context()["home_location"])
                result.order_status.append(order_result)
                self._log("execute_plan", f"蛋糕下单 - {'成功' if order_result.success else '失败'}")

        # 4. 发送消息
        if exec_config.get("allow_mock_send_message", True):
            # 发送给家人或朋友
            family_types = [CompanionsType.FAMILY_WITH_KIDS, CompanionsType.FAMILY_WITH_ELDERLY, CompanionsType.FAMILY_MIXED]
            recipient = "家人" if self.state.user_request.companions in family_types else "朋友"
            message_result = send_plan(
                recipient,
                f"活动方案：{plan.title}，时间：{plan.timeline[0].start_time}"
            )
            result.message_status.append(message_result)
            self._log("execute_plan", f"消息发送给{recipient} - {'成功' if message_result.success else '失败'}")

        # 生成执行摘要
        result.executed_at = datetime.now()
        result.all_succeeded = all(
            b.success for b in result.activity_booking_status
        ) and (result.restaurant_booking_status is None or result.restaurant_booking_status.success)

        result.final_summary = self._generate_execution_summary(result)
        self.state.execution_result = result

        self._log("execute_plan", f"方案执行完成，全部成功: {result.all_succeeded}")

        return result

    def _find_fallback_restaurant(self, original: Restaurant) -> Optional[Restaurant]:
        """查找备选餐厅"""
        # 查找同类型的其他餐厅
        for restaurant in self.state.found_restaurants:
            if restaurant.id != original.id and restaurant.is_available:
                return restaurant
        return None

    def _generate_execution_summary(self, result: ExecutionResult) -> str:
        """生成执行摘要"""
        summary_parts = []

        # 活动预约
        for booking in result.activity_booking_status:
            status = "✓ 成功" if booking.success else "✗ 失败"
            summary_parts.append(f"活动预约（{booking.item_name}）: {status}")

        # 餐厅预约
        if result.restaurant_booking_status:
            status = "✓ 成功" if result.restaurant_booking_status.success else "✗ 失败"
            summary_parts.append(f"餐厅预约（{result.restaurant_booking_status.item_name}）: {status}")

        # 订单
        for order in result.order_status:
            status = "✓ 成功" if order.success else "✗ 失败"
            item_name = {"cake": "蛋糕", "flower": "鲜花", "gift": "礼物"}.get(order.item_type, "精选商品")
            summary_parts.append(f"{item_name}下单: {status}")

        # 消息
        for msg in result.message_status:
            status = "✓ 成功" if msg.success else "✗ 失败"
            summary_parts.append(f"发送消息（{msg.recipient}）: {status}")

        return "\n".join(summary_parts)

    # ==================== Step 10: 异常处理 ====================

    def handle_failure(
        self,
        failure_type: str,
        original_item: Any,
        context: Optional[Dict] = None
    ) -> Any:
        """
        异常处理

        Args:
            failure_type: 异常类型
            original_item: 原始项目
            context: 上下文信息

        Returns:
            替代方案
        """
        self._log("handle_failure", f"处理异常: {failure_type}")

        fallbacks = self.product_rules.get("failure_fallbacks", {})

        if failure_type == "restaurant_unavailable":
            # 选择备选餐厅
            return self._find_fallback_restaurant(original_item)

        elif failure_type == "activity_unavailable":
            # 优先选择无需预约的活动
            for activity in self.state.found_activities:
                if not activity.need_booking and activity.is_available:
                    return activity
            # 如果没有，返回 citywalk
            return Activity(
                id="fallback_citywalk",
                name="附近 Citywalk",
                type="citywalk",
                location=Location(name="附近街区", address="社区周边"),
                distance_km=1.0,
                duration_minutes=60,
                suggested_duration_minutes=60,
                child_friendly=True,
                price_per_person=0,
                reservation_available=False,
                need_booking=False,
                description="附近街区散步，无需预约"
            )

        elif failure_type == "route_too_far":
            # 重新搜索更近的活动和餐厅
            max_drive = 15  # 缩小搜索范围
            return None  # 需要重新搜索

        elif failure_type == "not_child_friendly":
            return None

        elif failure_type == "diet_unfriendly":
            for restaurant in self.state.found_restaurants:
                if restaurant.diet_friendly:
                    return restaurant
            return None

        self.state.fallback_used = True
        self.state.fallback_reason = failure_type

        return None

    # ==================== 渐进式约束放宽 ====================

    def _build_retry_overrides(self, retry: int) -> Dict[str, Any]:
        """根据重试次数生成逐步放宽的搜索参数。"""
        overrides: Dict[str, Any] = {}
        relaxed: List[str] = []
        base_max_drive = int(self.product_rules.get("defaults", {}).get("max_drive_minutes", 30))

        if retry >= 1:
            overrides["max_drive_minutes"] = int(base_max_drive * 1.5)
            relaxed.append(f"max_drive_minutes → {overrides['max_drive_minutes']}min")

        if retry >= 2:
            overrides["drop_child_filter"] = True
            overrides["drop_diet_filter"] = True
            relaxed.append("drop_child_filter, drop_diet_filter")

        if retry >= 3:
            overrides["max_drive_minutes"] = int(base_max_drive * 2.5)
            relaxed.append(f"max_drive_minutes → {overrides['max_drive_minutes']}min (大幅放宽)")

        self.state.relaxed_constraints = relaxed
        return overrides

    # ==================== 主流程（v2: agentic loop + draft/commit） ====================

    def run(
        self,
        user_input: str,
        user_confirmed: bool = True,
        execute_mode: str = "full",  # "plan_only" | "full"
        locked_constraints: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        运行 Agent 主流程。

        execute_mode:
          - "plan_only": 只生成方案，不执行（draft 阶段）
          - "full": 生成方案后直接执行（commit 阶段，需 user_confirmed=True）

        locked_constraints: Round 2 锁定的约束条件（来自泛方案卡片选择），
          会注入到搜索过滤、默认值补全和评分逻辑中。

        内置 agentic feedback loop: 当搜索/构建结果不足时自动放宽约束重试。
        """
        self._log("run", "=" * 50)
        self._log("run", f"开始执行 Agent 主流程 (mode={execute_mode}, retries={self.state.max_retries})")

        # 存储 locked_constraints 供后续步骤使用
        self.state.locked_constraints = locked_constraints or {}
        if self.state.locked_constraints:
            self._log("run", f"使用锁定约束: {json.dumps(self.state.locked_constraints, ensure_ascii=False)}")

        try:
            # Step 1: 解析请求
            request = self.parse_request(user_input)

            # Step 2: 补全缺失信息
            request = self.complete_missing_slots(request)

            # Step 3-6: 搜索 → 构建 → 评分（带重试 loop）
            plans: List[CandidatePlan] = []
            best_plan: Optional[CandidatePlan] = None

            for attempt in range(self.state.max_retries + 1):
                self.state.retry_count = attempt
                overrides = self._build_retry_overrides(attempt)

                if attempt > 0:
                    self._log("retry", f"第 {attempt} 次重试，放宽约束: {overrides}")

                # Step 3: 搜索活动
                activities = self.search_activities(request, overrides)

                # Step 4: 搜索餐厅
                restaurants = self.search_restaurants(request, overrides)

                # 如果搜索结果太少，直接下一轮重试
                if len(activities) < 1:
                    self._log("retry", f"活动数量不足 ({len(activities)}), 准备重试", level="warning")
                    continue

                # Step 5: 构建候选方案
                plans = self.build_candidate_plans(request, activities, restaurants)
                if not plans:
                    self._log("retry", "无法构建可行方案，准备重试", level="warning")
                    continue

                # Step 6: 评分 + 质量门禁
                plans = self.score_plans(plans)
                best_plan = plans[0] if plans else None

                if best_plan and best_plan.score >= QUALITY_SCORE_THRESHOLD:
                    self._log("retry", f"方案质量达标 (score={best_plan.score}), 停止重试")
                    break
                elif attempt < self.state.max_retries:
                    self._log(
                        "retry",
                        f"方案质量不达标 (score={best_plan.score if best_plan else 'N/A'} < {QUALITY_SCORE_THRESHOLD})，准备重试",
                        level="warning",
                    )
                else:
                    self._log("retry", f"已达最大重试次数，使用当前最优方案 (score={best_plan.score if best_plan else 'N/A'})")

            if not plans or not best_plan:
                return {
                    "success": False,
                    "error": f"经过 {self.state.retry_count} 次重试仍无法构建可行的活动方案",
                    "state": self._get_state_dict(),
                }

            # Step 7: 选择最优方案 + 生成推荐理由
            best_plan = self.choose_best_plan(plans)

            # 生成创意标题（缓存至 state 供后续 confirm_and_execute 复用）
            creative_title = self._build_creative_title(best_plan, request)
            self.state.creative_title = creative_title

            # ===== Draft/Commit 分离 =====
            if execute_mode == "plan_only":
                # 仅生成方案，等待用户确认
                self.state.confirmation_status = "pending"
                self.state.confirmed_plan_id = best_plan.plan_id
                self._log("run", f"方案已生成 (plan_only), 等待用户确认. plan_id={best_plan.plan_id}")

                return {
                    "success": True,
                    "phase": "draft",
                    "plan_id": best_plan.plan_id,
                    "request": request.to_dict(),
                    "candidate_plans_count": len(plans),
                    "all_plans": [self._plan_to_dict(p) for p in plans[:3]],
                    "best_plan": self._plan_to_dict(best_plan),
                    "creative_title": creative_title,
                    "requires_confirmation": True,
                    "state": self._get_state_dict(),
                }

            # Step 8: 执行方案（full mode / commit phase）
            execution_result = self.execute_plan(best_plan, user_confirmed)
            self.state.confirmation_status = "confirmed" if execution_result.all_succeeded else "rejected"

            self._log("run", "Agent 主流程执行完成")

            return {
                "success": True,
                "phase": "executed",
                "plan_id": best_plan.plan_id,
                "request": request.to_dict(),
                "candidate_plans_count": len(plans),
                "all_plans": [self._plan_to_dict(p) for p in plans[:3]],
                "best_plan": self._plan_to_dict(best_plan),
                "creative_title": creative_title,
                "execution_result": self._execution_to_dict(execution_result),
                "state": self._get_state_dict(),
            }

        except Exception as e:
            self._log("run", f"执行出错: {str(e)}", level="error")
            logger.exception(f"Agent run failed: {e}")
            return {
                "success": False,
                "error": str(e),
                "state": self._get_state_dict(),
            }

    def confirm_and_execute(self, plan_id: str) -> Dict[str, Any]:
        """
        用户确认后执行方案（commit 阶段）。

        调用前需确保 run(execute_mode="plan_only") 已成功生成方案并存于 state 中。
        """
        self._log("confirm_and_execute", f"用户确认执行 plan_id={plan_id}")

        if self.state.confirmation_status != "pending":
            return {
                "success": False,
                "error": f"当前确认状态为 {self.state.confirmation_status}，无法执行",
                "state": self._get_state_dict(),
            }

        if self.state.confirmed_plan_id != plan_id:
            return {
                "success": False,
                "error": f"plan_id 不匹配: 期望 {self.state.confirmed_plan_id}, 收到 {plan_id}",
                "state": self._get_state_dict(),
            }

        plan = self.state.selected_plan
        if not plan:
            return {
                "success": False,
                "error": "未找到待执行的方案，请先调用 run(execute_mode='plan_only')",
                "state": self._get_state_dict(),
            }

        try:
            execution_result = self.execute_plan(plan, user_confirmed=True)
            self.state.confirmation_status = "confirmed" if execution_result.all_succeeded else "rejected"
            self.state.execution_result = execution_result

            return {
                "success": True,
                "phase": "executed",
                "plan_id": plan.plan_id,
                "best_plan": self._plan_to_dict(plan),
                "creative_title": getattr(self.state, "creative_title", ""),
                "execution_result": self._execution_to_dict(execution_result),
                "state": self._get_state_dict(),
            }
        except Exception as e:
            self._log("confirm_and_execute", f"执行失败: {e}", level="error")
            return {
                "success": False,
                "error": str(e),
                "state": self._get_state_dict(),
            }

    def _build_creative_title(self, plan: CandidatePlan, request: UserRequest) -> str:
        """根据最优方案和用户请求生成创意标题（调用 DeepSeek）。"""
        locations: List[str] = []
        for a in plan.activities:
            locations.append(a.name)
        if plan.restaurant:
            locations.append(plan.restaurant.name)
        if plan.dinner_restaurant:
            locations.append(plan.dinner_restaurant.name)

        # 场景类型映射
        companion_map = {
            "family_with_children": "family", "family_with_elderly": "family",
            "friends": "friends", "couple": "couple", "solo": "solo",
            "colleagues": "friends", "pet": "family",
        }
        scene_type = "friends"
        for c in (request.companion_context or []):
            scene_type = companion_map.get(c, "friends")
            break

        # 氛围关键词
        vibe_parts = []
        if request.primary_intent:
            vibe_parts.append(request.primary_intent)
        if request.activity_preference:
            vibe_parts.append(request.activity_preference)
        vibe_parts.extend(request.context_modifiers[:2] or [])

        # 同行人详情
        detail_parts = []
        if request.people_count:
            detail_parts.append(f"{request.people_count}人")
        if request.has_child and request.child_age:
            detail_parts.append(f"孩子{request.child_age}岁")
        elif request.has_child:
            detail_parts.append("带娃")

        return generate_creative_title(
            locations=locations,
            scene_type=scene_type,
            vibe=" ".join(vibe_parts) if vibe_parts else "",
            group_detail="，".join(detail_parts) if detail_parts else "",
        )

    def _get_poi_recommendations(self, poi: Any, is_activity: bool = True) -> List[Dict[str, Any]]:
        """统一推荐引擎：融合多种子信息类型，按用户槽位打分、穿插排序。

        活动 POI：sub_facilities + seasonal_events + coupons + nearby_dining
        餐厅 POI：coupons + signature_dishes
        """
        locked = getattr(self.state, "locked_constraints", {}) or {}
        group_type = locked.get("group_type", "")
        child_age = locked.get("child_age")
        budget = locked.get("budget", "")
        people_count = locked.get("people_count", 0)
        context_modifiers = set(locked.get("context_modifiers", []) or [])
        hard_constraints = set(locked.get("hard_constraints", []) or [])

        budget_max = {"low": 80, "medium": 200, "high": 9999}.get(
            str(budget).lower() if budget else "", 200
        )

        all_items = []  # (score, content_type, raw_dict)

        # ---- 活动 POI：收集 4 种类型 ----
        if is_activity:
            # sub_facilities
            for sf in (getattr(poi, "sub_facilities", None) or []):
                if not isinstance(sf, dict):
                    continue
                score = self._score_item(sf, "sub", group_type, child_age,
                                         context_modifiers, hard_constraints, budget_max, people_count)
                all_items.append((score, "sub", sf))

            # seasonal_events
            for ev in (getattr(poi, "seasonal_events", None) or []):
                if not isinstance(ev, dict):
                    continue
                score = self._score_item(ev, "event", group_type, child_age,
                                         context_modifiers, hard_constraints, budget_max, people_count)
                all_items.append((score, "event", ev))

            # coupons
            for cp in (getattr(poi, "coupons", None) or []):
                if not isinstance(cp, dict):
                    continue
                score = self._score_item(cp, "coupon", group_type, child_age,
                                         context_modifiers, hard_constraints, budget_max, people_count)
                all_items.append((score, "coupon", cp))

        else:
            # ---- 餐厅 POI：coupons + signature_dishes ----
            # 套餐优先级始终高于单个推荐菜
            for cp in (getattr(poi, "coupons", None) or []):
                if not isinstance(cp, dict):
                    continue
                score = self._score_item(cp, "coupon", group_type, child_age,
                                         context_modifiers, hard_constraints, budget_max, people_count)
                all_items.append((score + 500, "coupon", cp))

            est_price = int((poi.price_per_person or 80) * 0.3)
            for dish_name in (getattr(poi, "signature_dishes", None) or []):
                if not dish_name:
                    continue
                dish_dict = {"name": str(dish_name), "price_per_person": est_price}
                score = self._score_item(dish_dict, "dish", group_type, child_age,
                                         context_modifiers, hard_constraints, budget_max, people_count)
                all_items.append((score, "dish", dish_dict))

        if not all_items:
            return []

        # 降序排列
        all_items.sort(key=lambda x: -x[0])

        # round-robin 穿插：避免同一类型聚集
        buckets = {}
        for score, ct, item in all_items:
            buckets.setdefault(ct, []).append((score, item))
        # 各 bucket 内部保持降序
        for ct in buckets:
            buckets[ct].sort(key=lambda x: -x[0])

        interleaved = []
        bucket_keys = sorted(buckets.keys(), key=lambda k: -buckets[k][0][0])  # 按最高分排 bucket 顺序
        ptr = {k: 0 for k in bucket_keys}
        while len(interleaved) < 5:
            added = False
            for k in bucket_keys:
                if ptr[k] < len(buckets[k]):
                    interleaved.append((buckets[k][ptr[k]][0], k, buckets[k][ptr[k]][1]))
                    ptr[k] += 1
                    added = True
            if not added:
                break

        # 构建输出
        result = []
        for score, ct, raw in interleaved:
            price = raw.get("price_per_person", raw.get("coupon_price", 0) or 0)
            orig_price = None
            if ct == "coupon":
                orig_price = raw.get("original_price")

            name = raw.get("name", raw.get("title", ""))
            highlight = raw.get("highlight", raw.get("description", ""))

            # 徽章生成
            badge = self._make_badge(ct, raw, score, group_type, price, orig_price)

            result.append({
                "content_type": ct,
                "name": name,
                "subtitle": raw.get("type", raw.get("cuisine", "")),
                "price": price,
                "original_price": orig_price,
                "highlight": highlight,
                "badge": badge,
            })
        return result

    @staticmethod
    def _score_item(raw, content_type, group_type, child_age,
                    context_modifiers, hard_constraints, budget_max, people_count=0):
        """对单个推荐项打分。包含团购套餐人数适配逻辑。"""
        score = 0
        name = str(raw.get("name", raw.get("title", "")))
        sf_type = str(raw.get("type", raw.get("cuisine", "")))
        sf_price = raw.get("price_per_person", raw.get("coupon_price", 0) or 0)
        sf_child = raw.get("child_friendly", False)
        sf_tags = raw.get("tags", {}) or {}
        sf_attr = set(sf_tags.get("attribute", []) if isinstance(sf_tags, dict) else [])
        all_text = name + sf_type + " ".join(sf_attr)

        # ---- 团购套餐人数适配 ----
        person_match = re.search(r"(\d+)人|双人|单人|(\d)大(\d)小|亲子票", name)
        coupon_persons = 1  # 默认单人
        if person_match:
            matched = person_match.group(0)
            if "双人" in matched:
                coupon_persons = 2
            elif "亲子票" in matched or "大" in matched:
                coupon_persons = 2  # 1大1小 = 2人
            elif "单人" in matched:
                coupon_persons = 1
            else:
                try:
                    coupon_persons = int(person_match.group(1))
                except (ValueError, IndexError):
                    coupon_persons = 1
        # 约会/浪漫关键词默认双人
        if "约会" in name or "浪漫" in name:
            coupon_persons = max(coupon_persons, 2)

        # 根据同行人类型调整人数期望
        if group_type in ("独自一人",):
            if coupon_persons >= 2:
                score -= 45  # 独行用户不推荐多人套餐
        elif group_type in ("情侣约会",):
            if coupon_persons == 2:
                score += 18  # 双人套餐正合适
            elif coupon_persons >= 4:
                score -= 25  # 情侣不需要大份套餐
        elif group_type in ("朋友聚会",):
            if coupon_persons >= 4:
                score += 22  # 聚会优选大份套餐
            elif coupon_persons == 1 and content_type == "coupon":
                score -= 10  # 朋友聚餐单人套餐不够
            # 朋友出行不推情侣/双人套餐
            if "情侣" in all_text or "浪漫" in all_text or "约会" in all_text:
                score -= 40
            elif coupon_persons == 2 and ("双人" in name or "二人" in name):
                score -= 30
        elif group_type in ("家庭出行",):
            # 估算家庭人数：带老人通常3-6人，带娃2-4人
            est_family_size = 3
            if "family_with_elderly" in str(hard_constraints):
                est_family_size = 4
            if people_count and isinstance(people_count, (int, float)) and people_count > 0:
                est_family_size = max(est_family_size, int(people_count))
            if coupon_persons >= est_family_size:
                score += 22  # 人数匹配的家庭套餐
            elif coupon_persons == 2:
                score -= 25  # 双人套餐不够家庭吃
            elif coupon_persons == 1:
                score -= 15

        # ---- 同行人适配 ----
        if group_type in ("家庭出行",):
            if sf_child:
                score += 30
            if "亲子" in all_text:
                score += 20
            if str(child_age) in ("0-3", "0-3岁") and ("乐园" in all_text or "游乐" in all_text):
                score += 15
        elif group_type in ("情侣约会",):
            if content_type in ("sub",) and sf_type in ("私人影院", "手作体验"):
                score += 20
            if "浪漫" in all_text or "情侣" in all_text:
                score += 15
        elif group_type in ("朋友聚会",):
            if content_type in ("sub",) and sf_type in ("聚会团建",):
                score += 20
            if "聚会" in all_text:
                score += 15
            # 朋友出行不推情侣/浪漫标签
            if "情侣" in all_text or "浪漫" in all_text or "约会" in all_text:
                score -= 30
        elif group_type in ("独自一人",):
            if "安静" in all_text:
                score += 15
            if content_type in ("dining",):
                score -= 5  # 独自一人不太需要附近餐饮推荐

        if sf_price > 0:
            if sf_price <= budget_max:
                score += 10
            elif sf_price > budget_max * 1.5:
                score -= 30

        if "low_energy" in context_modifiers or "low_walking" in context_modifiers:
            if "低强度" in all_text or "轻松" in all_text:
                score += 10
        if "photo_spot" in context_modifiers:
            if "出片" in all_text or "打卡" in all_text or "拍照" in all_text:
                score += 10
        if "quiet" in context_modifiers:
            if content_type in ("sub",) and sf_type in ("健身瑜伽", "私人影院", "书店"):
                score += 10

        if "pet_allowed" in hard_constraints:
            if "宠物" in all_text:
                score += 20

        # 内容类型基础分：确保多样性
        type_bonus = {"sub": 5, "event": 8, "coupon": 3, "dining": 2, "dish": 1}
        score += type_bonus.get(content_type, 0)

        return score

    @staticmethod
    def _make_badge(content_type, raw, score, group_type, price, orig_price):
        """为强推荐项生成 ≤4 字的鲜艳小标签。"""
        name = str(raw.get("name", raw.get("title", "")))
        sf_type = str(raw.get("type", raw.get("cuisine", "")))
        sf_child = raw.get("child_friendly", False)

        # 优惠券：省钱金额
        if content_type == "coupon" and orig_price and price:
            saved = orig_price - price
            if saved >= 100:
                return f"省{saved}"
            elif saved >= 20:
                return f"减{saved}"

        # 停车场
        if "停车" in name:
            return "停车券"

        # 限时活动
        if content_type == "event":
            date_range = str(raw.get("date_range", ""))
            if "06" in date_range or "07" in date_range:
                return "限时"
            return "活动"

        # 免费
        if price == 0 and content_type != "dish":
            return "免费"

        # 亲子
        if sf_child and group_type in ("家庭出行",):
            return "亲子"

        # 高评分推荐
        if score >= 40:
            return "推荐"

        # 新人/新店
        if "新" in name[:3]:
            return "新"

        return None

    @staticmethod
    def _restaurant_to_dict(r: Optional[Restaurant]) -> Optional[Dict[str, Any]]:
        """将 Restaurant 对象转为字典（复用，避免 restaurant/dinner_restaurant 复制粘贴）。"""
        if r is None:
            return None
        return {
            "name": r.name,
            "cuisine_type": r.cuisine_type,
            "diet_friendly": r.diet_friendly,
            "location": {
                "name": r.location.name,
                "address": r.location.address,
                "district": r.location.district,
            } if r.location else None,
            "price_per_person": r.price_per_person,
        }

    def _plan_to_dict(self, plan: CandidatePlan) -> Dict[str, Any]:
        """将方案转换为字典"""
        return {
            "plan_id": plan.plan_id,
            "title": plan.title,
            "timeline": [
                {
                    "time": f"{item.start_time}-{item.end_time}",
                    "activity": item.activity,
                    "location": item.location,
                    "type": item.type,
                    "description": item.description,
                }
                for item in plan.timeline
            ],
            "total_duration_minutes": plan.total_duration_minutes,
            "activities": [
                {
                    "name": a.name,
                    "type": a.type,
                    "indoor_outdoor": {"indoor": "室内", "outdoor": "户外", "mixed": "室内外结合"}.get(getattr(a, "indoor_outdoor", ""), ""),
                    "child_friendly": a.child_friendly,
                    "need_booking": a.need_booking,
                    "location": {
                        "name": a.location.name,
                        "address": a.location.address,
                        "district": a.location.district,
                    } if a.location else None,
                    "duration_minutes": a.suggested_duration_minutes,
                    "tags": a.tags,
                    "price_per_person": a.price_per_person,
                    "recommendations": self._get_poi_recommendations(a, is_activity=True),
                }
                for a in plan.activities
            ],
            "restaurant": _enrich_restaurant_dict(
                self._restaurant_to_dict(plan.restaurant),
                self._get_poi_recommendations(plan.restaurant, is_activity=False) if plan.restaurant else [],
            ),
            "dinner_restaurant": _enrich_restaurant_dict(
                self._restaurant_to_dict(plan.dinner_restaurant),
                self._get_poi_recommendations(plan.dinner_restaurant, is_activity=False) if plan.dinner_restaurant else [],
            ),
            "route_infos": [
                {
                    "from": ri.from_location.name if ri.from_location else "",
                    "to": ri.to_location.name if ri.to_location else "",
                    "travel_minutes": ri.travel_minutes,
                    "distance_km": ri.distance_km,
                    "transportation": ri.transportation,
                    "traffic_condition": ri.traffic_condition,
                }
                for ri in (plan.route_infos or [])
            ],
            "score": plan.score,
            "score_breakdown": plan.score_breakdown.to_dict(),
            "risks": plan.risks,
            "recommendation_reason": plan.recommendation_reason
        }

    def _execution_to_dict(self, result: ExecutionResult) -> Dict[str, Any]:
        """将执行结果转换为字典"""
        return {
            "all_succeeded": result.all_succeeded,
            "activity_bookings": [
                {"item": b.item_name, "success": b.success, "message": b.message}
                for b in result.activity_booking_status
            ],
            "restaurant_booking": {
                "item": result.restaurant_booking_status.item_name,
                "success": result.restaurant_booking_status.success,
                "message": result.restaurant_booking_status.message
            } if result.restaurant_booking_status else None,
            "orders": [
                {"item": o.item_type, "success": o.success, "message": o.message}
                for o in result.order_status
            ],
            "messages": [
                {"recipient": m.recipient, "success": m.success}
                for m in result.message_status
            ],
            "final_summary": result.final_summary
        }

    def _get_state_dict(self) -> Dict[str, Any]:
        """获取状态字典（含可观测性指标）"""
        return {
            "request_id": self.state.request_id,
            "current_step": self.state.current_step,
            "logs_count": len(self.state.logs),
            "fallback_used": self.state.fallback_used,
            "fallback_reason": self.state.fallback_reason,
            "retry_count": self.state.retry_count,
            "relaxed_constraints": self.state.relaxed_constraints,
            "confirmation_status": self.state.confirmation_status,
            "total_tokens": self.state.total_tokens,
            "total_cost": round(self.state.total_cost, 6),
            "llm_call_count": self.state.llm_call_count,
        }


# ==================== 便捷调用函数 ====================

def run_agent(
    user_input: str,
    user_confirmed: bool = True,
    execute_mode: str = "full",
    locked_constraints: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    便捷函数：运行 Agent

    Args:
        user_input: 用户输入
        user_confirmed: 用户是否已确认（仅 execute_mode="full" 时生效）
        execute_mode: "plan_only" 仅生成方案 / "full" 生成并执行
        locked_constraints: Round 2 锁定的约束条件

    Returns:
        执行结果
    """
    agent = WeekendActivityAgent()
    return agent.run(user_input, user_confirmed=user_confirmed, execute_mode=execute_mode, locked_constraints=locked_constraints)


def run_agent_plan_only(user_input: str, locked_constraints: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """便捷函数：仅生成方案（draft 阶段），返回方案等待用户确认。"""
    return run_agent(user_input, user_confirmed=False, execute_mode="plan_only", locked_constraints=locked_constraints)
