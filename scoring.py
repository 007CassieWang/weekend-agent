"""
方案评分模块
根据 product_rules.yaml 的场景识别结果选择 scoring_profiles 动态评分。
"""

import yaml
from typing import Dict, Any, List, Optional

from schemas import CandidatePlan, ScoreBreakdown, CompanionsType


def load_product_rules() -> Dict[str, Any]:
    """加载完整产品规则。"""
    try:
        with open("config/product_rules.yaml", "r", encoding="utf-8") as f:
            return yaml.safe_load(f) or {}
    except Exception:
        return {}


def _merge_weight_delta(weights: Dict[str, float], delta: Dict[str, float]) -> None:
    for key, value in delta.items():
        weights[key] = max(0.0, float(weights.get(key, 0.0)) + float(value))


def _normalize_weights(weights: Dict[str, float], total: float = 100.0) -> Dict[str, float]:
    current_total = sum(weights.values())
    if current_total <= 0:
        return weights
    return {key: round(value * total / current_total, 2) for key, value in weights.items() if value > 0}


def _labels_as_list(value: Any) -> List[str]:
    if not value:
        return []
    if isinstance(value, list):
        return [str(item) for item in value]
    return [str(value)]


def load_scoring_weights(
    profile_name: Optional[str] = None,
    scenario_labels: Optional[Dict[str, Any]] = None,
) -> Dict[str, float]:
    """
    加载评分权重。
    优先根据 multi-label scoring_strategy 合成权重，缺失时回退到 scoring_profiles/scoring_weights。
    """
    rules = load_product_rules()
    strategy = rules.get("scoring_strategy", {})
    if strategy and scenario_labels:
        weights = dict(strategy.get("base_weights", {}))
        adjustments = strategy.get("label_adjustments", {})

        for companion in _labels_as_list(scenario_labels.get("companion_context")):
            _merge_weight_delta(weights, adjustments.get("companion_context", {}).get(companion, {}))

        for intent in _labels_as_list(scenario_labels.get("primary_intent")):
            _merge_weight_delta(weights, adjustments.get("primary_intent", {}).get(intent, {}))

        for modifier in _labels_as_list(scenario_labels.get("context_modifiers")):
            _merge_weight_delta(weights, adjustments.get("context_modifiers", {}).get(modifier, {}))

        for constraint in _labels_as_list(scenario_labels.get("hard_constraints")):
            _merge_weight_delta(weights, adjustments.get("hard_constraints", {}).get(constraint, {}))

        if weights:
            return _normalize_weights(weights)

    profiles = rules.get("scoring_profiles", {})
    if profile_name and profile_name in profiles:
        return profiles[profile_name]
    return rules.get("scoring_weights", {
        "time_fit": 20,
        "distance_fit": 20,
        "preference_match": 20,
        "budget_fit": 15,
        "group_fit": 10,
        "availability_risk": 15,
    })


def load_failure_fallbacks() -> Dict[str, str]:
    """加载异常兜底策略。"""
    return load_product_rules().get("failure_fallbacks", {})


def load_defaults() -> Dict[str, Any]:
    """加载默认配置。"""
    return load_product_rules().get("defaults", {
        "max_drive_minutes": 30,
        "duration_hours": 4,
    })


def score_time_fit(plan: CandidatePlan, target_duration_hours: int = 4, max_score: float = 20) -> float:
    total_minutes = plan.total_duration_minutes
    target_minutes = target_duration_hours * 60
    min_ideal = target_minutes * 0.8
    max_ideal = target_minutes * 1.2

    if min_ideal <= total_minutes <= max_ideal:
        score = max_score
    elif total_minutes < min_ideal:
        score = max_score * (total_minutes / min_ideal)
    else:
        score = max_score * (max_ideal / total_minutes)

    for activity in plan.activities:
        if activity.duration_minutes < 45:
            score -= 2

    return round(max(0, min(score, max_score)), 1)


def score_distance_fit(plan: CandidatePlan, max_drive_minutes: int = 30, max_score: float = 20) -> float:
    if not plan.route_infos:
        return round(max_score * 0.8, 1)

    total_travel_minutes = sum(route.travel_minutes for route in plan.route_infos)
    max_acceptable_minutes = max_drive_minutes * 2

    if total_travel_minutes <= max_acceptable_minutes:
        score = max_score * (1 - (total_travel_minutes / max_acceptable_minutes) * 0.3)
    else:
        score = max_score * (max_acceptable_minutes / total_travel_minutes) * 0.5

    if any(route.travel_minutes > max_drive_minutes for route in plan.route_infos):
        score *= 0.7

    return round(max(0, min(score, max_score)), 1)


def score_child_friendly(plan: CandidatePlan, max_score: float) -> float:
    score = max_score
    for activity in plan.activities:
        if not activity.child_friendly:
            score -= max_score * 0.4
        elif activity.type in ["indoor_playground", "themed", "handicraft", "art_exhibition", "museum"]:
            score += max_score * 0.1
        if activity.type in ["livehouse", "bar", "extreme_sport"]:
            score -= max_score * 0.5
    if plan.restaurant and not plan.restaurant.child_friendly:
        score -= max_score * 0.2
    return round(max(0, min(score, max_score)), 1)


def score_diet_friendly(plan: CandidatePlan, max_score: float) -> float:
    if not plan.restaurant:
        return round(max_score * 0.5, 1)

    score = max_score * 0.6
    healthy_types = ["light_meal", "cantonese", "japanese", "healthy", "粤菜", "日料", "轻食"]
    heavy_types = ["hotpot", "bbq", "spicy", "xinjiang", "火锅", "烧烤", "川菜"]

    if plan.restaurant.diet_friendly:
        score += max_score * 0.4
    elif plan.restaurant.type in healthy_types or plan.restaurant.cuisine_type in healthy_types:
        score += max_score * 0.3
    elif plan.restaurant.type in heavy_types or plan.restaurant.cuisine_type in heavy_types:
        score -= max_score * 0.3

    return round(max(0, min(score, max_score)), 1)


def score_group_fit(plan: CandidatePlan, max_score: float, activity_preference: str = None) -> float:
    score = max_score * 0.7
    for activity in plan.activities:
        score += max_score * 0.1 if activity.group_friendly else -max_score * 0.15
        if activity.type in ["board_game", "board_game_cafe", "ktv", "sports", "hotpot", "bbq"]:
            score += max_score * 0.05
        if activity_preference == "celebration" and ("亲子" in activity.name or "儿童" in activity.name):
            score -= max_score * 0.3
    if plan.restaurant:
        score += max_score * 0.1 if plan.restaurant.group_friendly else -max_score * 0.1
    return round(max(0, min(score, max_score)), 1)


def score_availability_risk(plan: CandidatePlan, max_score: float) -> float:
    score = max_score
    for activity in plan.activities:
        if activity.need_booking:
            score -= max_score * 0.2
        if activity.queue_minutes > 20:
            score -= max_score * 0.2
        elif activity.queue_minutes > 10:
            score -= max_score * 0.1
        if not activity.is_available:
            score -= max_score * 0.5

    if plan.restaurant:
        if plan.restaurant.need_booking:
            score -= max_score * 0.2
        if plan.restaurant.queue_minutes > 30:
            score -= max_score * 0.3
        elif plan.restaurant.queue_minutes > 15:
            score -= max_score * 0.15
        if not plan.restaurant.is_available:
            score -= max_score * 0.5

    return round(max(0, min(score, max_score)), 1)


def score_preference_match(plan: CandidatePlan, max_score: float, activity_preference: str = None) -> float:
    if not activity_preference:
        return round(max_score * 0.75, 1)

    preference_types = {
        "art": {"art_exhibition", "museum", "handicraft"},
        "outdoor": {"citywalk", "park", "hiking", "botanical_garden"},
        "entertainment": {"ktv", "board_game", "indoor_playground", "music_event"},
        "relax": {"cafe", "onsen", "citywalk", "park", "botanical_garden"},
        "food": {"cafe"},
        "celebration": {"ktv", "music_event", "board_game", "art_exhibition"},
    }
    matched_types = preference_types.get(activity_preference, set())
    if any(activity.type in matched_types for activity in plan.activities):
        return max_score
    return round(max_score * 0.65, 1)


def score_budget_fit(plan: CandidatePlan, max_score: float) -> float:
    activity_cost = sum(activity.price_per_person for activity in plan.activities)
    restaurant_cost = plan.restaurant.price_per_person if plan.restaurant else 0
    total_per_person = activity_cost + restaurant_cost
    if total_per_person <= 250:
        return max_score
    if total_per_person <= 400:
        return round(max_score * 0.75, 1)
    return round(max_score * 0.55, 1)


def is_child_or_family_themed(plan: CandidatePlan) -> bool:
    """判断方案是否明显是亲子/儿童/家庭主题供给。"""
    terms = ["亲子", "儿童", "宝宝", "童话", "游乐区", "儿童餐", "儿童套餐", "家庭餐厅"]
    parts = []
    for activity in plan.activities:
        parts.extend([
            activity.name,
            activity.type,
            activity.description,
            " ".join(activity.tags or []),
        ])
    if plan.restaurant:
        parts.extend([
            plan.restaurant.name,
            plan.restaurant.type,
            plan.restaurant.cuisine_type,
            plan.restaurant.description,
            " ".join(plan.restaurant.tags or []),
            " ".join(plan.restaurant.signature_dishes or []),
        ])
    text = " ".join(parts)
    return any(term in text for term in terms)


def score_generic_profile_component(
    key: str,
    plan: CandidatePlan,
    max_score: float,
    companions: CompanionsType = None,
    activity_preference: str = None,
) -> float:
    """为新 profile 字段提供可解释的通用近似评分。"""
    if key == "time_fit":
        raise ValueError("time_fit requires target duration")
    if key == "distance_fit":
        raise ValueError("distance_fit requires max drive minutes")
    if key == "preference_match":
        return score_preference_match(plan, max_score, activity_preference)
    if key == "budget_fit":
        return score_budget_fit(plan, max_score)
    if key == "group_fit":
        return score_group_fit(plan, max_score, activity_preference)
    if key in {"availability_risk", "booking_risk"}:
        return score_availability_risk(plan, max_score)
    if key in {"child_friendly", "family_comfort"}:
        return score_child_friendly(plan, max_score)
    if key in {"diet_friendly", "food_quality", "food_match"}:
        return score_diet_friendly(plan, max_score)
    if key in {"atmosphere_match", "date_atmosphere", "privacy_comfort", "quiet_comfort"}:
        return score_preference_match(plan, max_score, "relax")
    if key in {"social_interaction", "low_decision_cost"}:
        return score_group_fit(plan, max_score, activity_preference)
    if key in {"low_physical_load", "accessibility", "elder_mobility"}:
        return score_preference_match(plan, max_score, "relax")
    if key in {"pet_friendly", "outdoor_or_open_space", "weather_fit", "activity_intensity_match", "physical_load_match"}:
        return score_preference_match(plan, max_score, "outdoor")
    if key in {"scenery_or_experience", "interest_match", "uniqueness"}:
        return score_preference_match(plan, max_score, activity_preference)
    if key in {"route_smoothness", "place_quality", "service_quality", "coupon_or_discount", "queue_fit", "reservation_fit", "parking_fit", "subway_fit"}:
        return round(max_score * 0.75, 1)
    return round(max_score * 0.7, 1)


def calculate_plan_score(
    plan: CandidatePlan,
    target_duration_hours: int = 4,
    max_drive_minutes: int = 30,
    companions: CompanionsType = None,
    activity_preference: str = None,
    scenario_type: str = "general_leisure",
    scoring_profile: str = "general",
    scenario_labels: Optional[Dict[str, Any]] = None,
    activated_constraints: Optional[List[str]] = None,
    has_child: bool = False,
    diet_goal: str = "none",
) -> tuple[float, ScoreBreakdown]:
    weights = load_scoring_weights(scoring_profile, scenario_labels)
    scores: Dict[str, float] = {}

    for key, max_score in weights.items():
        if key == "child_friendly" and not has_child:
            continue
        if key == "diet_friendly" and diet_goal == "none" and scenario_type != "health_diet":
            continue
        if key == "time_fit":
            scores[key] = score_time_fit(plan, target_duration_hours, max_score)
        elif key == "distance_fit":
            scores[key] = score_distance_fit(plan, max_drive_minutes, max_score)
        else:
            scores[key] = score_generic_profile_component(
                key, plan, max_score, companions, activity_preference
            )

    if not has_child and scenario_type != "family_with_children" and is_child_or_family_themed(plan):
        penalty = min(18.0, sum(weights.values()) * 0.2)
        scores["scenario_mismatch_penalty"] = -round(penalty, 1)

    breakdown = ScoreBreakdown(scores=scores)
    breakdown.time_fit = scores.get("time_fit", 0.0)
    breakdown.distance_fit = scores.get("distance_fit", 0.0)
    breakdown.child_friendly = scores.get("child_friendly", 0.0)
    breakdown.diet_friendly = scores.get("diet_friendly", 0.0)
    breakdown.group_fit = scores.get("group_fit", 0.0)
    breakdown.booking_risk = scores.get("availability_risk", scores.get("booking_risk", 0.0))

    return round(sum(scores.values()), 1), breakdown


def score_plans(
    plans: List[CandidatePlan],
    target_duration_hours: int = 4,
    max_drive_minutes: int = 30,
    companions: CompanionsType = None,
    activity_preference: str = None,
    scenario_type: str = "general_leisure",
    scoring_profile: str = "general",
    scenario_labels: Optional[Dict[str, Any]] = None,
    activated_constraints: Optional[List[str]] = None,
    has_child: bool = False,
    diet_goal: str = "none",
) -> List[CandidatePlan]:
    """对多个候选方案评分并按分数降序排序。"""
    for plan in plans:
        score, breakdown = calculate_plan_score(
            plan,
            target_duration_hours,
            max_drive_minutes,
            companions,
            activity_preference,
            scenario_type,
            scoring_profile,
            scenario_labels,
            activated_constraints,
            has_child,
            diet_goal,
        )
        plan.score = score
        plan.score_breakdown = breakdown

    plans.sort(key=lambda x: x.score, reverse=True)
    return plans


def get_score_explanation(breakdown: ScoreBreakdown) -> Dict[str, str]:
    """获取各项得分的简要解释。"""
    _DIM_LABELS = {
        "time_fit": "时间匹配度",
        "distance_fit": "距离合理度",
        "route_score": "路线顺畅度",
        "availability_risk": "可预约性",
        "match_score": "偏好匹配度",
        "variety_score": "体验丰富度",
        "cost_efficiency": "性价比",
        "weather_fit": "天气适配度",
    }
    explanations = {}
    for key, value in breakdown.to_dict().items():
        label = _DIM_LABELS.get(key, key)
        explanations[key] = f"{label} 得分 {value:.1f}"
    return explanations
